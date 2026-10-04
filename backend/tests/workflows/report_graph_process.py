"""Subprocess probe for complete report-graph PostgreSQL recovery."""

import asyncio
import json
import os
import sys
from typing import cast

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langchain_core.runnables import RunnableConfig  # noqa: E402
from ops_agent.domain.quality import (  # noqa: E402
    QualityRouteDecision,
    QualityRouteStatus,
)
from ops_agent.persistence.checkpoints import open_postgres_checkpointer  # noqa: E402
from ops_agent.workflows.report_graph import (  # noqa: E402
    ReportWorkflowNodes,
    ReportWorkflowState,
    StageHandler,
    build_report_workflow_graph,
)


def build_nodes(phase: str, crash_node: str) -> ReportWorkflowNodes:
    def handler(name: str) -> StageHandler:
        async def run(state: ReportWorkflowState) -> dict[str, object]:
            if phase == "crash" and name == crash_node:
                os._exit(23)
            counts = dict(state.get("node_counts", {}))
            counts[name] = counts.get(name, 0) + 1
            updates: dict[str, object] = {
                "completed_nodes": [*state["completed_nodes"], name],
                "node_counts": counts,
            }
            if name == "quality":
                updates["route_decision"] = QualityRouteDecision(
                    status=QualityRouteStatus.PASSED,
                    revision_round=0,
                    rationale="恢复探针质量检查通过。",
                ).model_dump(mode="json")
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


def initial_state(thread_id: str) -> ReportWorkflowState:
    return {
        "job_id": thread_id,
        "brief": {},
        "classification": {},
        "completed_nodes": [],
        "revision_round": 0,
        "node_counts": {},
    }


async def run(phase: str, crash_node: str, thread_id: str, schema: str) -> None:
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    async with open_postgres_checkpointer(
        os.environ["OPS_AGENT_TEST_CHECKPOINT_URL"],
        schema=schema,
        setup=True,
    ) as checkpointer:
        graph = build_report_workflow_graph(
            build_nodes(phase, crash_node),
            checkpointer=checkpointer,
        )
        if phase == "crash":
            await graph.ainvoke(initial_state(thread_id), config)
            raise AssertionError("crash phase unexpectedly completed")
        snapshot = await graph.aget_state(config)
        graph_input = None if snapshot.values else initial_state(thread_id)
        result = cast(ReportWorkflowState, await graph.ainvoke(graph_input, config))
        print(
            json.dumps(
                {
                    "completed_nodes": result["completed_nodes"],
                    "node_counts": result["node_counts"],
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    coroutine = run(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    if sys.platform == "win32":
        asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(coroutine)
