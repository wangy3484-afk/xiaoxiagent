"""Clarification priority and LangGraph research-gate tests."""

import pytest
from ops_agent.domain.intake import (
    BriefField,
    FieldStatus,
    OperationsBrief,
    OperationsScene,
    SceneClassification,
)
from ops_agent.playbooks.loader import load_default_registry
from ops_agent.workflows.classification import check_completeness
from ops_agent.workflows.questions import (
    build_intake_gate_graph,
    prioritize_clarifying_questions,
)


def _classification() -> SceneClassification:
    return SceneClassification(
        primary_scene=OperationsScene.RETENTION,
        rationale=["目标是提升留存"],
        confidence=0.9,
    )


def _incomplete_brief() -> OperationsBrief:
    return OperationsBrief(
        operation_goal=BriefField[str].from_user("提升次月留存", "提升次月留存"),
        target_users=BriefField[str].from_user("新注册用户", "新注册用户"),
    )


def test_questions_put_blocking_scene_specific_gaps_first() -> None:
    completeness = check_completeness(
        _incomplete_brief(), _classification(), load_default_registry()
    )

    questions = prioritize_clarifying_questions(completeness)

    required_fields = {gap.field for gap in completeness.required_gaps}
    first_recommended_index = next(
        (
            index
            for index, question in enumerate(questions)
            if question.field not in required_fields
        ),
        len(questions),
    )
    assert all(
        question.field in required_fields
        for question in questions[:first_recommended_index]
    )
    assert any(question.id == "retention_definition" for question in questions)
    assert any(question.field == "execution_period" for question in questions)


@pytest.mark.asyncio
async def test_graph_interrupts_before_research_when_required_fields_are_missing() -> None:
    completeness = check_completeness(
        _incomplete_brief(), _classification(), load_default_registry()
    )
    graph = build_intake_gate_graph()

    result = await graph.ainvoke(
        {
            "completeness": completeness,
            "clarification_questions": [],
            "clarification_answers": {},
            "research_started": False,
        }
    )

    assert result["research_started"] is False
    assert result.get("__interrupt__")


@pytest.mark.asyncio
async def test_graph_reaches_research_when_required_fields_are_confirmed() -> None:
    brief = OperationsBrief(
        current_problem=BriefField[str].from_user("首周流失高", "首周流失高"),
        operation_goal=BriefField[str].from_user("提升次月留存", "提升次月留存"),
        target_users=BriefField[str].from_user("新注册用户", "新注册用户"),
        business_stage=BriefField[str].from_user("增长期", "增长期"),
        execution_period=BriefField[str].from_user("未来90天", "未来90天"),
        budget_and_resources=BriefField[str].from_user("2名运营", "2名运营"),
        current_baseline=BriefField[str].from_user("次月留存15%", "次月留存15%"),
    )
    completeness = check_completeness(
        brief, _classification(), load_default_registry()
    )
    graph = build_intake_gate_graph()

    result = await graph.ainvoke(
        {
            "completeness": completeness,
            "clarification_questions": [],
            "clarification_answers": {},
            "research_started": False,
        }
    )

    assert completeness.ready_for_research is True
    assert result["research_started"] is True
    assert "__interrupt__" not in result
    assert brief.current_baseline.status is FieldStatus.CONFIRMED


def test_unknown_baseline_stays_unknown_after_question_generation() -> None:
    brief = _incomplete_brief()
    completeness = check_completeness(brief, _classification(), load_default_registry())

    prioritize_clarifying_questions(completeness)

    assert brief.current_baseline.status is FieldStatus.UNKNOWN
    assert brief.current_baseline.value is None
