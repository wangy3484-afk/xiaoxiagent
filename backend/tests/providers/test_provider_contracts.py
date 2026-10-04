"""Shared offline contracts for all deterministic provider substitutes."""

import socket
from datetime import UTC, date, datetime

import pytest
from ops_agent.providers import (
    ContentExtractor,
    DeterministicContentExtractor,
    DeterministicModelProvider,
    DeterministicPageFetcher,
    DeterministicSearchProvider,
    ExtractedContent,
    FetchedPage,
    ModelMessage,
    ModelProvider,
    ModelRequest,
    PageFetcher,
    SearchProvider,
    SearchRequest,
    SearchResult,
)
from pydantic import BaseModel, HttpUrl


class ExampleModelOutput(BaseModel):
    primary_scene: str
    rationale: str


def _disable_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("provider substitute attempted network access")

    monkeypatch.setattr(socket, "socket", fail_network)
    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(socket, "getaddrinfo", fail_network)


@pytest.mark.asyncio
async def test_all_provider_substitutes_follow_contracts_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_network(monkeypatch)
    url = HttpUrl("https://example.com/case")
    model: ModelProvider = DeterministicModelProvider(
        {
            "classify_scene": {
                "primary_scene": "retention",
                "rationale": "目标是提升新用户次日留存。",
            }
        }
    )
    search: SearchProvider = DeterministicSearchProvider(
        {
            "留存案例": (
                SearchResult(
                    title="官方留存案例",
                    url=url,
                    snippet="企业公开介绍了分层引导机制。",
                    rank=1,
                ),
            )
        }
    )
    page = FetchedPage(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html; charset=utf-8",
        body="<html><title>案例</title><p>分层引导</p></html>".encode(),
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    fetcher: PageFetcher = DeterministicPageFetcher({str(url): page})
    content = ExtractedContent(
        canonical_url=url,
        title="官方留存案例",
        text="企业公开介绍了分层引导机制。",
        content_hash="a" * 64,
        publication_date=date(2026, 9, 1),
        publisher="示例企业",
    )
    extractor: ContentExtractor = DeterministicContentExtractor({str(url): content})

    model_result = await model.generate_structured(
        ModelRequest(
            purpose="classify_scene",
            messages=(ModelMessage(role="user", content="提升次日留存"),),
        ),
        ExampleModelOutput,
    )
    search_result = await search.search(SearchRequest(query="留存案例", max_results=1))
    fetched = await fetcher.fetch(url)
    extracted = await extractor.extract(fetched)

    assert model_result.output.primary_scene == "retention"
    assert model_result.usage.total_tokens == 0
    assert search_result.results[0].url == url
    assert fetched.body.startswith(b"<html>")
    assert extracted.publication_date == date(2026, 9, 1)
    assert isinstance(model, ModelProvider)
    assert isinstance(search, SearchProvider)
    assert isinstance(fetcher, PageFetcher)
    assert isinstance(extractor, ContentExtractor)


@pytest.mark.asyncio
async def test_substitutes_are_repeatable_and_apply_request_limits() -> None:
    url = HttpUrl("https://example.com/one")
    provider = DeterministicSearchProvider(
        {
            "query": (
                SearchResult(title="第一条", url=url, rank=1),
                SearchResult(
                    title="第二条",
                    url=HttpUrl("https://example.com/two"),
                    rank=2,
                ),
            )
        }
    )
    request = SearchRequest(query="query", max_results=1)

    first = await provider.search(request)
    second = await provider.search(request)

    assert first == second
    assert len(first.results) == 1
    assert len(provider.calls) == 2
