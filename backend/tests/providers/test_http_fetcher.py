"""Security tests for the bounded HTML page fetcher."""

import asyncio
from collections.abc import Sequence

import httpx
import pytest
from ops_agent.providers import SecureHttpPageFetcher
from ops_agent.providers.errors import (
    ContentRejectedError,
    ProviderTimeoutError,
    UnsafeUrlError,
)
from pydantic import HttpUrl


async def _public_resolver(_host: str, _port: int) -> Sequence[str]:
    return ("93.184.216.34",)


def _fetcher(
    handler: httpx.MockTransport,
    *,
    resolver: object = _public_resolver,
    max_bytes: int = 100,
    max_redirects: int = 2,
    timeout_seconds: float = 1,
) -> SecureHttpPageFetcher:
    return SecureHttpPageFetcher(
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        resolver=resolver,  # type: ignore[arg-type]
        transport=handler,
    )


@pytest.mark.asyncio
async def test_fetches_html_and_revalidates_dns_after_redirect() -> None:
    resolutions: list[tuple[str, int]] = []

    async def resolver(host: str, port: int) -> Sequence[str]:
        resolutions.append((host, port))
        return ("93.184.216.34",)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8", "etag": "v1"},
            content=b"<html>ok</html>",
        )

    result = await _fetcher(httpx.MockTransport(handler), resolver=resolver).fetch(
        HttpUrl("https://example.com/start")
    )

    assert result.final_url == HttpUrl("https://example.com/final")
    assert result.redirect_chain == (HttpUrl("https://example.com/final"),)
    assert result.body == b"<html>ok</html>"
    assert result.response_headers == {
        "content-type": "text/html; charset=utf-8",
        "content-length": "15",
        "etag": "v1",
    }
    assert resolutions == [("example.com", 443), ("example.com", 443)]


@pytest.mark.asyncio
async def test_blocks_direct_private_destination_before_network_access() -> None:
    requests = 0

    async def resolver(_host: str, _port: int) -> Sequence[str]:
        return ("127.0.0.1",)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200)

    with pytest.raises(UnsafeUrlError):
        await _fetcher(httpx.MockTransport(handler), resolver=resolver).fetch(
            HttpUrl("http://internal.example/")
        )

    assert requests == 0


@pytest.mark.asyncio
async def test_blocks_redirect_to_cloud_metadata_address() -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    with pytest.raises(UnsafeUrlError):
        await _fetcher(httpx.MockTransport(handler)).fetch(
            HttpUrl("https://example.com/start")
        )

    assert requests == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "text/html", "content-length": "101"},
        {"content-type": "text/html"},
    ],
)
async def test_rejects_oversized_response_with_or_without_content_length(
    headers: dict[str, str],
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, headers=headers, content=b"x" * 101)
    )

    with pytest.raises(ContentRejectedError, match="response size limit"):
        await _fetcher(transport, max_bytes=100).fetch(HttpUrl("https://example.com/"))


@pytest.mark.asyncio
async def test_rejects_non_html_content_without_retaining_body() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"sensitive document body",
        )
    )

    with pytest.raises(ContentRejectedError) as captured:
        await _fetcher(transport).fetch(HttpUrl("https://example.com/file"))

    assert "sensitive document body" not in str(captured.value)


@pytest.mark.asyncio
async def test_total_timeout_includes_dns_resolution() -> None:
    async def slow_resolver(_host: str, _port: int) -> Sequence[str]:
        await asyncio.sleep(1)
        return ("93.184.216.34",)

    transport = httpx.MockTransport(lambda _request: httpx.Response(200))
    with pytest.raises(ProviderTimeoutError):
        await _fetcher(
            transport,
            resolver=slow_resolver,
            timeout_seconds=0.01,
        ).fetch(HttpUrl("https://example.com/"))
