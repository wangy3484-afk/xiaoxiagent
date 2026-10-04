"""Deterministic provider substitutes for offline workflow and contract tests."""

import json
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
from typing import Any

from pydantic import BaseModel, HttpUrl

from ops_agent.providers.contracts import (
    ExtractedContent,
    FetchedPage,
    ModelRequest,
    ModelUsage,
    SearchRequest,
    SearchResponse,
    SearchResult,
    StructuredModelResult,
)


class DeterministicModelProvider:
    """Validate scripted dictionaries through the requested Pydantic schema."""

    def __init__(
        self,
        responses: Mapping[str, Mapping[str, Any]],
        *,
        model: str = "deterministic-model",
    ) -> None:
        self._responses = deepcopy(dict(responses))
        self.model = model
        self.calls: list[ModelRequest] = []

    async def generate_structured[OutputT: BaseModel](
        self,
        request: ModelRequest,
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        self.calls.append(request)
        scripted = deepcopy(self._responses[request.purpose])
        output = output_schema.model_validate(scripted)
        request_fingerprint = sha256(
            json.dumps(
                request.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:16]
        return StructuredModelResult[OutputT](
            output=output,
            provider="deterministic",
            model=self.model,
            request_id=f"fake-model-{request_fingerprint}",
            usage=ModelUsage(input_tokens=0, output_tokens=0),
        )


class DeterministicSearchProvider:
    def __init__(self, results: Mapping[str, tuple[SearchResult, ...]]) -> None:
        self._results = dict(results)
        self.calls: list[SearchRequest] = []

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.calls.append(request)
        end = request.offset + request.max_results
        results = self._results.get(request.query, ())[request.offset : end]
        return SearchResponse(
            query=request.query,
            results=results,
            provider="deterministic",
            request_id=_stable_id("search", request.model_dump(mode="json")),
        )


class DeterministicPageFetcher:
    def __init__(self, pages: Mapping[str, FetchedPage]) -> None:
        self._pages = dict(pages)
        self.calls: list[HttpUrl] = []

    async def fetch(self, url: HttpUrl) -> FetchedPage:
        self.calls.append(url)
        return self._pages[str(url)].model_copy(deep=True)


class DeterministicContentExtractor:
    def __init__(self, contents: Mapping[str, ExtractedContent]) -> None:
        self._contents = dict(contents)
        self.calls: list[FetchedPage] = []

    async def extract(self, page: FetchedPage) -> ExtractedContent:
        self.calls.append(page)
        return self._contents[str(page.final_url)].model_copy(deep=True)


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    digest = sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:16]
    return f"fake-{prefix}-{digest}"
