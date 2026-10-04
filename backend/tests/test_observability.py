"""Structured correlation, metrics, and redaction tests."""

import json
import logging
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from ops_agent.config import Settings
from ops_agent.observability import (
    RunMetrics,
    bind_observability_context,
    log_event,
    observe_provider_set,
)
from ops_agent.providers.contracts import (
    ExtractedContent,
    FetchedPage,
    ModelMessage,
    ModelRequest,
    ModelUsage,
    SearchRequest,
    SearchResult,
    StructuredModelResult,
)
from ops_agent.providers.fakes import (
    DeterministicContentExtractor,
    DeterministicPageFetcher,
    DeterministicSearchProvider,
)
from ops_agent.providers.wiring import ProviderSet
from ops_agent.workflows.report_graph import (
    ReportWorkflowNodes,
    ReportWorkflowState,
    instrument_report_nodes,
)
from pydantic import BaseModel, HttpUrl


class ExampleOutput(BaseModel):
    result: str


class UsageModelProvider:
    async def generate_structured[OutputT: BaseModel](
        self,
        request: ModelRequest,
        output_schema: type[OutputT],
    ) -> StructuredModelResult[OutputT]:
        return StructuredModelResult(
            output=output_schema.model_validate({"result": "ok"}),
            provider="test-model",
            model="test-model-v1",
            request_id="provider-request-1",
            usage=ModelUsage(input_tokens=100, output_tokens=50),
        )


@pytest.mark.asyncio
async def test_provider_and_node_logs_are_correlated_metered_and_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "TOP-SECRET-INPUT-AND-WEBPAGE"
    url = HttpUrl("https://example.com/case?private=value")
    page = FetchedPage(
        requested_url=url,
        final_url=url,
        status_code=200,
        content_type="text/html",
        body=f"<p>{secret}</p>".encode(),
        fetched_at=datetime(2026, 10, 3, tzinfo=UTC),
    )
    extracted = ExtractedContent(
        canonical_url=url,
        title="案例",
        text=secret,
        content_hash="a" * 64,
    )
    search = DeterministicSearchProvider(
        {
            secret: (
                SearchResult(title="案例", url=url, snippet=secret, rank=1),
            )
        }
    )
    metrics = RunMetrics()
    settings = Settings.model_validate(
        {
            "environment": "test",
            "model_input_cost_per_million_tokens": 2.0,
            "model_output_cost_per_million_tokens": 10.0,
        }
    )
    providers = observe_provider_set(
        ProviderSet(
            model=UsageModelProvider(),
            search=search,
            fetcher=DeterministicPageFetcher({str(url): page}),
            extractor=DeterministicContentExtractor({str(url): extracted}),
        ),
        metrics,
        settings,
    )

    async def stage(state: ReportWorkflowState) -> dict[str, object]:
        return {"completed_nodes": [*state["completed_nodes"], "research"]}

    nodes = instrument_report_nodes(
        ReportWorkflowNodes(
            load_context=stage,
            research=stage,
            diagnosis=stage,
            strategy=stage,
            planning=stage,
            assembly=stage,
            quality=stage,
            finalize=stage,
        )
    )
    state: ReportWorkflowState = {
        "job_id": "job-123",
        "brief": {"private_input": secret},
        "classification": {},
        "completed_nodes": [],
        "revision_round": 0,
    }

    with caplog.at_level(logging.INFO, logger="ops_agent.observability"):
        with bind_observability_context(
            request_id="request-123",
            job_id="job-123",
            thread_id="job-123",
        ):
            await providers.model.generate_structured(
                ModelRequest(
                    purpose="test_generation",
                    messages=(ModelMessage(role="user", content=secret),),
                ),
                ExampleOutput,
            )
            await providers.search.search(SearchRequest(query=secret, max_results=1))
            fetched = await providers.fetcher.fetch(url)
            await providers.extractor.extract(fetched)
            await cast(Any, nodes.research)(state)
            log_event(
                "report_job_run_finished",
                metrics=metrics.summary(),
                api_key=secret,
                webpage_body=secret,
            )

    payloads: list[dict[str, Any]] = [json.loads(record.message) for record in caplog.records]
    assert payloads
    assert all(payload["request_id"] == "request-123" for payload in payloads)
    assert all(payload["job_id"] == "job-123" for payload in payloads)
    assert all(payload["thread_id"] == "job-123" for payload in payloads)
    assert metrics.model_calls == 1
    assert metrics.input_tokens == 100
    assert metrics.output_tokens == 50
    assert metrics.search_calls == metrics.search_results == 1
    assert metrics.fetch_attempts == metrics.fetch_successes == 1
    assert metrics.estimated_cost == pytest.approx(0.0007)
    model_log = next(
        payload for payload in payloads if payload["event"] == "model_call_completed"
    )
    assert model_log["input_tokens"] == 100
    assert model_log["output_tokens"] == 50
    assert any(payload["event"] == "graph_node_completed" for payload in payloads)
    combined_logs = "\n".join(record.message for record in caplog.records)
    assert secret not in combined_logs
    assert "private=value" not in combined_logs
    assert '"api_key": "[REDACTED]"' in combined_logs
    assert '"webpage_body": "[REDACTED]"' in combined_logs
