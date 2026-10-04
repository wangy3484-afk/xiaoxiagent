"""Subprocess probe used to prove checkpoint recovery across process restarts."""

import asyncio
import json
import os
import sys
from typing import Any, TypedDict, cast

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langchain_core.runnables import RunnableConfig  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Command, interrupt  # noqa: E402
from ops_agent.persistence.checkpoints import open_postgres_checkpointer  # noqa: E402


class RecoveryState(TypedDict):
    prepare_count: int
    decision: str
    completed: bool


def prepare(state: RecoveryState) -> RecoveryState:
    return {
        "prepare_count": state["prepare_count"] + 1,
        "decision": state["decision"],
        "completed": state["completed"],
    }


def approval_gate(state: RecoveryState) -> RecoveryState:
    decision = cast(str, interrupt({"question": "approve deterministic probe"}))
    return {
        "prepare_count": state["prepare_count"],
        "decision": decision,
        "completed": state["completed"],
    }


def finalize(state: RecoveryState) -> RecoveryState:
    return {
        "prepare_count": state["prepare_count"],
        "decision": state["decision"],
        "completed": True,
    }


def build_graph(checkpointer: Any) -> Any:
    builder = StateGraph(RecoveryState)
    builder.add_node("prepare", prepare)
    builder.add_node("approval_gate", approval_gate)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "approval_gate")
    builder.add_edge("approval_gate", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)


async def run(phase: str, thread_id: str, schema: str) -> dict[str, object]:
    database_url = os.environ["OPS_AGENT_TEST_CHECKPOINT_URL"]
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    async with open_postgres_checkpointer(
        database_url,
        schema=schema,
        setup=True,
    ) as checkpointer:
        graph = build_graph(checkpointer)
        if phase == "start":
            result = await graph.ainvoke(
                {"prepare_count": 0, "decision": "", "completed": False},
                config,
            )
            return {
                "interrupted": bool(result.get("__interrupt__")),
                "prepare_count": result["prepare_count"],
                "completed": result["completed"],
            }
        if phase == "resume":
            result = await graph.ainvoke(Command(resume="approved"), config)
            return {
                "prepare_count": result["prepare_count"],
                "decision": result["decision"],
                "completed": result["completed"],
            }
        raise ValueError(f"unknown phase: {phase}")


if __name__ == "__main__":
    coroutine = run(sys.argv[1], sys.argv[2], sys.argv[3])
    if sys.platform == "win32":
        process_result = asyncio.run(
            coroutine,
            loop_factory=asyncio.SelectorEventLoop,
        )
    else:
        process_result = asyncio.run(coroutine)
    print(json.dumps(process_result))
