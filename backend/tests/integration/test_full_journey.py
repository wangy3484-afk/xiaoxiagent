"""Offline API-to-report acceptance journey with deterministic providers."""

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any, cast

import pytest
from api.support import api_test_context, register_and_login
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from ops_agent.domain.intake import BriefField, OperationsBrief
from ops_agent.persistence.job_state import JobStatus, ReportJobStateMachine
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
from ops_agent.report_runner import _load_job_context, _persist_result
from ops_agent.workflows.report_graph import (
    ReportWorkflowState,
    build_production_report_nodes,
    build_report_workflow_graph,
    initial_report_workflow_state,
)
from pydantic import HttpUrl
from workflows.test_acquisition_strategy import _model as acquisition_model
from workflows.test_action_plan import _model as action_model
from workflows.test_diagnosis import _model as diagnosis_model
from workflows.test_measurement_plan import _measurement_response
from workflows.test_professional_quality_review import _review_response
from workflows.test_report_assembly import _narrative_response
from workflows.test_resource_budget_risk_summary import _summary_response


class RecordingQueue:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    async def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


class OneHitSearch:
    def __init__(self, result: SearchResult) -> None:
        self.result = result
        self.calls: list[SearchRequest] = []

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.calls.append(request)
        return SearchResponse(
            query=request.query,
            results=(self.result,),
            provider="deterministic",
        )


def _confirmed_brief() -> OperationsBrief:
    def field(value: str) -> BriefField[str]:
        return BriefField[str].from_correction(value, value)

    return OperationsBrief(
        business_context=field("社区团购小程序"),
        current_problem=field("注册后首单转化低"),
        operation_goal=field("提升新客首单转化"),
        target_users=field("三四线城市新注册家庭用户"),
        business_stage=field("冷启动阶段"),
        execution_period=field("未来90天"),
        budget_and_resources=field("2名运营，预算上限5万元"),
        existing_channels=BriefField[list[str]].from_correction(
            ["社群", "小红书"], "社群、小红书"
        ),
        current_baseline=field("首单转化率8%"),
        preferred_benchmark_companies=BriefField[list[str]].from_correction(
            ["京东"], "京东"
        ),
    )


def _providers() -> tuple[ProviderSet, DeterministicModelProvider, OneHitSearch]:
    url = HttpUrl("https://example.com/official")
    content_hash = sha256("示例公司官方说明已上线新客首单任务。".encode()).hexdigest()
    source_id = f"src_{sha256(f'{url}|{content_hash}'.encode()).hexdigest()[:16]}"
    evidence_id = f"ev_{source_id}"
    narrative = _narrative_response()
    resource_summary = _summary_response()
    cast(list[dict[str, object]], resource_summary["risks"])[0][
        "monitoring_metric_ids"
    ] = ["metric_refund_complaint"]
    for claim in cast(list[dict[str, object]], narrative["supplemental_claims"]):
        if claim["claim_type"] == "inference":
            claim["evidence_ids"] = [evidence_id]
        if claim["claim_id"] == "hyp-1":
            claim["claim_id"] = "hyp-narrative"

    responses = {
        "parse_intake": {
            "operation_goal": {
                "value": "提升新客首单转化",
                "source_excerpt": "提升新客首单转化",
            },
        },
        "classify_scene": {
            "primary_scene": "acquisition",
            "rationale": ["核心目标是新客首单转化"],
            "confidence": 0.9,
        },
        "research_plan": {
            "topics": ["新客首单转化"],
            "similarity_dimensions": ["运营目标", "业务阶段"],
            "queries": [],
            "stop_conditions": ["达到预算时停止"],
        },
        "case_mechanism_extraction": {
            "claims": [
                {
                    "claim_id": "claim-1",
                    "text": "示例公司已上线新客首单任务",
                    "claim_type": "fact",
                    "source_ids": [source_id],
                    "supporting_quotes": ["已上线新客首单任务"],
                    "reasoning": "官方原文直接确认实施动作。",
                },
                {
                    "claim_id": "hyp-1",
                    "text": "社群机制可能改善首单转化",
                    "claim_type": "hypothesis",
                    "source_ids": [],
                    "supporting_quotes": [],
                    "reasoning": "需要在当前场景做实验验证。",
                },
            ],
            "cases": [
                {
                    "case_id": "case-official",
                    "company": "示例公司",
                    "goal": "提升新客首单转化",
                    "audience": "新注册家庭用户",
                    "touchpoints": ["活动页"],
                    "mechanism": "用首单任务降低决策门槛。",
                    "execution_conditions": ["具备任务配置能力"],
                    "outcome_claim_ids": ["claim-1"],
                    "evidence_source_ids": [source_id],
                    "transferable_elements": ["首单任务"],
                    "non_transferable_elements": ["头部自然流量"],
                }
            ],
        },
        "diagnose_operations": diagnosis_model()._responses["diagnose_operations"],
        "design_acquisition_strategy": acquisition_model()._responses[
            "design_acquisition_strategy"
        ],
        "build_action_plan": action_model()._responses["build_action_plan"],
        "build_measurement_plan": _measurement_response(),
        "build_resource_budget_risk_summary": resource_summary,
        "assemble_operations_report": narrative,
        "professional_quality_review": _review_response(),
    }
    model = DeterministicModelProvider(
        cast(Mapping[str, Mapping[str, Any]], responses)
    )
    search = OneHitSearch(
        SearchResult(
            title="示例公司官方首单任务",
            url=url,
            snippet="官方说明了新客首单任务。",
            rank=1,
        )
    )
    page = FetchedPage(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        body=b"<html><body>official case</body></html>",
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    providers = ProviderSet(
        model=model,
        search=search,
        fetcher=DeterministicPageFetcher({str(url): page}),
        extractor=DeterministicContentExtractor(
            {
                str(url): ExtractedContent(
                    canonical_url=url,
                    title="示例公司官方首单任务",
                    text="示例公司官方说明已上线新客首单任务。",
                    content_hash=content_hash,
                    publication_date=date(2026, 9, 1),
                    publisher="示例公司官方",
                )
            }
        ),
    )
    return providers, model, search


@pytest.mark.asyncio
async def test_offline_journey_from_login_to_report_and_both_exports() -> None:
    providers, model, search = _providers()
    queue = RecordingQueue()
    async with api_test_context(model_provider=model, job_queue=queue) as context:
        await register_and_login(context.client)
        parsed = await context.client.post(
            "/api/v1/briefs/parse",
            json={"scenario": "希望提升新客首单转化，业务是社区团购小程序"},
            headers={"Idempotency-Key": "full-journey-parse"},
        )
        assert parsed.status_code == 201, parsed.text
        assert parsed.json()["required_gaps"]
        brief_id = parsed.json()["id"]
        revised = await context.client.patch(
            f"/api/v1/briefs/{brief_id}",
            json={
                "expected_revision_number": 1,
                "brief": _confirmed_brief().model_dump(mode="json"),
                "classification": parsed.json()["classification"],
            },
        )
        assert revised.status_code == 200, revised.text
        confirmed = await context.client.post(
            f"/api/v1/briefs/{brief_id}/confirm",
            json={"expected_revision_number": 2},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["ready_for_research"] is True
        revision_id = confirmed.json()["revision_id"]
        created = await context.client.post(
            "/api/v1/jobs",
            json={"brief_id": brief_id, "brief_revision_id": revision_id},
            headers={"Idempotency-Key": "full-journey-job"},
        )
        assert created.status_code == 202, created.text
        job_id = created.json()["id"]
        assert queue.job_ids == [job_id]

        async with context.session_factory() as session:
            await ReportJobStateMachine(session).start(job_id)
            await session.commit()
        job_context = await _load_job_context(context.session_factory, job_id)
        graph = build_report_workflow_graph(
            build_production_report_nodes(providers, context.settings),
            checkpointer=InMemorySaver(),
        )
        config: RunnableConfig = {"configurable": {"thread_id": job_id}}
        result = cast(
            ReportWorkflowState,
            await graph.ainvoke(
                initial_report_workflow_state(
                    job_id=job_id,
                    brief=job_context.brief,
                    classification=job_context.classification,
                ),
                config,
            ),
        )
        assert result["completed_nodes"].count("research") >= 1
        assert result["completed_nodes"].count("strategy") >= 1
        assert result["completed_nodes"].count("quality") >= 2
        assert result["completed_nodes"][-1] == "finalize"
        assert search.calls
        assert Counter(call.purpose for call in model.calls)["professional_quality_review"] >= 2

        await _persist_result(context.session_factory, context.settings, job_context, result)
        async with context.session_factory() as session:
            await ReportJobStateMachine(session).transition(
                job_id, target_status=JobStatus.COMPLETED, stage="completed"
            )
            await session.commit()

        status = await context.client.get(f"/api/v1/jobs/{job_id}")
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "completed"
        report_id = status.json()["report_version_ids"][0]
        report = await context.client.get(f"/api/v1/reports/{report_id}")
        assert report.status_code == 200, report.text
        assert report.json()["version_number"] == 1
        assert report.json()["report_payload"]["evidence_appendix"]
        assert any(
            "改用示例公司" in note
            for note in report.json()["report_payload"]["limitations"]
        )
        for export_format in ("markdown", "pdf"):
            exported = await context.client.post(
                f"/api/v1/reports/{report_id}/exports",
                json={"format": export_format},
                headers={"Idempotency-Key": f"full-journey-{export_format}"},
            )
            assert exported.status_code == 201, exported.text
            downloaded = await context.client.get(exported.json()["download_url"])
            assert downloaded.status_code == 200
            assert downloaded.headers["x-checksum-sha256"] == sha256(
                downloaded.content
            ).hexdigest()
            assert downloaded.content
