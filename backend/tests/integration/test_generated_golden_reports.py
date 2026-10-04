"""Generate all twelve golden reports through the real graph with offline providers."""

import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from ops_agent.config import Settings
from ops_agent.domain.intake import (
    BriefField,
    FieldStatus,
    OperationsBrief,
    OperationsScene,
    SceneClassification,
)
from ops_agent.domain.report import OperationsReport
from ops_agent.domain.research import EvidenceCoverageResult
from ops_agent.evaluation import (
    GoldenScenario,
    evaluate_golden_batch,
    evaluate_golden_report,
    load_default_golden_scenarios,
)
from ops_agent.providers import (
    DeterministicContentExtractor,
    DeterministicModelProvider,
    DeterministicPageFetcher,
    ExtractedContent,
    FetchedPage,
    SearchResponse,
    SearchResult,
)
from ops_agent.providers.contracts import SearchRequest
from ops_agent.providers.wiring import ProviderSet
from ops_agent.workflows.report_graph import (
    ReportWorkflowState,
    build_production_report_nodes,
    build_report_workflow_graph,
    initial_report_workflow_state,
)
from pydantic import HttpUrl
from workflows.test_acquisition_strategy import _model as acquisition_model
from workflows.test_campaign_strategy import _model as campaign_model
from workflows.test_content_strategy import _model as content_model
from workflows.test_retention_strategy import _model as retention_model

from .test_full_journey import _providers as base_providers


class GoldenSearch:
    def __init__(self, results: tuple[SearchResult, ...]) -> None:
        self.results = results

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            results=self.results[request.offset : request.offset + request.max_results],
            provider="deterministic",
        )


def _brief(scenario: GoldenScenario) -> OperationsBrief:
    def field(value: str) -> BriefField[str]:
        return BriefField[str].from_correction(value, value)

    baseline = (
        field("用户确认已有可用的汇总业务基线，但具体数值未在匿名样例中披露")
        if scenario.baseline_status is FieldStatus.CONFIRMED
        else BriefField[str].unknown()
    )
    target_users = (
        BriefField[str].unknown()
        if scenario.scenario_id == "golden-campaign-03"
        else field("与该黄金场景相符的目标用户群")
    )
    return OperationsBrief(
        business_context=field(scenario.anonymized_context),
        current_problem=field(scenario.input_text),
        operation_goal=field(scenario.input_text),
        target_users=target_users,
        business_stage=field("匿名黄金场景验证阶段"),
        execution_period=field("按场景描述的周期执行"),
        budget_and_resources=field("；".join(scenario.known_constraints)),
        current_baseline=baseline,
        constraints=BriefField[list[str]].from_correction(
            scenario.known_constraints, "；".join(scenario.known_constraints)
        ),
    )


def _replace_strategy_id(value: Any, strategy_id: str) -> Any:
    if isinstance(value, str):
        return value.replace("strategy-community-first-order", strategy_id)
    if isinstance(value, list):
        return [_replace_strategy_id(item, strategy_id) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_strategy_id(item, strategy_id)
            for key, item in value.items()
        }
    return value


def _provider_fixture(scenario: GoldenScenario) -> ProviderSet:
    _base, base_model, _search = base_providers()
    responses = deepcopy(base_model._responses)
    strategy_by_scene = {
        OperationsScene.ACQUISITION: (
            "design_acquisition_strategy",
            acquisition_model,
            "strategy-community-first-order",
            "已上线新客首单任务",
        ),
        OperationsScene.RETENTION: (
            "design_retention_strategy",
            retention_model,
            "strategy-first-value-retention",
            "已上线新用户引导和留存提醒",
        ),
        OperationsScene.CAMPAIGN: (
            "design_campaign_strategy",
            campaign_model,
            "strategy-member-day",
            "已上线节日会员活动",
        ),
        OperationsScene.CONTENT: (
            "design_content_strategy",
            content_model,
            "strategy-content-diagnosis",
            "已上线专业知识内容栏目",
        ),
    }
    purpose, strategy_model, strategy_id, source_phrase = strategy_by_scene[
        scenario.scene
    ]
    responses[purpose] = strategy_model()._responses[purpose]
    for planning_purpose in (
        "build_action_plan",
        "build_measurement_plan",
        "build_resource_budget_risk_summary",
    ):
        responses[planning_purpose] = _replace_strategy_id(
            responses[planning_purpose], strategy_id
        )

    results: list[SearchResult] = []
    pages: dict[str, FetchedPage] = {}
    contents: dict[str, ExtractedContent] = {}
    source_ids: list[str] = []
    for number, (domain, publisher) in enumerate(
        (
            ("brand.example.com", "示例公司官方"),
            ("research.example.org", "独立研究机构"),
            ("association.example.net", "行业协会"),
        ),
        start=1,
    ):
        url = HttpUrl(f"https://{domain}/operations-case")
        text = f"{publisher}的公开页面确认：示例公司{source_phrase}。来源编号{number}。"
        content_hash = sha256(text.encode()).hexdigest()
        source_id = f"src_{sha256(f'{url}|{content_hash}'.encode()).hexdigest()[:16]}"
        source_ids.append(source_id)
        results.append(
            SearchResult(title=f"{publisher}运营案例", url=url, snippet=text, rank=number)
        )
        pages[str(url)] = FetchedPage(
            requested_url=url,
            final_url=url,
            status_code=200,
            content_type="text/html",
            body=b"<html><body>fixture</body></html>",
            fetched_at=datetime(2026, 10, 4, tzinfo=UTC),
        )
        contents[str(url)] = ExtractedContent(
            canonical_url=url,
            title=f"{publisher}运营案例",
            text=text,
            content_hash=content_hash,
            publication_date=date(2026, 9, 1),
            publisher=publisher,
        )

    extraction = cast(dict[str, Any], responses["case_mechanism_extraction"])
    extraction["claims"][0]["text"] = f"示例公司{source_phrase}"
    extraction["claims"][0]["source_ids"] = source_ids
    extraction["claims"][0]["supporting_quotes"] = [source_phrase]
    extraction["cases"][0]["goal"] = scenario.input_text
    extraction["cases"][0]["mechanism"] = source_phrase
    extraction["cases"][0]["evidence_source_ids"] = source_ids
    review = cast(dict[str, Any], responses["professional_quality_review"])
    if scenario.expected_blockers:
        review["passed"] = False
        review["findings"] = [
            {
                "finding_id": blocker.blocker_code,
                "dimension": "requirements_completeness",
                "issue_type": (
                    blocker.blocker_code
                    if blocker.blocker_code
                    in {"resource_conflict", "false_precision", "correlation_as_causation"}
                    else "other"
                ),
                "blocking": True,
                "rationale": blocker.rationale,
                "related_ids": [],
                "revision_target": blocker.revision_target.value,
                "remediation": "按黄金场景的已知约束缩小方案并补齐验证条件。",
            }
            for blocker in scenario.expected_blockers
        ]
        review["blocking_issue_ids"] = [
            blocker.blocker_code for blocker in scenario.expected_blockers
        ]
    else:
        review["passed"] = True
        review["findings"] = []
        review["blocking_issue_ids"] = []
        for dimension in review["dimensions"]:
            dimension["verdict"] = "pass"
    narrative = cast(dict[str, Any], responses["assemble_operations_report"])
    narrative["title"] = scenario.title
    narrative["executive_summary"] = (
        f"针对{scenario.title}，先按当前团队约束验证关键机制，"
        "再依据结果指标、过程指标和风险指标决定是否扩大。"
    )
    for claim in narrative["supplemental_claims"]:
        if claim["claim_type"] == "inference":
            claim["evidence_ids"] = [f"ev_{source_ids[0]}"]
    known_claim_ids = {
        claim["claim_id"] for claim in narrative["supplemental_claims"]
    } | {claim["claim_id"] for claim in extraction["claims"]}
    for strategy in responses[purpose]["strategy_options"]:
        for assumption_id in strategy["assumption_claim_ids"]:
            if assumption_id in known_claim_ids:
                continue
            narrative["supplemental_claims"].append(
                {
                    "claim_id": assumption_id,
                    "text": "该场景策略效果仍需在当前业务中验证",
                    "claim_type": "hypothesis",
                    "evidence_ids": [],
                    "reasoning": "公开案例只证明实施动作，不能替代当前场景实验。",
                    "verification_status": "unverified",
                }
            )
            known_claim_ids.add(assumption_id)
    model = DeterministicModelProvider(
        cast(Mapping[str, Mapping[str, Any]], responses)
    )
    return ProviderSet(
        model=model,
        search=GoldenSearch(tuple(results)),
        fetcher=DeterministicPageFetcher(pages),
        extractor=DeterministicContentExtractor(contents),
    )


async def _generate_scenario(
    scenario: GoldenScenario,
) -> tuple[OperationsReport, EvidenceCoverageResult, ReportWorkflowState]:
    providers = _provider_fixture(scenario)
    classification = SceneClassification(
        primary_scene=scenario.scene,
        rationale=["按照黄金场景定义的第一运营目标确定主场景"],
        confidence=0.9,
    )
    graph = build_report_workflow_graph(
        build_production_report_nodes(providers, Settings(environment="test")),
        checkpointer=InMemorySaver(),
    )
    config: RunnableConfig = {"configurable": {"thread_id": scenario.scenario_id}}
    result = cast(
        ReportWorkflowState,
        await graph.ainvoke(
            initial_report_workflow_state(
                job_id=scenario.scenario_id,
                brief=_brief(scenario),
                classification=classification,
            ),
            config,
        ),
    )
    report = OperationsReport.model_validate(result["finalized_report"])
    coverage = EvidenceCoverageResult.model_validate(result["evidence_coverage"])
    return report, coverage, result


@pytest.mark.asyncio
async def test_all_twelve_generated_golden_reports_pass_automatic_gates(
    tmp_path: Path,
) -> None:
    golden_set = load_default_golden_scenarios()
    for scenario in golden_set.scenarios:
        report, coverage, graph_state = await _generate_scenario(scenario)
        evaluation = evaluate_golden_report(scenario, report, coverage)
        assert evaluation.passed, (scenario.scenario_id, evaluation.failures)
        assert {"research", "diagnosis", "strategy", "planning", "assembly", "finalize"} <= set(
            graph_state["completed_nodes"]
        )
        observed_blockers = set(
            graph_state["professional_review"]["blocking_issue_ids"]
        )
        assert observed_blockers == {
            blocker.blocker_code for blocker in scenario.expected_blockers
        }
        expected_quality_runs = 3 if scenario.expected_blockers else 1
        assert graph_state["completed_nodes"].count("quality") == expected_quality_runs
        (tmp_path / f"{scenario.scenario_id}.json").write_text(
            json.dumps(
                {
                    "report": report.model_dump(mode="json"),
                    "coverage": coverage.model_dump(mode="json"),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    batch = evaluate_golden_batch(golden_set, tmp_path)
    assert batch.passed, batch
    assert len(batch.results) == 12
