"""Prioritized Playbook clarification and the pre-research interrupt gate."""

from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ops_agent.playbooks.schema import ClarifyingQuestion, QuestionPriority
from ops_agent.workflows.classification import BriefCompleteness


class IntakeGateState(TypedDict):
    completeness: BriefCompleteness
    clarification_questions: list[ClarifyingQuestion]
    clarification_answers: dict[str, str]
    research_started: bool


def prioritize_clarifying_questions(
    completeness: BriefCompleteness,
) -> list[ClarifyingQuestion]:
    """Return one ordered, deduplicated set of questions for blocking gaps first."""
    by_id = {
        question.id: question
        for question in completeness.merged_playbook.clarifying_questions
    }
    questions: list[ClarifyingQuestion] = []
    for gap in [*completeness.required_gaps, *completeness.recommended_gaps]:
        matched = [by_id[item_id] for item_id in gap.question_ids if item_id in by_id]
        if matched:
            questions.extend(matched)
            continue
        questions.append(_fallback_question(gap.field, gap.importance == "required"))

    priority_order = {
        QuestionPriority.CRITICAL: 0,
        QuestionPriority.HIGH: 1,
        QuestionPriority.MEDIUM: 2,
    }
    required_fields = {gap.field for gap in completeness.required_gaps}
    unique = {question.id: question for question in questions}
    return sorted(
        unique.values(),
        key=lambda item: (
            0 if item.field in required_fields else 1,
            priority_order[item.priority],
            item.id,
        ),
    )


def build_intake_gate_graph() -> Any:
    """Compile the minimal gate proving research cannot run before clarification."""
    builder = StateGraph(IntakeGateState)
    builder.add_node("clarification_gate", _clarification_gate)
    builder.add_node("research", _research_probe)
    builder.add_edge(START, "clarification_gate")
    builder.add_edge("clarification_gate", "research")
    builder.add_edge("research", END)
    return builder.compile()


def _clarification_gate(state: IntakeGateState) -> IntakeGateState:
    questions = prioritize_clarifying_questions(state["completeness"])
    if state["completeness"].required_gaps:
        answers = cast(
            dict[str, str],
            interrupt(
                {
                    "type": "clarification_required",
                    "questions": [
                        question.model_dump(mode="json") for question in questions
                    ],
                }
            ),
        )
        return {
            **state,
            "clarification_questions": questions,
            "clarification_answers": answers,
        }
    return {**state, "clarification_questions": questions}


def _research_probe(state: IntakeGateState) -> IntakeGateState:
    return {**state, "research_started": True}


def _fallback_question(field: str, required: bool) -> ClarifyingQuestion:
    prompt, rationale = _FALLBACK_QUESTIONS.get(
        field,
        (
            f"请补充 {field} 的可确认信息；如果目前无法提供，请明确说明未知。",
            "该信息会影响方案选择或后续验证设计。",
        ),
    )
    return ClarifyingQuestion(
        id=f"fallback_{field}",
        field=field,
        prompt=prompt,
        priority=QuestionPriority.CRITICAL if required else QuestionPriority.MEDIUM,
        rationale=rationale,
    )


_FALLBACK_QUESTIONS: dict[str, tuple[str, str]] = {
    "business_context": (
        "请简要说明产品、业务模式和本次运营所处的业务背景。",
        "业务背景用于判断案例和策略是否具备可迁移性。",
    ),
    "current_problem": (
        "目前最需要解决的具体运营问题是什么，有哪些可观察表现？",
        "明确当前问题才能避免把结果目标直接当作问题诊断。",
    ),
    "operation_goal": (
        "本次运营最优先改变的业务结果或用户行为是什么？",
        "没有优先目标就无法做策略取舍和效果判断。",
    ),
    "target_users": (
        "需要影响的是哪类用户，他们当前处于什么生命周期阶段？",
        "用户范围和阶段决定触点、机制与指标口径。",
    ),
    "business_stage": (
        "当前业务处于验证、增长、成熟还是调整阶段？",
        "业务阶段决定案例适配和投入方式。",
    ),
    "execution_period": (
        "希望方案覆盖什么起止时间或多长的执行周期？",
        "执行周期决定实验规模、节奏和验收节点。",
    ),
    "budget_and_resources": (
        "可投入的人员、渠道、内容产能、工具和预算上限分别是什么？",
        "资源边界决定方案范围和必须做出的取舍。",
    ),
    "existing_channels": (
        "目前可使用哪些自有、付费或合作渠道？",
        "已有渠道影响触达可行性和新增能力成本。",
    ),
    "current_baseline": (
        "当前相关指标的口径和基线是多少；若没有数据，请明确说明未知。",
        "基线决定目标只能使用有依据的区间还是先建立测量实验。",
    ),
    "constraints": (
        "有哪些不能做、必须遵守或可能阻碍执行的限制？",
        "明确限制可以避免生成无法落地或越界的建议。",
    ),
}
