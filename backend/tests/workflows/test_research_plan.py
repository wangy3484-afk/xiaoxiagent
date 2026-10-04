"""Research-plan workflow tests."""

from datetime import UTC, date, datetime

import pytest
from ops_agent.config import Settings
from ops_agent.domain.intake import (
    BriefField,
    OperationsBrief,
    OperationsScene,
    SceneClassification,
)
from ops_agent.domain.research import (
    ResearchBudget,
    ResearchPlan,
    ResearchQuery,
    ResearchQueryKind,
)
from ops_agent.providers import (
    DeterministicContentExtractor,
    DeterministicModelProvider,
    DeterministicPageFetcher,
    DeterministicSearchProvider,
    ExtractedContent,
    FetchedPage,
    SearchResult,
)
from ops_agent.workflows.confirmation import ConfirmedBriefBaseline
from ops_agent.workflows.research import (
    ResearchCollectionStage,
    build_research_plan,
    explain_named_company_substitutions,
    research_plan,
    run_research_collection,
)
from pydantic import HttpUrl

from .test_case_mechanism_migration import _case_mechanism


def _brief(*, benchmark_companies: list[str]) -> OperationsBrief:
    return OperationsBrief(
        business_context=BriefField[str].from_user(
            "社区团购小程序", "社区团购小程序"
        ),
        current_problem=BriefField[str].from_user(
            "注册后首单转化低", "注册后首单转化低"
        ),
        operation_goal=BriefField[str].from_user(
            "提升新客首单转化", "提升新客首单转化"
        ),
        target_users=BriefField[str].from_user(
            "三四线城市新注册用户", "三四线城市新注册用户"
        ),
        business_stage=BriefField[str].from_user("冷启动阶段", "冷启动阶段"),
        existing_channels=BriefField[list[str]].from_user(
            ["社群", "小红书"], "社群、小红书"
        ),
        preferred_benchmark_companies=BriefField[list[str]].from_user(
            benchmark_companies, "、".join(benchmark_companies)
        ),
    )


def _classification() -> SceneClassification:
    return SceneClassification(
        primary_scene=OperationsScene.ACQUISITION,
        secondary_scenes=[OperationsScene.CONTENT],
        rationale=["核心目标是提升新客首单转化，内容渠道是辅助触达手段"],
        confidence=0.9,
    )


def _settings(max_queries: int = 5) -> Settings:
    return Settings(
        environment="test",
        report_max_search_queries=max_queries,
        report_max_sources_per_query=3,
        report_max_evidence_items=12,
        report_timeout_seconds=120,
    )


@pytest.mark.asyncio
async def test_research_plan_covers_named_companies_and_structural_cases() -> None:
    model = DeterministicModelProvider(
        {
            "research_plan": {
                "topics": ["新客首单转化机制"],
                "similarity_dimensions": ["运营目标", "业务阶段", "渠道条件"],
                "queries": [
                    {
                        "query_id": "model_mechanism",
                        "query": "新客 首单 转化 激励 机制 案例",
                        "purpose": "补充首单激励机制案例",
                        "kind": "mechanism",
                        "expected_evidence": ["机制说明", "效果上下文"],
                        "max_results": 8,
                    }
                ],
                "stop_conditions": ["模型认为已覆盖主要机制时停止"],
            }
        }
    )

    plan = await build_research_plan(
        _brief(benchmark_companies=["淘宝", "京东"]),
        _classification(),
        model,
        settings=_settings(),
    )

    named_targets = {
        query.target_company
        for query in plan.queries
        if query.kind is ResearchQueryKind.NAMED_COMPANY
    }
    structural_queries = [
        query for query in plan.queries if query.kind is ResearchQueryKind.STRUCTURALLY_SIMILAR
    ]

    assert named_targets == {"淘宝", "京东"}
    assert structural_queries
    assert any(
        token in structural_queries[0].query
        for token in ("提升新客首单转化", "冷启动阶段", "社群", "小红书")
    )
    assert len(plan.queries) <= plan.budget.max_queries == 5
    assert all(query.max_results <= 3 for query in plan.queries)
    assert "达到查询数、页面数或总耗时预算时立即停止" in plan.stop_conditions


def test_unverified_named_company_is_replaced_with_explained_verified_case() -> None:
    plan = ResearchPlan(
        topics=["新客首单转化"],
        named_companies=["京东"],
        similarity_dimensions=["运营目标", "业务阶段"],
        queries=[
            ResearchQuery(
                query_id="named-jd",
                query="京东 新客首单 转化 案例",
                purpose="核验京东相关公开案例",
                kind=ResearchQueryKind.NAMED_COMPANY,
                target_company="京东",
                expected_evidence=["官方原文"],
            ),
            ResearchQuery(
                query_id="similar",
                query="区域生鲜 新客首单 转化 案例",
                purpose="寻找结构相似且可核验案例",
                kind=ResearchQueryKind.STRUCTURALLY_SIMILAR,
                expected_evidence=["结构相似案例"],
            ),
        ],
        stop_conditions=["达到预算停止"],
        budget=ResearchBudget(max_queries=2, max_pages=4, max_seconds=60),
    )
    verified_alternative = _case_mechanism().model_copy(
        update={"company": "区域同业"}
    )

    note = explain_named_company_substitutions(plan, [verified_alternative])

    assert len(note) == 1
    assert "京东" in note[0]
    assert "改用区域同业" in note[0]
    assert "替换原因" in note[0]
    assert explain_named_company_substitutions(
        plan, [_case_mechanism().model_copy(update={"company": "京东"})]
    ) == []
    assert "未取得可替代" in explain_named_company_substitutions(plan, [])[0]


@pytest.mark.asyncio
async def test_research_plan_node_uses_confirmed_baseline() -> None:
    model = DeterministicModelProvider(
        {
            "research_plan": {
                "topics": [],
                "similarity_dimensions": [],
                "queries": [],
                "stop_conditions": [],
            }
        }
    )
    baseline = ConfirmedBriefBaseline(
        brief=_brief(benchmark_companies=["淘宝"]),
        classification=_classification(),
        fingerprint_sha256="b" * 64,
    )

    result = await research_plan(
        {"confirmed_baseline": baseline, "research_plan": None},
        model,
        settings=_settings(max_queries=3),
    )

    assert result["confirmed_baseline"] == baseline
    assert result["research_plan"] is not None
    assert {
        query.kind for query in result["research_plan"].queries
    } >= {
        ResearchQueryKind.NAMED_COMPANY,
        ResearchQueryKind.STRUCTURALLY_SIMILAR,
    }


@pytest.mark.asyncio
async def test_research_plan_rejects_budget_too_small_for_named_coverage() -> None:
    model = DeterministicModelProvider(
        {
            "research_plan": {
                "topics": [],
                "similarity_dimensions": [],
                "queries": [],
                "stop_conditions": [],
            }
        }
    )

    with pytest.raises(ValueError, match="budget is too small"):
        await build_research_plan(
            _brief(benchmark_companies=["淘宝", "京东"]),
            _classification(),
            model,
            settings=_settings(max_queries=2),
        )


@pytest.mark.asyncio
async def test_research_collection_enforces_budgets_and_keeps_valid_pages() -> None:
    url_valid = HttpUrl("https://example.com/valid")
    url_missing = HttpUrl("https://example.com/missing")
    url_duplicate = HttpUrl("https://example.com/duplicate")
    url_large = HttpUrl("https://example.com/large")
    url_extra = HttpUrl("https://example.com/extra")
    plan = ResearchPlan(
        topics=["新客首单转化"],
        named_companies=["淘宝"],
        similarity_dimensions=["运营目标", "业务阶段", "渠道条件"],
        queries=[
            ResearchQuery(
                query_id="q_named_1",
                query="淘宝 新客首单转化 运营 案例",
                purpose="核验点名企业案例",
                kind=ResearchQueryKind.NAMED_COMPANY,
                target_company="淘宝",
                expected_evidence=["官方材料"],
                max_results=2,
            ),
            ResearchQuery(
                query_id="q_structural_1",
                query="社区团购 冷启动 新客首单转化 相似案例",
                purpose="寻找结构相似案例",
                kind=ResearchQueryKind.STRUCTURALLY_SIMILAR,
                expected_evidence=["相似阶段案例"],
                max_results=3,
            ),
        ],
        stop_conditions=["达到预算停止"],
        budget=ResearchBudget(max_queries=2, max_pages=4, max_seconds=60),
    )
    search = DeterministicSearchProvider(
        {
            "淘宝 新客首单转化 运营 案例": (
                SearchResult(title="有效案例", url=url_valid, rank=1),
                SearchResult(title="抓取失败案例", url=url_missing, rank=2),
            ),
            "社区团购 冷启动 新客首单转化 相似案例": (
                SearchResult(title="重复案例", url=url_duplicate, rank=1),
                SearchResult(title="超大页面", url=url_large, rank=2),
                SearchResult(title="预算外页面", url=url_extra, rank=3),
            ),
        }
    )
    page_valid = FetchedPage(
        requested_url=url_valid,
        final_url=url_valid,
        status_code=200,
        content_type="text/html",
        body=b"<html>valid</html>",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    page_duplicate = FetchedPage(
        requested_url=url_duplicate,
        final_url=url_valid,
        status_code=200,
        content_type="text/html",
        body=b"<html>duplicate</html>",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    page_large = FetchedPage(
        requested_url=url_large,
        final_url=url_large,
        status_code=200,
        content_type="text/html",
        body=b"x" * 10_001,
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    fetcher = DeterministicPageFetcher(
        {
            str(url_valid): page_valid,
            str(url_duplicate): page_duplicate,
            str(url_large): page_large,
        }
    )
    extractor = DeterministicContentExtractor(
        {
            str(url_valid): ExtractedContent(
                canonical_url=url_valid,
                title="有效案例正文",
                text="企业公开说明了新客首单转化机制。",
                content_hash="c" * 64,
                publication_date=date(2026, 9, 1),
                publisher="示例来源",
            )
        }
    )

    result = await run_research_collection(
        plan,
        search,
        fetcher,
        extractor,
        settings=Settings(
            environment="test",
            report_max_sources_per_query=3,
            fetch_max_bytes=10_000,
            fetch_concurrency=4,
        ),
    )

    failure_stages = {failure.stage for failure in result.failures}
    fetched_urls = {str(url) for url in fetcher.calls}

    assert [source.canonical_url for source in result.sources] == [url_valid]
    assert result.attempted_queries == 2
    assert result.attempted_pages == 4
    assert result.deduplicated_pages == 1
    assert str(url_extra) not in fetched_urls
    assert {
        ResearchCollectionStage.FETCH,
        ResearchCollectionStage.RESPONSE_SIZE,
        ResearchCollectionStage.DEDUPLICATE,
    } <= failure_stages
