"""Complete report graph routing and checkpoint-resume tests."""

from collections import Counter
from typing import cast

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from ops_agent.domain.quality import QualityRouteDecision, QualityRouteStatus, RevisionTarget
from ops_agent.workflows.report_graph import (
    ReportWorkflowNodes,
    ReportWorkflowState,
    StageHandler,
    build_report_workflow_graph,
)


class ForcedWorkerStop(RuntimeError):
    pass


def _initial() -> ReportWorkflowState:
    return {
        "job_id": "job-graph-1",
        "brief": {},
        "classification": {},
        "completed_nodes": [],
        "revision_round": 0,
    }


def _nodes(
    *,
    calls: Counter[str],
    crash_once_at: str | None = None,
    revise_strategy_once: bool = False,
) -> ReportWorkflowNodes:
    crashed = False
    quality_round = 0

    def handler(name: str) -> StageHandler:
        async def run(state: ReportWorkflowState) -> dict[str, object]:
            nonlocal crashed, quality_round
            calls[name] += 1
            if crash_once_at == name and not crashed:
                crashed = True
                raise ForcedWorkerStop(name)
            updates: dict[str, object] = {
                "completed_nodes": [*state["completed_nodes"], name]
            }
            if name == "quality":
                quality_round += 1
                if revise_strategy_once and quality_round == 1:
                    decision = QualityRouteDecision(
                        status=QualityRouteStatus.REVISE,
                        revision_round=1,
                        targets=[RevisionTarget.STRATEGY],
                        issue_ids=["quality-1"],
                        rationale="策略需要一次定向修订。",
                    )
                else:
                    decision = QualityRouteDecision(
                        status=QualityRouteStatus.PASSED,
                        revision_round=quality_round - 1,
                        rationale="质量门槛已通过。",
                    )
                updates["route_decision"] = decision.model_dump(mode="json")
            return updates

        return run

    return ReportWorkflowNodes(
        load_context=handler("load_context"),
        research=handler("research"),
        diagnosis=handler("diagnosis"),
        strategy=handler("strategy"),
        planning=handler("planning"),
        assembly=handler("assembly"),
        quality=handler("quality"),
        finalize=handler("finalize"),
    )


@pytest.mark.asyncio
async def test_complete_graph_runs_all_stages_and_targeted_revision() -> None:
    calls: Counter[str] = Counter()
    graph = build_report_workflow_graph(
        _nodes(calls=calls, revise_strategy_once=True),
        checkpointer=InMemorySaver(),
    )
    config: RunnableConfig = {"configurable": {"thread_id": "graph-revision"}}

    result = await graph.ainvoke(_initial(), config)

    assert result["completed_nodes"] == [
        "load_context",
        "research",
        "diagnosis",
        "strategy",
        "planning",
        "assembly",
        "quality",
        "strategy",
        "planning",
        "assembly",
        "quality",
        "finalize",
    ]
    assert calls["research"] == 1
    assert calls["strategy"] == 2
    assert calls["quality"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("crash_node", ["research", "quality"])
async def test_checkpoint_resume_does_not_repeat_completed_nodes(crash_node: str) -> None:
    calls: Counter[str] = Counter()
    saver = InMemorySaver()
    graph = build_report_workflow_graph(
        _nodes(calls=calls, crash_once_at=crash_node),
        checkpointer=saver,
    )
    config: RunnableConfig = {
        "configurable": {"thread_id": f"graph-crash-{crash_node}"}
    }

    with pytest.raises(ForcedWorkerStop, match=crash_node):
        await graph.ainvoke(_initial(), config)

    result = cast(ReportWorkflowState, await graph.ainvoke(None, config))

    assert result["completed_nodes"] == [
        "load_context",
        "research",
        "diagnosis",
        "strategy",
        "planning",
        "assembly",
        "quality",
        "finalize",
    ]
    completed_before_crash = {
        "research": ["load_context"],
        "quality": [
            "load_context",
            "research",
            "diagnosis",
            "strategy",
            "planning",
            "assembly",
        ],
    }[crash_node]
    for node in completed_before_crash:
        assert calls[node] == 1
    assert calls[crash_node] == 2
