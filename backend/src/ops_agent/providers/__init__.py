"""Provider contracts and adapters for models, search, fetch, and extraction."""

from ops_agent.providers.contracts import (
    ContentExtractor,
    ExtractedContent,
    FetchedPage,
    ModelMessage,
    ModelProvider,
    ModelRequest,
    ModelUsage,
    PageFetcher,
    SearchProvider,
    SearchRequest,
    SearchResponse,
    SearchResult,
    StructuredModelResult,
)
from ops_agent.providers.fakes import (
    DeterministicContentExtractor,
    DeterministicModelProvider,
    DeterministicPageFetcher,
    DeterministicSearchProvider,
)
from ops_agent.providers.html_extractor import HtmlContentExtractor
from ops_agent.providers.http_fetcher import SecureHttpPageFetcher
from ops_agent.providers.openai_compatible import OpenAICompatibleModelProvider
from ops_agent.providers.tavily import TavilySearchProvider
from ops_agent.providers.wiring import ProviderSet, build_production_providers

__all__ = [
    "ContentExtractor",
    "DeterministicContentExtractor",
    "DeterministicModelProvider",
    "DeterministicPageFetcher",
    "DeterministicSearchProvider",
    "ExtractedContent",
    "FetchedPage",
    "HtmlContentExtractor",
    "ModelMessage",
    "ModelProvider",
    "ModelRequest",
    "ModelUsage",
    "OpenAICompatibleModelProvider",
    "PageFetcher",
    "ProviderSet",
    "SearchProvider",
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    "SecureHttpPageFetcher",
    "StructuredModelResult",
    "TavilySearchProvider",
    "build_production_providers",
]
