"""Bounded HTML fetcher with DNS-aware SSRF protection."""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
from pydantic import HttpUrl, ValidationError

from ops_agent.providers.contracts import FetchedPage
from ops_agent.providers.errors import (
    ContentRejectedError,
    ProviderResponseError,
    ProviderTimeoutError,
    UnsafeUrlError,
)

Resolver = Callable[[str, int], Awaitable[Sequence[str]]]

_ALLOWED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_SENSITIVE_METADATA_ADDRESSES = frozenset(
    {
        ipaddress.ip_address("168.63.129.16"),  # Azure platform virtual IP
        ipaddress.ip_address("169.254.169.254"),
        ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud metadata
    }
)


class SecureHttpPageFetcher:
    """Fetch public HTML only, revalidating DNS before every redirect hop."""

    provider_name = "page-fetcher"

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_bytes: int,
        max_redirects: int,
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.resolver = resolver or _resolve_host
        self.transport = transport

    async def fetch(self, url: HttpUrl) -> FetchedPage:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._fetch_within_deadline(url)
        except TimeoutError as exc:
            raise ProviderTimeoutError(
                "page fetch exceeded its total time limit",
                provider=self.provider_name,
                retryable=True,
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "page fetch timed out",
                provider=self.provider_name,
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(
                "page fetch request failed",
                provider=self.provider_name,
                retryable=True,
            ) from exc

    async def _fetch_within_deadline(self, original_url: HttpUrl) -> FetchedPage:
        current_url = original_url
        redirect_chain: list[HttpUrl] = []
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(
            timeout=timeout,
            transport=self.transport,
            follow_redirects=False,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "OpsStrategyAgent/0.1 research-fetcher",
            },
        ) as client:
            while True:
                await self._validate_public_destination(current_url)
                async with client.stream("GET", str(current_url)) as response:
                    if response.status_code in _REDIRECT_STATUS_CODES:
                        if len(redirect_chain) >= self.max_redirects:
                            raise ContentRejectedError(
                                "page exceeded the redirect limit",
                                provider=self.provider_name,
                                retryable=False,
                            )
                        location = response.headers.get("location")
                        if location is None:
                            raise ContentRejectedError(
                                "redirect response omitted its destination",
                                provider=self.provider_name,
                                retryable=False,
                            )
                        current_url = _redirect_url(current_url, location)
                        redirect_chain.append(current_url)
                        continue

                    if response.is_error:
                        raise ProviderResponseError(
                            f"page returned HTTP {response.status_code}",
                            provider=self.provider_name,
                            retryable=response.status_code >= 500,
                        )
                    content_type = _validated_content_type(response)
                    _validate_content_length(response, self.max_bytes)
                    body = await _read_bounded_body(response, self.max_bytes)
                    return FetchedPage(
                        requested_url=original_url,
                        final_url=current_url,
                        status_code=response.status_code,
                        content_type=content_type,
                        body=body,
                        fetched_at=datetime.now(UTC),
                        redirect_chain=tuple(redirect_chain),
                        response_headers=_safe_response_headers(response),
                    )

    async def _validate_public_destination(self, url: HttpUrl) -> None:
        if url.scheme not in ("http", "https"):
            raise UnsafeUrlError(
                "only HTTP and HTTPS destinations are allowed",
                provider=self.provider_name,
                retryable=False,
            )
        if url.username is not None or url.password is not None:
            raise UnsafeUrlError(
                "URL user information is not allowed",
                provider=self.provider_name,
                retryable=False,
            )
        host = url.host
        if host is None:
            raise UnsafeUrlError(
                "URL host is required",
                provider=self.provider_name,
                retryable=False,
            )
        port = url.port or (443 if url.scheme == "https" else 80)
        try:
            literal_address = ipaddress.ip_address(host)
        except ValueError:
            try:
                addresses = await self.resolver(host, port)
            except OSError as exc:
                raise ProviderResponseError(
                    "page host could not be resolved",
                    provider=self.provider_name,
                    retryable=True,
                ) from exc
            if not addresses:
                raise ProviderResponseError(
                    "page host resolved to no addresses",
                    provider=self.provider_name,
                    retryable=True,
                ) from None
            for value in addresses:
                try:
                    address = ipaddress.ip_address(value)
                except ValueError as exc:
                    raise UnsafeUrlError(
                        "page host resolved to an invalid address",
                        provider=self.provider_name,
                        retryable=False,
                    ) from exc
                _require_public_address(address)
        else:
            _require_public_address(literal_address)


async def _resolve_host(host: str, port: int) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(record[4][0] for record in records))


def _require_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if address in _SENSITIVE_METADATA_ADDRESSES or not address.is_global:
        raise UnsafeUrlError(
            "destination address is not public",
            provider=SecureHttpPageFetcher.provider_name,
            retryable=False,
        )


def _redirect_url(current_url: HttpUrl, location: str) -> HttpUrl:
    try:
        return HttpUrl(urljoin(str(current_url), location))
    except ValidationError as exc:
        raise UnsafeUrlError(
            "redirect destination is invalid",
            provider=SecureHttpPageFetcher.provider_name,
            retryable=False,
        ) from exc


def _validated_content_type(response: httpx.Response) -> str:
    value: str = response.headers.get("content-type", "")
    media_type = value.split(";", maxsplit=1)[0].strip().lower()
    if media_type not in _ALLOWED_CONTENT_TYPES:
        raise ContentRejectedError(
            "page content type is not supported",
            provider=SecureHttpPageFetcher.provider_name,
            retryable=False,
        )
    return value


def _validate_content_length(response: httpx.Response, max_bytes: int) -> None:
    value = response.headers.get("content-length")
    if value is None:
        return
    try:
        length = int(value)
    except ValueError:
        return
    if length > max_bytes:
        raise ContentRejectedError(
            "page exceeds the response size limit",
            provider=SecureHttpPageFetcher.provider_name,
            retryable=False,
        )


async def _read_bounded_body(response: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > max_bytes:
            raise ContentRejectedError(
                "page exceeds the response size limit",
                provider=SecureHttpPageFetcher.provider_name,
                retryable=False,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _safe_response_headers(response: httpx.Response) -> dict[str, str]:
    allowed = ("content-type", "content-length", "etag", "last-modified")
    return {name: response.headers[name] for name in allowed if name in response.headers}
