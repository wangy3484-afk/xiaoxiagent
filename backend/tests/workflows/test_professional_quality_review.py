"""Independent seven-dimension professional review tests."""

import pytest
from ops_agent.domain.quality import (
    ProfessionalIssueType,
    QualityDimension,
    RevisionTarget,
)
from ops_agent.providers import DeterministicModelProvider
from ops_agent.workflows.quality import (
    check_operations_report,
    review_operations_report,
)

from .test_deterministic_quality import _valid_report


def _dimension(dimension: str, verdict: str, rationale: str) -> dict[str, object]:
    return {
        "dimension": dimension,
        "verdict": verdict,
        "rationale": rationale,
        "supporting_ids": [],
    }


def _finding(
    finding_id: str,
    dimension: str,
    issue_type: str,
    revision_target: str,
    rationale: str,
) -> dict[str, object]:
    return {
        "finding_id": finding_id,
        "dimension": dimension,
        "issue_type": issue_type,
        "blocking": True,
        "rationale": rationale,
        "related_ids": ["strategy-1"],
        "revision_target": revision_target,
        "remediation": "缩小结论范围并补充验证依据后重新审查。",
    }


def _review_response() -> dict[str, object]:
    findings = [
        _finding(
            "finding-causation",
            "evidence_quality",
            "correlation_as_causation",
            "research",
            "现有证据只证明企业实施过动作，不能证明该动作导致转化提升。",
        ),
        _finding(
            "finding-generalization",
            "scene_fit",
            "single_case_generalization",
            "strategy",
            "报告从单一案例推导普遍适用结论，缺少场景边界和独立来源验证。",
        ),
        _finding(
            "finding-resource",
            "execution_feasibility",
            "resource_conflict",
            "plan",
            "行动范围超过当前两名运营可承担的并行产能，需要缩小执行范围。",
        ),
        _finding(
            "finding-precision",
            "measurement",
            "false_precision",
            "plan",
            "当前没有可靠基线，精确提升幅度只能作为待验证假设。",
        ),
    ]
    return {
        "review_id": "professional-review-1",
        "passed": False,
        "dimensions": [
            _dimension(
                "requirements_completeness",
                "pass",
                "目标用户、运营目标和核心约束均已结构化记录。",
            ),
            _dimension(
                "evidence_quality",
                "fail",
                "证据只能证明实施动作，尚不能支持因果效果结论。",
            ),
            _dimension(
                "scene_fit",
                "fail",
                "单一案例不能直接泛化到当前冷启动社区场景。",
            ),
            _dimension(
                "strategy_logic",
                "warning",
                "策略影响路径合理，但仍需明确替代解释。",
            ),
            _dimension(
                "execution_feasibility",
                "fail",
                "执行范围与当前团队产能存在冲突。",
            ),
            _dimension(
                "measurement",
                "fail",
                "无基线条件下存在虚假精确风险。",
            ),
            _dimension(
                "risk_coverage",
                "pass",
                "主要风险包含触发条件、负责人和监控指标。",
            ),
        ],
        "findings": findings,
        "blocking_issue_ids": [item["finding_id"] for item in findings],
        "summary": "报告结构完整，但四类专业问题需要定向返工后才能进入正式交付。",
    }


@pytest.mark.asyncio
async def test_review_identifies_four_professional_failure_patterns_without_rewrite() -> None:
    report = await _valid_report()
    deterministic_quality = check_operations_report(report)
    model = DeterministicModelProvider(
        {"professional_quality_review": _review_response()}
    )

    state = await review_operations_report(
        {
            "report": report,
            "deterministic_quality": deterministic_quality,
        },
        model,
    )

    review = state["professional_review"]
    assert review is not None
    assert state["report"] == report
    assert len(review.dimensions) == 7
    assert {item.dimension for item in review.dimensions} == set(QualityDimension)
    assert {item.issue_type for item in review.findings} == {
        ProfessionalIssueType.CORRELATION_AS_CAUSATION,
        ProfessionalIssueType.SINGLE_CASE_GENERALIZATION,
        ProfessionalIssueType.RESOURCE_CONFLICT,
        ProfessionalIssueType.FALSE_PRECISION,
    }
    targets = {item.issue_type: item.revision_target for item in review.findings}
    assert targets[ProfessionalIssueType.CORRELATION_AS_CAUSATION] is RevisionTarget.RESEARCH
    assert targets[ProfessionalIssueType.SINGLE_CASE_GENERALIZATION] is RevisionTarget.STRATEGY
    assert targets[ProfessionalIssueType.RESOURCE_CONFLICT] is RevisionTarget.PLAN
    assert targets[ProfessionalIssueType.FALSE_PRECISION] is RevisionTarget.PLAN
    assert review.passed is False
