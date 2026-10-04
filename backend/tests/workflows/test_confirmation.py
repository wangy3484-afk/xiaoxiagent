"""Interrupt/resume tests for immutable brief confirmation baselines."""

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from ops_agent.domain.intake import (
    BriefField,
    OperationsBrief,
    OperationsScene,
    SceneClassification,
)
from ops_agent.workflows.confirmation import build_brief_confirmation_graph


def _brief(goal: str) -> OperationsBrief:
    return OperationsBrief(
        operation_goal=BriefField[str].from_user(goal, goal),
        target_users=BriefField[str].from_user("新注册用户", "新注册用户"),
    )


def _classification() -> SceneClassification:
    return SceneClassification(
        primary_scene=OperationsScene.RETENTION,
        rationale=["核心目标是留存"],
        confidence=0.9,
    )


@pytest.mark.asyncio
async def test_modified_brief_is_used_after_interrupt_resume_and_frozen() -> None:
    graph = build_brief_confirmation_graph()
    config: RunnableConfig = {"configurable": {"thread_id": "brief-confirmation-1"}}
    initial = await graph.ainvoke(
        {
            "brief": _brief("提升次月留存"),
            "classification": _classification(),
            "confirmed_baseline": None,
            "research_started": False,
        },
        config,
    )
    assert initial.get("__interrupt__")
    assert initial["research_started"] is False

    modified_brief = _brief("提升完成关键行为的新用户次月留存")
    modified = await graph.ainvoke(
        Command(
            resume={
                "action": "modify",
                "brief": modified_brief.model_dump(mode="json"),
            }
        ),
        config,
    )
    assert modified.get("__interrupt__")
    assert modified["research_started"] is False

    confirmed = await graph.ainvoke(Command(resume={"action": "confirm"}), config)

    baseline = confirmed["confirmed_baseline"]
    assert baseline.brief.operation_goal.value == modified_brief.operation_goal.value
    assert confirmed["brief"].operation_goal.value == modified_brief.operation_goal.value
    assert confirmed["research_started"] is True
    assert len(baseline.fingerprint_sha256) == 64


@pytest.mark.asyncio
async def test_confirmation_without_changes_freezes_original_version() -> None:
    graph = build_brief_confirmation_graph()
    config: RunnableConfig = {"configurable": {"thread_id": "brief-confirmation-2"}}
    original = _brief("提升次月留存")
    await graph.ainvoke(
        {
            "brief": original,
            "classification": _classification(),
            "confirmed_baseline": None,
            "research_started": False,
        },
        config,
    )

    result = await graph.ainvoke(Command(resume={"action": "confirm"}), config)

    assert result["confirmed_baseline"].brief == original
    assert result["research_started"] is True
