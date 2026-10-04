"""Safe structured observability for API, worker, graph, and providers."""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, HttpUrl

from ops_agent.config import Settings
from ops_agent.providers.contracts import (
    ContentExtractor,
    ExtractedContent,
    FetchedPage,
    ModelProvider,
    ModelRequest,
    PageFetcher,
    SearchProvider,
    SearchRequest,
    SearchResponse,
    StructuredModelResult,
)
from ops_agent.providers.wiring import ProviderSet

LOGGER = logging.getLogger("ops_agent.observability")
_REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)
_JOB_ID: ContextVar[str | None] = ContextVar("job_id", default=None)
_THREAD_ID: ContextVar[str | None] = ContextVar("thread_id", default=None)
_SENSITIVE_KEY_PARTS = ("secret", "password", "api_key", "cookie", "body")
_SENSITIVE_TOKEN_KEYS = {
    "token",
    "access_token",
    "refresh_token",
    "session_token",
    "token_hash",
}


def configure_observability(level: str) -> None:
    """Apply the level and add a fallback stream only when the host has none."""
    LOGGER.setLevel(getattr(logging, level.upper(), logging.INFO))
    root = logging.getLogger()
    if not root.handlers and not LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)


@dataclass
class RunMetrics:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    search_calls: int = 0
    search_results: int = 0
    fetch_attempts: int = 0
    fetch_successes: int = 0
    estimated_cost: float = 0.0

    def summary(self) -> dict[str, int | float]:
        success_rate = (
            self.fetch_successes / self.fetch_attempts if self.fetch_attempts else 0.0
        )
        return {
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "search_calls": self.search_calls,
            "search_results": self.search_results,
            "fetch_attempts": self.fetch_attempts,
            "fetch_successes": self.fetch_successes,
            "fetch_success_rate": round(success_rate, 4),
            "estimated_cost": round(self.estimated_cost, 6),
        }


def current_request_id() -> str | None:
    return _REQUEST_ID.get()


@contextmanager
def bind_observability_context(
    *,
    request_id: str | None = None,
    job_id: str | None = None,
    thread_id: str | None = None,
) -> Iterator[None]:
    tokens = push_observability_context(
        request_id=request_id,
        job_id=job_id,
        thread_id=thread_id,
    )
    try:
        yield
    finally:
        reset_observability_context(tokens)


def push_observability_context(
    *,
    request_id: str | None = None,
    job_id: str | None = None,
    thread_id: str | None = None,
) -> list[tuple[ContextVar[str | None], Any]]:
    tokens: list[tuple[ContextVar[str | None], Any]] = []
    for variable, value in (
        (_REQUEST_ID, request_id),
        (_JOB_ID, job_id),
        (_THREAD_ID, thread_id),
    ):
        if value is not None:
            tokens.append((variable, variable.set(value)))
    return tokens


def reset_observability_context(
    tokens: list[tuple[ContextVar[str | None], Any]],
) -> None:
    for variable, token in reversed(tokens):
        variable.reset(token)


def log_event(
    event: str,
    *,
    level: int = logging.INFO,
    **fields: object,
) -> None:
    payload: dict[str, object] = {
        "event": event,
        "request_id": _REQUEST_ID.get(),
        "job_id": _JOB_ID.get(),
        "thread_id": _THREAD_ID.get(),
        **fields,
    }
    LOGGER.log(
        level,
        json.dumps(_sanitize(payload), ensure_ascii=False, sort_keys=True),
    )


def _sanitize(value: object, *, key: str = "") -> object:
    normalized_key = key.lower()
    if normalized_key in _SENSITIVE_TOKEN_KEYS or any(
        part in normalized_key for part in _SENSITIVE_KEY_PARTS
    ):
        return "[REDACTED]"
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:300]
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list | tuple):
        return [_sanitize(item) for item in value[:50]]
    return type(value).__name__


class ObservedModelProvider:
    def __init__(
        self,
        inner: ModelProvider,
        metrics: RunMetrics,
        settings: Settings,
    ) -> None:
        self.inner = inner
        self.metrics = metrics
        self.settings = settings

    async def generate_structured[OutputT: BaseModel](
        self,
        request: ModelRequest,
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        started = perf_counter()
        try:
            result = await self.inner.generate_structured(request, output_schema)
        except Exception as exc:
            log_event(
                "model_call_failed",
                level=logging.WARNING,
                purpose=request.purpose,
                duration_ms=_elapsed_ms(started),
                error_type=type(exc).__name__,
            )
            raise
        self.metrics.model_calls += 1
        self.metrics.input_tokens += result.usage.input_tokens
        self.metrics.output_tokens += result.usage.output_tokens
        self.metrics.estimated_cost += (
            result.usage.input_tokens
            * self.settings.model_input_cost_per_million_tokens
            + result.usage.output_tokens
            * self.settings.model_output_cost_per_million_tokens
        ) / 1_000_000
        log_event(
            "model_call_completed",
            purpose=request.purpose,
            provider=result.provider,
            model=result.model,
            provider_request_id=result.request_id,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            duration_ms=_elapsed_ms(started),
        )
        return result


class ObservedSearchProvider:
    def __init__(self, inner: SearchProvider, metrics: RunMetrics) -> None:
        self.inner = inner
        self.metrics = metrics

    async def search(self, request: SearchRequest) -> SearchResponse:
        started = perf_counter()
        self.metrics.search_calls += 1
        try:
            result = await self.inner.search(request)
        except Exception as exc:
            log_event(
                "search_call_failed",
                level=logging.WARNING,
                duration_ms=_elapsed_ms(started),
                error_type=type(exc).__name__,
            )
            raise
        self.metrics.search_results += len(result.results)
        log_event(
            "search_call_completed",
            provider=result.provider,
            provider_request_id=result.request_id,
            result_count=len(result.results),
            duration_ms=_elapsed_ms(started),
        )
        return result


class ObservedPageFetcher:
    def __init__(self, inner: PageFetcher, metrics: RunMetrics) -> None:
        self.inner = inner
        self.metrics = metrics

    async def fetch(self, url: HttpUrl) -> FetchedPage:
        started = perf_counter()
        self.metrics.fetch_attempts += 1
        host = urlsplit(str(url)).hostname
        try:
            result = await self.inner.fetch(url)
        except Exception as exc:
            log_event(
                "page_fetch_failed",
                level=logging.WARNING,
                host=host,
                duration_ms=_elapsed_ms(started),
                error_type=type(exc).__name__,
            )
            raise
        self.metrics.fetch_successes += 1
        log_event(
            "page_fetch_completed",
            host=host,
            status_code=result.status_code,
            content_type=result.content_type,
            duration_ms=_elapsed_ms(started),
        )
        return result


class ObservedContentExtractor:
    def __init__(self, inner: ContentExtractor) -> None:
        self.inner = inner

    async def extract(self, page: FetchedPage) -> ExtractedContent:
        started = perf_counter()
        try:
            result = await self.inner.extract(page)
        except Exception as exc:
            log_event(
                "content_extraction_failed",
                level=logging.WARNING,
                duration_ms=_elapsed_ms(started),
                error_type=type(exc).__name__,
            )
            raise
        log_event("content_extraction_completed", duration_ms=_elapsed_ms(started))
        return result


def observe_provider_set(
    providers: ProviderSet,
    metrics: RunMetrics,
    settings: Settings,
) -> ProviderSet:
    return ProviderSet(
        model=ObservedModelProvider(providers.model, metrics, settings),
        search=ObservedSearchProvider(providers.search, metrics),
        fetcher=ObservedPageFetcher(providers.fetcher, metrics),
        extractor=ObservedContentExtractor(providers.extractor),
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1_000))
