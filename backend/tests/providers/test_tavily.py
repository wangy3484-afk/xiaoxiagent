"""Mock and optional live tests for the bounded Tavily search adapter."""

import json
import os

import httpx
import pytest
from ops_agent.providers import SearchRequest, TavilySearchProvider
from ops_agent.providers.errors import (
    ProviderQuotaError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from pydantic import SecretStr, ValidationError


def _provider(
    transport: httpx.AsyncBaseTransport | None,
    *,
    api_key: str = "test-search-secret",
) -> TavilySearchProvider:
    return TavilySearchProvider(
        base_url="https://search.example/",
        api_key=SecretStr(api_key),
        timeout_seconds=3,
        transport=transport,
    )


@pytest.mark.asyncio
async def test_search_applies_language_pagination_truncation_and_url_deduplication() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-search-secret"
        return httpx.Response(
            200,
            json={
                "request_id": "tavily-request-1",
                "results": [
                    {"title": "A", "url": "https://example.com/a", "content": "a"},
                    {"title": "A duplicate", "url": "https://example.com/a", "content": "dup"},
                    {
                        "title": "B",
                        "url": "https://example.com/b",
                        "content": "b",
                        "score": 0.9,
                    },
                    {"title": "C", "url": "https://example.com/c", "content": "c"},
                    {"title": "D", "url": "https://example.com/d", "content": "d"},
                ],
            },
        )

    result = await _provider(httpx.MockTransport(handler)).search(
        SearchRequest(query="中文运营案例", language="zh-CN", offset=1, max_results=2)
    )

    assert [item.title for item in result.results] == ["B", "C"]
    assert [item.rank for item in result.results] == [2, 3]
    assert result.results[0].provider_metadata["score"] == 0.9
    assert result.request_id == "tavily-request-1"
    assert captured == [
        {
            "query": "中文运营案例",
            "topic": "general",
            "search_depth": "basic",
            "max_results": 3,
            "language": "zh",
            "filter_by_language": True,
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
        }
    ]


@pytest.mark.asyncio
async def test_search_allows_zero_results() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"results": []})
    )

    result = await _provider(transport).search(SearchRequest(query="no matches"))

    assert result.results == ()


@pytest.mark.asyncio
async def test_search_rate_limit_is_classified_and_secret_is_redacted() -> None:
    secret = "must-not-leak-search-key"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"x-request-id": "limited-1"},
            json={"detail": secret},
        )

    provider = _provider(httpx.MockTransport(handler), api_key=secret)
    with pytest.raises(ProviderRateLimitError) as captured:
        await provider.search(SearchRequest(query="query"))

    assert captured.value.retryable is True
    assert captured.value.request_id == "limited-1"
    assert secret not in str(captured.value)
    assert secret not in repr(provider.__dict__)


@pytest.mark.asyncio
async def test_search_quota_exhaustion_is_not_retryable() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(432, json={"detail": "quota exceeded"})
    )

    with pytest.raises(ProviderQuotaError) as captured:
        await _provider(transport).search(SearchRequest(query="query"))

    assert captured.value.retryable is False
    assert captured.value.category == "quota"


@pytest.mark.asyncio
async def test_search_timeout_is_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("unsafe timeout body", request=request)

    with pytest.raises(ProviderTimeoutError) as captured:
        await _provider(httpx.MockTransport(handler)).search(SearchRequest(query="query"))

    assert captured.value.retryable is True
    assert "unsafe timeout body" not in str(captured.value)


def test_search_request_rejects_windows_over_provider_limit() -> None:
    with pytest.raises(ValidationError, match="offset plus max_results"):
        SearchRequest(query="query", offset=15, max_results=6)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tavily_live_smoke_when_explicit_test_key_is_available() -> None:
    api_key = os.getenv("OPS_AGENT_TEST_TAVILY_API_KEY")
    if not api_key:
        pytest.skip("OPS_AGENT_TEST_TAVILY_API_KEY is not configured")

    provider = TavilySearchProvider(
        base_url=os.getenv("OPS_AGENT_TEST_TAVILY_BASE_URL", "https://api.tavily.com"),
        api_key=SecretStr(api_key),
        timeout_seconds=20,
    )
    result = await provider.search(
        SearchRequest(query="site:tavily.com Tavily Search API", language="en", max_results=1)
    )

    assert len(result.results) <= 1
    assert result.provider == "tavily"
