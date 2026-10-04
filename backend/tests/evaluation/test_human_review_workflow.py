"""Executable verification of the human sampling-review manual and output."""

from pathlib import Path

from ops_agent.domain.quality import (
    QualityDimension,
    QualityRuleCode,
    RevisionTarget,
)
from ops_agent.evaluation import (
    HumanReviewFinding,
    load_default_human_review_rubric,
    load_human_review_submission_file,
    score_human_review,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_EXAMPLE_PATH = _PROJECT_ROOT / "docs" / "examples" / "human-review.example.yaml"
_MANUAL_PATH = _PROJECT_ROOT / "docs" / "quality-review-manual.md"


def test_reviewer_can_load_example_and_produce_structured_passing_result() -> None:
    submission = load_human_review_submission_file(_EXAMPLE_PATH)
    rubric = load_default_human_review_rubric()

    assessment = score_human_review(submission, rubric)
    serialized = assessment.model_dump(mode="json")

    assert assessment.weighted_score == 4.15
    assert assessment.passed is True
    assert assessment.below_threshold_dimensions == []
    assert assessment.blocking_finding_ids == []
    assert serialized["submission"]["scenario_id"] == "golden-acquisition-01"
    assert serialized["required_revision_targets"] == []


def test_blocker_or_below_threshold_dimension_forces_failed_assessment() -> None:
    submission = load_human_review_submission_file(_EXAMPLE_PATH)
    scores = list(submission.dimension_scores)
    scores[1] = scores[1].model_copy(update={"score": 2})
    finding = HumanReviewFinding(
        finding_id="finding-evidence-001",
        dimension=QualityDimension.EVIDENCE_QUALITY,
        blocking=True,
        description="关键效果数据只有二手描述，无法从可访问原始来源核验。",
        report_location="案例证据第2项",
        revision_target=RevisionTarget.RESEARCH,
        owner_role="研究节点负责人",
    )
    submission = submission.model_copy(
        update={"dimension_scores": scores, "findings": [finding]}
    )

    assessment = score_human_review(submission, load_default_human_review_rubric())

    assert assessment.passed is False
    assert assessment.below_threshold_dimensions == [QualityDimension.EVIDENCE_QUALITY]
    assert assessment.blocking_finding_ids == ["finding-evidence-001"]
    assert assessment.required_revision_targets == [RevisionTarget.RESEARCH]


def test_manual_lists_every_hard_rule_and_operational_review_step() -> None:
    manual = _MANUAL_PATH.read_text(encoding="utf-8")

    for rule in QualityRuleCode:
        assert f"`{rule.value}`" in manual
    assert "七维人工评分方法" in manual
    assert "操作步骤" in manual
    assert "结构化结果格式" in manual
    assert "不得在评分过程中直接改写原报告" in manual
