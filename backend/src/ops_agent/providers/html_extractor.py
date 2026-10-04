"""Deterministic HTML extraction and canonicalization for research evidence."""

import json
import posixpath
import re
from datetime import date, datetime
from hashlib import sha256
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from pydantic import HttpUrl, ValidationError

from ops_agent.providers.contracts import ExtractedContent, FetchedPage
from ops_agent.providers.errors import ContentExtractionError

_IGNORED_TAGS = frozenset(
    {
        "aside",
        "button",
        "canvas",
        "footer",
        "form",
        "header",
        "nav",
        "noscript",
        "script",
        "style",
        "svg",
        "template",
    }
)
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
_TRACKING_PARAMETERS = frozenset(
    {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "referrer", "spm"}
)
_NOISE_PATTERNS = (
    re.compile(r"^(accept|manage|reject) (all )?cookies?$", re.IGNORECASE),
    re.compile(r"^(登录|注册|返回顶部|同意全部|隐私设置)$"),
    re.compile(r"javascript (is )?(required|disabled)", re.IGNORECASE),
)
_DATE_KEYS = frozenset(
    {
        "article:published_time",
        "date",
        "datepublished",
        "publishdate",
        "pubdate",
    }
)


class HtmlContentExtractor:
    provider_name = "html-extractor"

    async def extract(self, page: FetchedPage) -> ExtractedContent:
        document = _ResearchHtmlParser()
        try:
            document.feed(_decode_body(page))
            document.close()
        except (UnicodeError, ValueError) as exc:
            raise ContentExtractionError(
                "HTML document could not be parsed",
                provider=self.provider_name,
                retryable=False,
            ) from exc

        text = _normalized_main_text(document)
        title = _normalized_title(document)
        if not title or not text:
            raise ContentExtractionError(
                "HTML document did not contain extractable title and body text",
                provider=self.provider_name,
                retryable=False,
            )
        canonical_url = normalize_url(
            document.canonical_href or str(page.final_url),
            base_url=str(page.final_url),
        )
        publication_date = _publication_date(document)
        return ExtractedContent(
            canonical_url=canonical_url,
            title=title[:500],
            text=text,
            content_hash=sha256(text.encode("utf-8")).hexdigest(),
            publication_date=publication_date,
            publisher=document.publisher,
            metadata={
                "publication_date_status": (
                    "verified" if publication_date is not None else "unknown"
                )
            },
        )


def normalize_url(value: str, *, base_url: str | None = None) -> HttpUrl:
    """Return a stable public HTTP URL without fragments or tracking parameters."""
    absolute = urljoin(base_url, value) if base_url is not None else value
    parsed = urlsplit(absolute)
    if parsed.scheme.lower() not in ("http", "https") or parsed.hostname is None:
        raise ContentExtractionError(
            "canonical URL is not HTTP or HTTPS",
            provider=HtmlContentExtractor.provider_name,
            retryable=False,
        )
    if parsed.username is not None or parsed.password is not None:
        raise ContentExtractionError(
            "canonical URL contains user information",
            provider=HtmlContentExtractor.provider_name,
            retryable=False,
        )
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ContentExtractionError(
            "canonical URL has an invalid port",
            provider=HtmlContentExtractor.provider_name,
            retryable=False,
        ) from exc
    default_port = 80 if scheme == "http" else 443
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = host if port in (None, default_port) else f"{host}:{port}"
    path = posixpath.normpath(parsed.path or "/")
    if parsed.path.endswith("/") and not path.endswith("/"):
        path += "/"
    if not path.startswith("/"):
        path = f"/{path}"
    query_items = sorted(
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in _TRACKING_PARAMETERS
    )
    normalized = urlunsplit((scheme, netloc, path, urlencode(query_items), ""))
    try:
        return HttpUrl(normalized)
    except ValidationError as exc:
        raise ContentExtractionError(
            "canonical URL is invalid",
            provider=HtmlContentExtractor.provider_name,
            retryable=False,
        ) from exc


class _ResearchHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.preferred_text: list[str] = []
        self.fallback_text: list[str] = []
        self.title_text: list[str] = []
        self.heading_text: list[str] = []
        self.json_ld_text: list[str] = []
        self.canonical_href: str | None = None
        self.publisher: str | None = None
        self.date_candidates: list[str] = []
        self._json_ld_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.lower()
        attributes = {key.lower(): value for key, value in attrs if value is not None}
        if tag == "link" and "canonical" in attributes.get("rel", "").lower().split():
            self.canonical_href = attributes.get("href") or self.canonical_href
        if tag == "meta":
            self._read_meta(attributes)
        if tag == "time" and attributes.get("datetime"):
            self.date_candidates.append(attributes["datetime"])
        if tag not in _VOID_TAGS:
            self.stack.append(tag)
            if tag == "script" and attributes.get("type", "").lower() == "application/ld+json":
                self._json_ld_depth = len(self.stack)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag not in self.stack:
            return
        reverse_index = self.stack[::-1].index(tag)
        index = len(self.stack) - reverse_index - 1
        del self.stack[index:]
        if self._json_ld_depth > len(self.stack):
            self._json_ld_depth = 0

    def handle_data(self, data: str) -> None:
        value = _collapse_space(data)
        if not value:
            return
        if self._json_ld_depth:
            self.json_ld_text.append(data)
            return
        if "title" in self.stack:
            self.title_text.append(value)
            return
        if "h1" in self.stack:
            self.heading_text.append(value)
        if any(tag in _IGNORED_TAGS for tag in self.stack):
            return
        self.fallback_text.append(value)
        if any(tag in {"article", "main"} for tag in self.stack):
            self.preferred_text.append(value)

    def _read_meta(self, attributes: dict[str, str]) -> None:
        key = (attributes.get("property") or attributes.get("name") or "").lower()
        content = attributes.get("content", "").strip()
        if not content:
            return
        if key in _DATE_KEYS:
            self.date_candidates.append(content)
        elif key in {"og:site_name", "application-name", "publisher"}:
            self.publisher = content[:300]
        elif key in {"og:title", "twitter:title"} and not self.title_text:
            self.title_text.append(_collapse_space(content))


def _decode_body(page: FetchedPage) -> str:
    charset_match = re.search(r"charset\s*=\s*['\"]?([^;\s'\"]+)", page.content_type, re.I)
    encodings = [charset_match.group(1)] if charset_match else []
    encodings.extend(["utf-8", "gb18030"])
    for encoding in encodings:
        try:
            return page.body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return page.body.decode("utf-8", errors="replace")


def _normalized_title(document: _ResearchHtmlParser) -> str:
    values = document.title_text or document.heading_text
    return _collapse_space(" ".join(values))


def _normalized_main_text(document: _ResearchHtmlParser) -> str:
    preferred = _clean_fragments(document.preferred_text)
    fallback = _clean_fragments(document.fallback_text)
    values = preferred if len(" ".join(preferred)) >= 20 else fallback
    return "\n".join(values)


def _clean_fragments(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        normalized = _collapse_space(value)
        if not normalized or any(pattern.search(normalized) for pattern in _NOISE_PATTERNS):
            continue
        if not cleaned or cleaned[-1] != normalized:
            cleaned.append(normalized)
    return cleaned


def _publication_date(document: _ResearchHtmlParser) -> date | None:
    candidates = [*document.date_candidates, *_json_ld_dates(document.json_ld_text)]
    for value in candidates:
        parsed = _parse_date(value)
        if parsed is not None:
            return parsed
    return None


def _json_ld_dates(documents: list[str]) -> list[str]:
    dates: list[str] = []
    for value in documents:
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            continue
        _collect_json_dates(payload, dates)
    return dates


def _collect_json_dates(value: Any, dates: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() == "datepublished" and isinstance(item, str):
                dates.append(item)
            else:
                _collect_json_dates(item, dates)
    elif isinstance(value, list):
        for item in value:
            _collect_json_dates(item, dates)


def _parse_date(value: str) -> date | None:
    normalized = value.strip().replace("年", "-").replace("月", "-").replace("日", "")
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()
    except ValueError:
        match = re.search(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", normalized)
        if match is None:
            return None
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            return None


def _collapse_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
