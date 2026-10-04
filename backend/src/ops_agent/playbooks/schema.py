"""Strict schema for version-controlled professional operations playbooks."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from ops_agent.domain.base import DomainModel
from ops_agent.domain.intake import OperationsScene
from ops_agent.domain.report import MetricType

PlaybookScene = OperationsScene | Literal["core"]


class QuestionPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"


class ClarifyingQuestion(DomainModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    field: str = Field(min_length=2, max_length=100)
    prompt: str = Field(min_length=5, max_length=500)
    priority: QuestionPriority
    rationale: str = Field(min_length=5, max_length=500)


class DiagnosticDimension(DomainModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=100)
    focus_questions: list[str] = Field(min_length=1)
    required_outputs: list[str] = Field(min_length=1)


class StrategySection(DomainModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=100)
    purpose: str = Field(min_length=5, max_length=500)
    required_fields: list[str] = Field(min_length=2)
    decision_rules: list[str] = Field(min_length=1)


class PlaybookMetric(DomainModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=100)
    metric_type: MetricType
    definition: str = Field(min_length=5, max_length=500)
    formula: str = Field(min_length=3, max_length=500)
    decision_use: str = Field(min_length=5, max_length=500)


class RuleSeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"


class QualityRule(DomainModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    severity: RuleSeverity
    description: str = Field(min_length=5, max_length=500)
    check: str = Field(min_length=5, max_length=500)
    remediation: str = Field(min_length=5, max_length=500)


class Playbook(DomainModel):
    schema_version: Literal["1.0"]
    playbook_version: str = Field(pattern=r"^[1-9]\d*\.\d+\.\d+$")
    scene: PlaybookScene
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=10, max_length=1000)
    required_input_fields: list[str] = Field(min_length=1)
    recommended_input_fields: list[str] = Field(default_factory=list)
    clarifying_questions: list[ClarifyingQuestion] = Field(min_length=1)
    diagnostic_dimensions: list[DiagnosticDimension] = Field(min_length=1)
    strategy_sections: list[StrategySection] = Field(min_length=1)
    required_metrics: list[PlaybookMetric] = Field(min_length=1)
    quality_rules: list[QualityRule] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_keys_and_input_sets(self) -> Self:
        overlap = set(self.required_input_fields) & set(self.recommended_input_fields)
        if overlap:
            raise ValueError(f"input fields cannot be both required and recommended: {overlap}")
        for field_name in ("required_input_fields", "recommended_input_fields"):
            values = getattr(self, field_name)
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must contain unique values")
        for field_name in (
            "clarifying_questions",
            "diagnostic_dimensions",
            "strategy_sections",
            "required_metrics",
            "quality_rules",
        ):
            items = getattr(self, field_name)
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{field_name} IDs must be unique")
        return self
