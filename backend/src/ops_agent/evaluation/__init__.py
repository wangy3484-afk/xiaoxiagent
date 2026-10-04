"""Golden scenarios and human-review rubric for operations report evaluation."""

from ops_agent.evaluation.batch import GoldenBatchResult, evaluate_golden_batch
from ops_agent.evaluation.golden import GoldenEvaluationResult, evaluate_golden_report
from ops_agent.evaluation.loader import (
    load_default_golden_scenarios,
    load_default_human_review_rubric,
    load_golden_scenario_file,
    load_human_review_rubric_file,
    load_human_review_submission_file,
)
from ops_agent.evaluation.schema import (
    GoldenExpectedBlocker,
    GoldenScenario,
    GoldenScenarioSet,
    HumanReviewAssessment,
    HumanReviewFinding,
    HumanReviewRubric,
    HumanReviewSubmission,
    RequiredReportSection,
    RubricDimension,
)
from ops_agent.evaluation.scoring import score_human_review

__all__ = [
    "GoldenBatchResult",
    "GoldenExpectedBlocker",
    "GoldenEvaluationResult",
    "GoldenScenario",
    "GoldenScenarioSet",
    "HumanReviewRubric",
    "HumanReviewAssessment",
    "HumanReviewFinding",
    "HumanReviewSubmission",
    "RequiredReportSection",
    "RubricDimension",
    "load_default_golden_scenarios",
    "load_default_human_review_rubric",
    "load_golden_scenario_file",
    "load_human_review_rubric_file",
    "load_human_review_submission_file",
    "score_human_review",
    "evaluate_golden_report",
    "evaluate_golden_batch",
]
