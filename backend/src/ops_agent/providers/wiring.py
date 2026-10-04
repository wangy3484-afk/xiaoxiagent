"""Provider dependency container and production composition root."""

from dataclasses import dataclass

from ops_agent.config import Settings
from ops_agent.providers.contracts import (
    ContentExtractor,
    ModelProvider,
    PageFetcher,
    SearchProvider,
)
from ops_agent.providers.html_extractor import HtmlContentExtractor
from ops_agent.providers.http_fetcher import SecureHttpPageFetcher
from ops_agent.providers.openai_compatible import OpenAICompatibleModelProvider
from ops_agent.providers.tavily import TavilySearchProvider


@dataclass(frozen=True, slots=True)
class ProviderSet:
    """The only external-service dependencies workflow nodes should receive."""

    model: ModelProvider
    search: SearchProvider
    fetcher: PageFetcher
    extractor: ContentExtractor


def build_production_providers(settings: Settings) -> ProviderSet:
    """Build configured production adapters without exposing them to workflow code."""
    if settings.model_api_key is None:
        raise ValueError("OPS_AGENT_MODEL_API_KEY is required to build model provider")
    if settings.search_api_key is None:
        raise ValueError("OPS_AGENT_SEARCH_API_KEY is required to build search provider")
    return ProviderSet(
        model=OpenAICompatibleModelProvider(
            base_url=str(settings.model_base_url),
            api_key=settings.model_api_key,
            model=settings.model_name,
            timeout_seconds=settings.model_timeout_seconds,
            schema_retries=settings.model_max_retries,
        ),
        search=TavilySearchProvider(
            base_url=str(settings.search_base_url),
            api_key=settings.search_api_key,
            timeout_seconds=settings.search_timeout_seconds,
        ),
        fetcher=SecureHttpPageFetcher(
            timeout_seconds=settings.fetch_timeout_seconds,
            max_bytes=settings.fetch_max_bytes,
            max_redirects=settings.fetch_max_redirects,
        ),
        extractor=HtmlContentExtractor(),
    )
