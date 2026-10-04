"""Contracts for deterministic and professional report quality review."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from ops_agent.domain.base import DomainModel


class QualityRuleCode(StrEnum):
    SECTION_COMPLETENESS = "section_completeness"
    REFERENCE_RESOLVABILITY = "reference_resolvability"
    FACT_CITATION_COVERAGE = "fact_citation_coverage"
    ACTION_CLOSED_LOOP = "action_closed_loop"
    METRIC_DEFINITION = "metric_definition"
    RESOURCE_CONSTRAINTS = "resource_constraints"
    NO_AUTOMATED_EXECUTION = "no_automated_execution"


class QualitySeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class QualityDimension(StrEnum):
    REQUIREMENTS_COMPLETENESS = "requirements_completeness"
    EVIDENCE_QUALITY = "evidence_quality"
    SCENE_FIT = "scene_fit"
    STRATEGY_LOGIC = "strategy_logic"
    EXECUTION_FEASIBILITY = "execution_feasibility"
    MEASUREMENT = "measurement"
    RISK_COVERAGE = "risk_coverage"


class ReviewVerdict(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


class RevisionTarget(StrEnum):
    RESEARCH = "research"
    DIAGNOSIS = "diagnosis"
    STRATEGY = "strategy"
    PLAN = "plan"
    ASSEMBLY = "assembly"


class QualityRouteStatus(StrEnum):
    PASSED = "passed"
    REVISE = "revise"
    UNRESOLVED = "unresolved"


class ProfessionalIssueType(StrEnum):
    CORRELATION_AS_CAUSATION = "correlation_as_causation"
    SINGLE_CASE_GENERALIZATION = "single_case_generalization"
    RESOURCE_CONFLICT = "resource_conflict"
    FALSE_PRECISION = "false_precision"
    OTHER = "other"


class DeterministicQualityIssue(DomainModel):
    issue_id: str = Field(min_length=1, max_length=120)
    rule_code: QualityRuleCode
    severity: QualitySeverity
    message: str = Field(min_length=5, max_length=1500)
    location: str = Field(min_length=1, max_length=500)
    remediation: str = Field(min_length=5, max_length=1500)
    related_ids: list[str] = Field(default_factory=list)


class DeterministicQualityResult(DomainModel):
    passed: bool
    checks_run: list[QualityRuleCode] = Field(min_length=1)
    issues: list[DeterministicQualityIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_checks_and_outcome(self) -> Self:
        if len(self.checks_run) != len(set(self.checks_run)):
            raise ValueError("deterministic quality checks must be unique")
        required_checks = set(QualityRuleCode)
        if set(self.checks_run) != required_checks:
            raise ValueError("deterministic quality result must run every required rule")
        has_blocker = any(
            issue.severity is QualitySeverity.BLOCKING for issue in self.issues
        )
        if self.passed == has_blocker:
            raise ValueError("quality result passes only when no blocking issue exists")
        return self


class DimensionReview(DomainModel):
    dimension: QualityDimension
    verdict: ReviewVerdict
    rationale: str = Field(min_length=10, max_length=2000)
    supporting_ids: list[str] = Field(default_factory=list)


class ProfessionalReviewFinding(DomainModel):
    finding_id: str = Field(min_length=1, max_length=120)
    dimension: QualityDimension
    issue_type: ProfessionalIssueType
    blocking: bool
    rationale: str = Field(min_length=10, max_length=2000)
    related_ids: list[str] = Field(default_factory=list)
    revision_target: RevisionTarget
    remediation: str = Field(min_length=10, max_length=2000)


class ProfessionalQualityReview(DomainModel):
    review_id: str = Field(min_length=1, max_length=120)
    passed: bool
    dimensions: list[DimensionReview] = Field(min_length=7, max_length=7)
    findings: list[ProfessionalReviewFinding] = Field(default_factory=list)
    blocking_issue_ids: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=10, max_length=3000)

    @model_validator(mode="after")
    def validate_dimensions_and_blockers(self) -> Self:
        dimensions = [item.dimension for item in self.dimensions]
        if set(dimensions) != set(QualityDimension) or len(dimensions) != len(
            QualityDimension
        ):
            raise ValueError("professional review must cover all seven dimensions")

        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("professional review finding IDs must be unique")
        expected_blockers = {
            finding.finding_id for finding in self.findings if finding.blocking
        }
        if set(self.blocking_issue_ids) != expected_blockers:
            raise ValueError("blocking issue IDs must match blocking findings")
        if self.passed == bool(expected_blockers):
            raise ValueError("professional review passes only when no blockers exist")
        return self


class QualityRouteDecision(DomainModel):
    status: QualityRouteStatus
    revision_round: int = Field(ge=0, le=2)
    targets: list[RevisionTarget] = Field(default_factory=list)
    issue_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=5, max_length=1500)

    @model_validator(mode="after")
    def validate_route_state(self) -> Self:
        if len(self.targets) != len(set(self.targets)):
            raise ValueError("quality revision targets must be unique")
        if len(self.issue_ids) != len(set(self.issue_ids)):
            raise ValueError("quality route issue IDs must be unique")
        if self.status is QualityRouteStatus.REVISE:
            if not self.targets or not self.issue_ids or self.revision_round < 1:
                raise ValueError("revision routes require targets, issues, and a revision round")
            return self
        if self.targets:
            raise ValueError("terminal quality routes cannot contain revision targets")
        if self.status is QualityRouteStatus.PASSED and self.issue_ids:
            raise ValueError("passed quality routes cannot contain blocking issues")
        if self.status is QualityRouteStatus.UNRESOLVED and not self.issue_ids:
            raise ValueError("unresolved quality routes require blocking issues")
        return self
