"""Tavily Search adapter with bounded, supplier-neutral results."""

from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import HttpUrl, SecretStr, ValidationError

from ops_agent.providers.contracts import (
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from ops_agent.providers.errors import (
    ProviderAuthenticationError,
    ProviderQuotaError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)


class TavilySearchProvider:
    """Call Tavily Search while enforcing the common 20-result window."""

    provider_name = "tavily"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = httpx.Timeout(timeout_seconds)
        self.transport = transport

    async def search(self, request: SearchRequest) -> SearchResponse:
        response = await self._post(self._request_payload(request))
        request_id = response.headers.get("x-request-id")
        payload = self._response_json(response, request_id)
        request_id = request_id or _optional_string(payload.get("request_id"))

        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise ProviderResponseError(
                "search provider returned an unexpected response shape",
                provider=self.provider_name,
                retryable=False,
                request_id=request_id,
            )

        unique_results = _normalize_results(raw_results)
        end = request.offset + request.max_results
        page = unique_results[request.offset : end]
        ranked = tuple(
            result.model_copy(update={"rank": request.offset + index})
            for index, result in enumerate(page, start=1)
        )
        return SearchResponse(
            query=request.query,
            results=ranked,
            provider=self.provider_name,
            request_id=request_id,
        )

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                transport=self.transport,
                headers={
                    "Authorization": f"Bearer {self.api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
            ) as client:
                response = await client.post(f"{self.base_url}/search", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "search provider request timed out",
                provider=self.provider_name,
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(
                "search provider request failed",
                provider=self.provider_name,
                retryable=True,
            ) from exc

        request_id = response.headers.get("x-request-id")
        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(
                "search provider rejected authentication",
                provider=self.provider_name,
                retryable=False,
                request_id=request_id,
            )
        if response.status_code == 429:
            raise ProviderRateLimitError(
                "search provider limit exceeded",
                provider=self.provider_name,
                retryable=True,
                request_id=request_id,
            )
        if response.status_code in (432, 433):
            raise ProviderQuotaError(
                "search provider quota is exhausted",
                provider=self.provider_name,
                retryable=False,
                request_id=request_id,
            )
        if response.is_error:
            raise ProviderResponseError(
                f"search provider returned HTTP {response.status_code}",
                provider=self.provider_name,
                retryable=response.status_code >= 500,
                request_id=request_id,
            )
        return response

    def _request_payload(self, request: SearchRequest) -> dict[str, Any]:
        language = request.language.split("-", maxsplit=1)[0].lower()
        return {
            "query": request.query,
            "topic": "general",
            "search_depth": "basic",
            "max_results": request.offset + request.max_results,
            "language": language,
            "filter_by_language": True,
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
        }

    def _response_json(
        self, response: httpx.Response, request_id: str | None
    ) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                "search provider returned malformed JSON",
                provider=self.provider_name,
                retryable=False,
                request_id=request_id,
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderResponseError(
                "search provider returned an unexpected response shape",
                provider=self.provider_name,
                retryable=False,
                request_id=request_id,
            )
        return payload


def _normalize_results(raw_results: list[object]) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    for item in raw_results:
        if not isinstance(item, Mapping):
            continue
        title = _optional_string(item.get("title"))
        url_value = _optional_string(item.get("url"))
        if title is None or url_value is None:
            continue
        try:
            url = HttpUrl(url_value)
        except ValidationError:
            continue
        deduplication_key = str(url).casefold()
        if deduplication_key in seen_urls:
            continue
        seen_urls.add(deduplication_key)
        metadata = {
            key: value
            for key in ("score", "published_date")
            if (value := item.get(key)) is None
            or isinstance(value, (str, int, float, bool))
        }
        try:
            results.append(
                SearchResult(
                    title=title[:500],
                    url=url,
                    snippet=(_optional_string(item.get("content")) or "")[:2_000],
                    rank=len(results) + 1,
                    provider_metadata=metadata,
                )
            )
        except ValidationError:
            continue
    return results


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
