"""Deterministic scoring for completed human report reviews."""

from ops_agent.evaluation.schema import (
    HumanReviewAssessment,
    HumanReviewRubric,
    HumanReviewSubmission,
)


def score_human_review(
    submission: HumanReviewSubmission,
    rubric: HumanReviewRubric,
) -> HumanReviewAssessment:
    """Apply rubric weights and blocking policy to a reviewer submission."""
    scores = {item.dimension: item.score for item in submission.dimension_scores}
    thresholds = {item.dimension: item.passing_score for item in rubric.dimensions}
    weighted_score = sum(
        scores[item.dimension] * item.weight / 100 for item in rubric.dimensions
    )
    below_threshold = [
        item.dimension
        for item in rubric.dimensions
        if scores[item.dimension] < thresholds[item.dimension]
    ]
    blocking_findings = [
        finding.finding_id for finding in submission.findings if finding.blocking
    ]
    revision_targets = list(
        dict.fromkeys(finding.revision_target for finding in submission.findings)
    )
    passed = (
        weighted_score >= rubric.overall_passing_score
        and not below_threshold
        and not blocking_findings
    )
    return HumanReviewAssessment(
        submission=submission,
        weighted_score=round(weighted_score, 2),
        passed=passed,
        below_threshold_dimensions=below_threshold,
        blocking_finding_ids=blocking_findings,
        required_revision_targets=revision_targets,
    )
