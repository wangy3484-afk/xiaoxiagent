"""Fixture tests for deterministic HTML normalization and extraction."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from ops_agent.providers import FetchedPage, HtmlContentExtractor
from ops_agent.providers.errors import ContentExtractionError
from ops_agent.providers.html_extractor import normalize_url
from pydantic import HttpUrl

FIXTURES = Path(__file__).parents[1] / "fixtures" / "extraction"


def _page(name: str, url: str = "https://Example.COM/source/page") -> FetchedPage:
    return FetchedPage(
        requested_url=HttpUrl(url),
        final_url=HttpUrl(url),
        status_code=200,
        content_type="text/html; charset=utf-8",
        body=(FIXTURES / name).read_bytes(),
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_extracts_chinese_article_canonical_url_hash_and_date() -> None:
    result = await HtmlContentExtractor().extract(_page("chinese_article.html"))

    assert result.title == "会员分层运营案例"
    assert "高意向新用户" in result.text
    assert "全站导航" not in result.text
    assert "动态脚本" not in result.text
    assert result.canonical_url == HttpUrl(
        "https://example.com/cases/member-growth?category=retention"
    )
    assert result.publication_date == date(2026, 9, 12)
    assert result.publisher == "示例企业研究院"
    assert len(result.content_hash) == 64


@pytest.mark.asyncio
async def test_missing_publication_date_remains_explicitly_unknown() -> None:
    result = await HtmlContentExtractor().extract(_page("missing_date.html"))

    assert result.publication_date is None
    assert result.metadata["publication_date_status"] == "unknown"


@pytest.mark.asyncio
async def test_same_normalized_content_has_same_hash_across_urls() -> None:
    extractor = HtmlContentExtractor()
    first = await extractor.extract(
        _page("missing_date.html", "https://example.com/article?utm_source=a")
    )
    second = await extractor.extract(
        _page("missing_date.html", "https://mirror.example.org/copied")
    )

    assert first.content_hash == second.content_hash
    assert first.canonical_url != second.canonical_url


@pytest.mark.asyncio
async def test_dynamic_noise_is_excluded_and_json_ld_date_is_used() -> None:
    result = await HtmlContentExtractor().extract(_page("dynamic_noise.html"))

    assert "四阶段节奏" in result.text
    assert "首页 产品" not in result.text
    assert "Accept all cookies" not in result.text
    assert "提示注入" not in result.text
    assert result.publication_date == date(2026, 8, 21)


@pytest.mark.asyncio
async def test_extraction_failure_is_safe_and_does_not_invent_body() -> None:
    with pytest.raises(ContentExtractionError, match="did not contain"):
        await HtmlContentExtractor().extract(_page("empty.html"))


def test_normalize_url_removes_default_port_fragment_tracking_and_dot_segments() -> None:
    result = normalize_url(
        "HTTPS://Example.COM:443/a/../b/?z=2&utm_campaign=x&a=1#section"
    )

    assert result == HttpUrl("https://example.com/b/?a=1&z=2")
