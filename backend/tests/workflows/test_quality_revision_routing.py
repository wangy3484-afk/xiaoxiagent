"""Bounded quality-revision graph routing tests."""

from collections.abc import Callable

from ops_agent.domain.quality import (
    DeterministicQualityIssue,
    DeterministicQualityResult,
    ProfessionalQualityReview,
    QualityRouteStatus,
    QualityRuleCode,
    QualitySeverity,
    RevisionTarget,
)
from ops_agent.workflows.quality import (
    QualityRevisionState,
    build_quality_revision_graph,
)

from .test_professional_quality_review import _review_response


def _blocking_deterministic_review() -> DeterministicQualityResult:
    return DeterministicQualityResult(
        passed=False,
        checks_run=list(QualityRuleCode),
        issues=[
            DeterministicQualityIssue(
                issue_id="fact_citation_coverage:key_claims",
                rule_code=QualityRuleCode.FACT_CITATION_COVERAGE,
                severity=QualitySeverity.BLOCKING,
                message="事实主张缺少有效证据引用。",
                location="key_claims",
                remediation="返回研究节点补充证据或降级主张。",
            )
        ],
    )


def _passing_deterministic_review() -> DeterministicQualityResult:
    return DeterministicQualityResult(
        passed=True,
        checks_run=list(QualityRuleCode),
    )


def _blocking_professional_review() -> ProfessionalQualityReview:
    return ProfessionalQualityReview.model_validate(_review_response())


def _passing_professional_review() -> ProfessionalQualityReview:
    data = _review_response()
    data["passed"] = True
    data["findings"] = []
    data["blocking_issue_ids"] = []
    data["summary"] = "七个专业维度均通过审查，可以进入交付判定。"
    dimensions = data["dimensions"]
    assert isinstance(dimensions, list)
    for item in dimensions:
        assert isinstance(item, dict)
        item["verdict"] = "pass"
        item["rationale"] = "该维度的报告内容、依据和约束均满足当前交付门槛。"
    return ProfessionalQualityReview.model_validate(data)


def _revision_node(state: QualityRevisionState) -> dict[str, object]:
    decision = state["route_decision"]
    history = [*state.get("revision_history", []), decision.targets]
    return {"revision_history": history}


def test_graph_passes_after_one_targeted_revision() -> None:
    blocking_deterministic = _blocking_deterministic_review()
    passing_deterministic = _passing_deterministic_review()
    blocking_professional = _blocking_professional_review()
    passing_professional = _passing_professional_review()

    def review_node(state: QualityRevisionState) -> dict[str, object]:
        if state["revision_round"] == 0:
            return {
                "deterministic_quality": blocking_deterministic,
                "professional_review": blocking_professional,
            }
        return {
            "deterministic_quality": passing_deterministic,
            "professional_review": passing_professional,
        }

    graph = build_quality_revision_graph(
        review_node=review_node,
        revision_node=_revision_node,
    )
    result = graph.invoke({"revision_round": 0, "revision_history": []})

    assert result["route_decision"].status is QualityRouteStatus.PASSED
    assert result["revision_round"] == 1
    assert len(result["revision_history"]) == 1
    assert set(result["revision_history"][0]) == {
        RevisionTarget.RESEARCH,
        RevisionTarget.STRATEGY,
        RevisionTarget.PLAN,
    }


def test_graph_stops_unresolved_after_two_revision_rounds() -> None:
    review_calls = 0

    def review_node(state: QualityRevisionState) -> dict[str, object]:
        nonlocal review_calls
        review_calls += 1
        return {
            "deterministic_quality": _blocking_deterministic_review(),
            "professional_review": _blocking_professional_review(),
        }

    graph = build_quality_revision_graph(
        review_node=review_node,
        revision_node=_revision_node,
    )
    result = graph.invoke({"revision_round": 0, "revision_history": []})

    assert result["route_decision"].status is QualityRouteStatus.UNRESOLVED
    assert result["revision_round"] == 2
    assert len(result["revision_history"]) == 2
    assert review_calls == 3


def test_revision_graph_callback_contract_is_sync_callable() -> None:
    callback: Callable[[QualityRevisionState], dict[str, object]] = _revision_node
    assert callable(callback)
