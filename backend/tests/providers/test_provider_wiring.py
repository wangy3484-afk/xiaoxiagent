"""Provider replacement stays outside workflow/business functions."""

import pytest
from ops_agent.config import Settings
from ops_agent.providers import (
    DeterministicContentExtractor,
    DeterministicModelProvider,
    DeterministicPageFetcher,
    DeterministicSearchProvider,
    ProviderSet,
    SearchRequest,
    SearchResult,
    build_production_providers,
)
from pydantic import HttpUrl, SecretStr


async def _business_research_step(providers: ProviderSet, query: str) -> tuple[str, ...]:
    response = await providers.search.search(SearchRequest(query=query, max_results=2))
    return tuple(item.title for item in response.results)


@pytest.mark.asyncio
async def test_workflow_dependency_can_be_replaced_with_offline_fakes() -> None:
    providers = ProviderSet(
        model=DeterministicModelProvider({}),
        search=DeterministicSearchProvider(
            {
                "留存案例": (
                    SearchResult(
                        title="公开案例",
                        url=HttpUrl("https://example.com/case"),
                        rank=1,
                    ),
                )
            }
        ),
        fetcher=DeterministicPageFetcher({}),
        extractor=DeterministicContentExtractor({}),
    )

    assert await _business_research_step(providers, "留存案例") == ("公开案例",)


def test_production_composition_uses_configured_adapters() -> None:
    settings = Settings(
        model_api_key=SecretStr("model-test-key"),
        search_api_key=SecretStr("search-test-key"),
    )

    providers = build_production_providers(settings)

    assert type(providers.model).__name__ == "OpenAICompatibleModelProvider"
    assert type(providers.search).__name__ == "TavilySearchProvider"
    assert type(providers.fetcher).__name__ == "SecureHttpPageFetcher"


def test_production_composition_requires_external_credentials() -> None:
    with pytest.raises(ValueError, match="MODEL_API_KEY"):
        build_production_providers(Settings())
