"""Operations intake and scene-classification contracts."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from ops_agent.domain.base import DomainModel


class OperationsScene(StrEnum):
    """Supported professional operations disciplines."""

    ACQUISITION = "acquisition"
    RETENTION = "retention"
    CAMPAIGN = "campaign"
    CONTENT = "content"


class FieldStatus(StrEnum):
    """Epistemic status of one brief field."""

    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    INFERRED = "inferred"


class FieldSource(StrEnum):
    """Origin of a brief field value."""

    USER_INPUT = "user_input"
    USER_CORRECTION = "user_correction"
    SYSTEM_INFERENCE = "system_inference"
    UNKNOWN = "unknown"


class BriefField[T](DomainModel):
    """A value plus provenance, including explicit unknown and inference states."""

    value: T | None = None
    status: FieldStatus
    source: FieldSource
    source_excerpt: str | None = Field(default=None, max_length=500)
    asserted_as_fact: bool = False

    @model_validator(mode="after")
    def enforce_epistemic_boundaries(self) -> Self:
        """Prevent unknown or inferred content from masquerading as user fact."""
        if self.status is FieldStatus.UNKNOWN:
            if self.value is not None:
                raise ValueError("unknown fields cannot contain a value")
            if self.source is not FieldSource.UNKNOWN:
                raise ValueError("unknown fields must use the unknown source")
            if self.source_excerpt is not None:
                raise ValueError("unknown fields cannot contain a source excerpt")
            if self.asserted_as_fact:
                raise ValueError("unknown fields cannot be asserted as fact")
            return self

        if self.value is None or (isinstance(self.value, str) and not self.value.strip()):
            raise ValueError("known or inferred fields require a non-empty value")

        if self.status is FieldStatus.INFERRED:
            if self.source is not FieldSource.SYSTEM_INFERENCE:
                raise ValueError("inferred fields must use the system_inference source")
            if self.asserted_as_fact:
                raise ValueError("system inference cannot be asserted as fact")
            return self

        if self.source not in {FieldSource.USER_INPUT, FieldSource.USER_CORRECTION}:
            raise ValueError("confirmed fields must originate from the user")
        if not self.source_excerpt:
            raise ValueError("confirmed fields require a user source excerpt")
        if not self.asserted_as_fact:
            raise ValueError("confirmed user fields must be marked as facts")
        return self

    @classmethod
    def unknown(cls) -> Self:
        """Construct a field whose value is explicitly unknown."""
        return cls(status=FieldStatus.UNKNOWN, source=FieldSource.UNKNOWN)

    @classmethod
    def from_user(cls, value: T, source_excerpt: str) -> Self:
        """Construct a confirmed fact traceable to user input."""
        return cls(
            value=value,
            status=FieldStatus.CONFIRMED,
            source=FieldSource.USER_INPUT,
            source_excerpt=source_excerpt,
            asserted_as_fact=True,
        )

    @classmethod
    def from_correction(cls, value: T, source_excerpt: str) -> Self:
        """Construct a confirmed fact traceable to an explicit user correction."""
        return cls(
            value=value,
            status=FieldStatus.CONFIRMED,
            source=FieldSource.USER_CORRECTION,
            source_excerpt=source_excerpt,
            asserted_as_fact=True,
        )

    @classmethod
    def inferred(cls, value: T, reasoning: str) -> Self:
        """Construct a non-factual inference for later user confirmation."""
        return cls(
            value=value,
            status=FieldStatus.INFERRED,
            source=FieldSource.SYSTEM_INFERENCE,
            source_excerpt=reasoning,
            asserted_as_fact=False,
        )


def _unknown_text() -> BriefField[str]:
    return BriefField[str].unknown()


def _unknown_list() -> BriefField[list[str]]:
    return BriefField[list[str]].unknown()


class OperationsBrief(DomainModel):
    """Structured, provenance-preserving description of an operations problem."""

    business_context: BriefField[str] = Field(default_factory=_unknown_text)
    current_problem: BriefField[str] = Field(default_factory=_unknown_text)
    operation_goal: BriefField[str] = Field(default_factory=_unknown_text)
    target_users: BriefField[str] = Field(default_factory=_unknown_text)
    business_stage: BriefField[str] = Field(default_factory=_unknown_text)
    execution_period: BriefField[str] = Field(default_factory=_unknown_text)
    budget_and_resources: BriefField[str] = Field(default_factory=_unknown_text)
    existing_channels: BriefField[list[str]] = Field(default_factory=_unknown_list)
    current_baseline: BriefField[str] = Field(default_factory=_unknown_text)
    constraints: BriefField[list[str]] = Field(default_factory=_unknown_list)
    preferred_benchmark_companies: BriefField[list[str]] = Field(default_factory=_unknown_list)

    def unknown_fields(self) -> list[str]:
        """Return stable field names that still require user confirmation."""
        return [
            field_name
            for field_name in type(self).model_fields
            if getattr(self, field_name).status is FieldStatus.UNKNOWN
        ]

    def inferred_fields(self) -> list[str]:
        """Return fields that are useful hypotheses but are not confirmed facts."""
        return [
            field_name
            for field_name in type(self).model_fields
            if getattr(self, field_name).status is FieldStatus.INFERRED
        ]


class SceneClassification(DomainModel):
    """Explainable primary and auxiliary operations-scene classification."""

    primary_scene: OperationsScene
    secondary_scenes: list[OperationsScene] = Field(default_factory=list)
    rationale: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    uncertainties: list[str] = Field(default_factory=list)
    user_corrected: bool = False

    @model_validator(mode="after")
    def validate_scene_hierarchy(self) -> Self:
        if self.primary_scene in self.secondary_scenes:
            raise ValueError("the primary scene cannot also be a secondary scene")
        if len(self.secondary_scenes) != len(set(self.secondary_scenes)):
            raise ValueError("secondary scenes must be unique")
        if self.user_corrected and self.confidence < 1:
            raise ValueError("a user-corrected classification must have confidence 1")
        return self
