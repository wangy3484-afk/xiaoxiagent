"""Strict schemas for golden scenarios and seven-dimension human scoring."""

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from ops_agent.domain.base import DomainModel
from ops_agent.domain.intake import FieldStatus, OperationsScene
from ops_agent.domain.quality import QualityDimension, RevisionTarget
from ops_agent.domain.report import ReportDeliveryStatus


class RequiredReportSection(StrEnum):
    EXECUTIVE_SUMMARY = "executive_summary"
    OPERATIONS_BRIEF = "operations_brief"
    DIAGNOSIS = "diagnosis"
    GOALS_AND_METRICS = "goals_and_metrics"
    AUDIENCE_ANALYSIS = "audience_analysis"
    CASE_EVIDENCE = "case_evidence"
    STRATEGY_DESIGN = "strategy_design"
    ACTION_PLAN = "action_plan"
    RESOURCE_AND_BUDGET = "resource_and_budget"
    EXPERIMENT_PLAN = "experiment_plan"
    RISK_PLAN = "risk_plan"
    EVIDENCE_APPENDIX = "evidence_appendix"


class GoldenExpectedBlocker(DomainModel):
    blocker_code: str = Field(min_length=3, max_length=120)
    rationale: str = Field(min_length=10, max_length=1200)
    revision_target: RevisionTarget


class GoldenScenario(DomainModel):
    scenario_id: str = Field(pattern=r"^golden-(acquisition|retention|campaign|content)-\d{2}$")
    scene: OperationsScene
    title: str = Field(min_length=5, max_length=200)
    anonymized_context: str = Field(min_length=20, max_length=2000)
    input_text: str = Field(min_length=20, max_length=3000)
    known_constraints: list[str] = Field(min_length=1)
    baseline_status: FieldStatus
    expected_delivery_status: ReportDeliveryStatus
    required_sections: list[RequiredReportSection] = Field(min_length=12)
    expected_blockers: list[GoldenExpectedBlocker]
    professional_review_benchmark: dict[QualityDimension, str]

    @model_validator(mode="after")
    def validate_scenario_coverage_and_anonymity(self) -> Self:
        if set(self.required_sections) != set(RequiredReportSection):
            raise ValueError("golden scenarios must require every report section")
        if len(self.required_sections) != len(set(self.required_sections)):
            raise ValueError("golden scenario report sections must be unique")
        if set(self.professional_review_benchmark) != set(QualityDimension):
            raise ValueError("golden scenarios must benchmark all seven quality dimensions")
        if self.expected_delivery_status is ReportDeliveryStatus.FORMAL:
            if self.expected_blockers:
                raise ValueError("formal golden scenarios cannot expect blocking issues")
        elif not self.expected_blockers:
            raise ValueError("limited golden scenarios must declare expected blockers")
        prohibited_names = {"淘宝", "京东", "滴滴", "链家", "小红书"}
        combined_text = f"{self.title} {self.anonymized_context} {self.input_text}"
        if any(name in combined_text for name in prohibited_names):
            raise ValueError("golden scenarios must remain anonymous")
        return self


class GoldenScenarioSet(DomainModel):
    schema_version: str = Field(pattern=r"^1\.\d+$")
    scenarios: list[GoldenScenario] = Field(min_length=12)

    @model_validator(mode="after")
    def validate_scene_distribution(self) -> Self:
        ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("golden scenario IDs must be unique")
        counts = {
            scene: sum(scenario.scene is scene for scenario in self.scenarios)
            for scene in OperationsScene
        }
        if any(count < 3 for count in counts.values()):
            raise ValueError("golden scenarios require at least three cases per scene")
        return self


class RubricDimension(DomainModel):
    dimension: QualityDimension
    weight: int = Field(ge=1, le=100)
    passing_score: int = Field(ge=1, le=5)
    review_question: str = Field(min_length=10, max_length=1000)
    score_1_anchor: str = Field(min_length=10, max_length=1200)
    score_3_anchor: str = Field(min_length=10, max_length=1200)
    score_5_anchor: str = Field(min_length=10, max_length=1200)


class HumanReviewRubric(DomainModel):
    schema_version: str = Field(pattern=r"^1\.\d+$")
    scale_min: int = Field(default=1, ge=1, le=5)
    scale_max: int = Field(default=5, ge=1, le=5)
    overall_passing_score: float = Field(ge=1, le=5)
    dimensions: list[RubricDimension] = Field(min_length=7, max_length=7)
    blocking_policy: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_rubric_dimensions(self) -> Self:
        if self.scale_min >= self.scale_max:
            raise ValueError("human review scale minimum must be lower than maximum")
        dimensions = [item.dimension for item in self.dimensions]
        if set(dimensions) != set(QualityDimension) or len(dimensions) != len(
            QualityDimension
        ):
            raise ValueError("human review rubric must cover all seven dimensions")
        if sum(item.weight for item in self.dimensions) != 100:
            raise ValueError("human review rubric weights must total 100")
        return self


class HumanDimensionScore(DomainModel):
    dimension: QualityDimension
    score: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=10, max_length=1500)
    report_locations: list[str] = Field(min_length=1)


class HumanReviewFinding(DomainModel):
    finding_id: str = Field(min_length=1, max_length=120)
    dimension: QualityDimension
    blocking: bool
    description: str = Field(min_length=10, max_length=1500)
    report_location: str = Field(min_length=1, max_length=500)
    revision_target: RevisionTarget
    owner_role: str = Field(min_length=2, max_length=200)


class HumanReviewSubmission(DomainModel):
    review_id: str = Field(min_length=1, max_length=120)
    scenario_id: str = Field(min_length=1, max_length=120)
    report_id: str = Field(min_length=1, max_length=120)
    reviewer_role: str = Field(min_length=2, max_length=200)
    reviewed_at: datetime
    dimension_scores: list[HumanDimensionScore] = Field(min_length=7, max_length=7)
    findings: list[HumanReviewFinding] = Field(default_factory=list)
    overall_comment: str = Field(min_length=10, max_length=3000)

    @model_validator(mode="after")
    def validate_review_submission(self) -> Self:
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("human review timestamp must include a timezone")
        dimensions = [item.dimension for item in self.dimension_scores]
        if set(dimensions) != set(QualityDimension) or len(dimensions) != len(
            QualityDimension
        ):
            raise ValueError("human review submission must score all seven dimensions")
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("human review finding IDs must be unique")
        return self


class HumanReviewAssessment(DomainModel):
    submission: HumanReviewSubmission
    weighted_score: float = Field(ge=1, le=5)
    passed: bool
    below_threshold_dimensions: list[QualityDimension]
    blocking_finding_ids: list[str]
    required_revision_targets: list[RevisionTarget]
