"""Research planning, evidence, case-mechanism, and claim contracts."""

from datetime import date, datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, HttpUrl, model_validator

from ops_agent.domain.base import DomainModel


class ResearchQueryKind(StrEnum):
    NAMED_COMPANY = "named_company"
    STRUCTURALLY_SIMILAR = "structurally_similar"
    MECHANISM = "mechanism"
    EVIDENCE_VALIDATION = "evidence_validation"


class ResearchQuery(DomainModel):
    query_id: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=3, max_length=500)
    purpose: str = Field(min_length=3, max_length=500)
    kind: ResearchQueryKind
    expected_evidence: list[str] = Field(min_length=1)
    target_company: str | None = Field(default=None, min_length=1, max_length=100)
    max_results: int = Field(default=8, ge=1, le=20)

    @model_validator(mode="after")
    def require_company_for_named_query(self) -> Self:
        if self.kind is ResearchQueryKind.NAMED_COMPANY and not self.target_company:
            raise ValueError("named-company queries require target_company")
        return self


class ResearchBudget(DomainModel):
    max_queries: int = Field(ge=1, le=100)
    max_pages: int = Field(ge=1, le=500)
    max_seconds: int = Field(ge=10, le=7200)


class ResearchPlan(DomainModel):
    topics: list[str] = Field(min_length=1)
    named_companies: list[str] = Field(default_factory=list)
    similarity_dimensions: list[str] = Field(min_length=1)
    queries: list[ResearchQuery] = Field(min_length=1)
    stop_conditions: list[str] = Field(min_length=1)
    budget: ResearchBudget

    @model_validator(mode="after")
    def enforce_query_budget_and_named_company_coverage(self) -> Self:
        if len(self.queries) > self.budget.max_queries:
            raise ValueError("research queries exceed the configured query budget")
        queried_companies = {
            query.target_company
            for query in self.queries
            if query.kind is ResearchQueryKind.NAMED_COMPANY
        }
        missing = set(self.named_companies) - queried_companies
        if missing:
            raise ValueError(f"named companies lack a dedicated query: {sorted(missing)}")
        if self.named_companies and not any(
            query.kind is ResearchQueryKind.STRUCTURALLY_SIMILAR for query in self.queries
        ):
            raise ValueError("named-company research must include structurally similar cases")
        return self


class SourceType(StrEnum):
    OFFICIAL_PRIMARY = "official_primary"
    TRUSTED_THIRD_PARTY = "trusted_third_party"
    GENERAL_SECONDARY = "general_secondary"


class CredibilityLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CredibilityAssessment(DomainModel):
    level: CredibilityLevel
    rationale: str = Field(min_length=10, max_length=1000)
    independence_notes: str = Field(min_length=3, max_length=500)


class PublicationDateStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class FreshnessLevel(StrEnum):
    CURRENT = "current"
    RECENT = "recent"
    STALE = "stale"
    UNKNOWN = "unknown"


class EvidenceFreshness(DomainModel):
    level: FreshnessLevel
    publication_date_status: PublicationDateStatus
    publication_date: date | None
    rationale: str = Field(min_length=5, max_length=500)

    @model_validator(mode="after")
    def validate_publication_date_status(self) -> Self:
        if self.publication_date_status is PublicationDateStatus.KNOWN:
            if self.publication_date is None:
                raise ValueError("known freshness requires a publication date")
        elif self.publication_date is not None:
            raise ValueError("unknown freshness cannot contain a guessed date")
        if self.level is FreshnessLevel.UNKNOWN and (
            self.publication_date_status is not PublicationDateStatus.UNKNOWN
        ):
            raise ValueError("unknown freshness requires unknown publication date status")
        return self


class EvidenceVerificationStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CONFLICTED = "conflicted"


class AdaptationDimensionName(StrEnum):
    OPERATIONS_GOAL = "operations_goal"
    TARGET_USER = "target_user"
    BUSINESS_STAGE = "business_stage"
    BUSINESS_MODEL = "business_model"
    CHANNEL_CONDITIONS = "channel_conditions"
    RESOURCE_SCALE = "resource_scale"
    TIME_CONTEXT = "time_context"


class AdaptationAssessment(DomainModel):
    dimension: AdaptationDimensionName
    score: int = Field(ge=1, le=5)
    rationale: str = Field(min_length=5, max_length=500)


class EvidenceAssessment(DomainModel):
    source_id: str = Field(min_length=1, max_length=80)
    source_type: SourceType
    credibility: CredibilityAssessment
    freshness: EvidenceFreshness
    adaptation: list[AdaptationAssessment] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def require_all_adaptation_dimensions(self) -> Self:
        dimensions = [item.dimension for item in self.adaptation]
        required = set(AdaptationDimensionName)
        if set(dimensions) != required or len(dimensions) != len(required):
            raise ValueError("evidence assessment must cover all adaptation dimensions")
        return self


class EvidenceRecord(DomainModel):
    evidence_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    publisher: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    url: HttpUrl
    publication_date: date | None
    publication_date_status: PublicationDateStatus
    accessed_at: datetime
    supporting_excerpt: str = Field(min_length=1, max_length=1500)
    context_summary: str = Field(min_length=1, max_length=1500)
    supported_claim_ids: list[str] = Field(default_factory=list)
    credibility: CredibilityAssessment
    verification_status: EvidenceVerificationStatus
    source_accessible: bool
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    adaptation: list[AdaptationAssessment] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_evidence_traceability(self) -> Self:
        if self.accessed_at.tzinfo is None or self.accessed_at.utcoffset() is None:
            raise ValueError("accessed_at must include a timezone")
        if self.publication_date_status is PublicationDateStatus.KNOWN:
            if self.publication_date is None:
                raise ValueError("known publication dates require a date")
        elif self.publication_date is not None:
            raise ValueError("unknown publication dates cannot contain a guessed date")

        if self.verification_status is EvidenceVerificationStatus.VERIFIED:
            if not self.source_accessible:
                raise ValueError("verified evidence must have an accessible source page")
            if not self.supported_claim_ids:
                raise ValueError("verified evidence must identify supported claims")
        if self.adaptation:
            dimensions = [item.dimension for item in self.adaptation]
            if len(dimensions) != len(set(dimensions)):
                raise ValueError("adaptation dimensions must be unique")
        return self


class ClaimType(StrEnum):
    FACT = "fact"
    INFERENCE = "inference"
    RECOMMENDATION = "recommendation"
    HYPOTHESIS = "hypothesis"


class Claim(DomainModel):
    claim_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=3, max_length=2000)
    claim_type: ClaimType
    evidence_ids: list[str] = Field(default_factory=list)
    reasoning: str = Field(min_length=3, max_length=1500)
    verification_status: EvidenceVerificationStatus

    @model_validator(mode="after")
    def facts_require_verified_evidence(self) -> Self:
        if self.claim_type is ClaimType.FACT:
            if not self.evidence_ids:
                raise ValueError("fact claims require evidence")
            if self.verification_status is not EvidenceVerificationStatus.VERIFIED:
                raise ValueError("fact claims must be verified")
        return self


class EvidenceSupportType(StrEnum):
    DIRECT = "direct"
    CONTEXT = "context"
    CONTRADICTS = "contradicts"


class ClaimEvidenceLink(DomainModel):
    claim_id: str = Field(min_length=1, max_length=80)
    evidence_id: str = Field(min_length=1, max_length=80)
    support_type: EvidenceSupportType
    rationale: str = Field(min_length=3, max_length=1000)


class CaseMechanism(DomainModel):
    case_id: str = Field(min_length=1, max_length=80)
    company: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=3, max_length=1000)
    audience: str = Field(min_length=3, max_length=1000)
    touchpoints: list[str] = Field(min_length=1)
    mechanism: str = Field(min_length=3, max_length=2000)
    incentive: str | None = Field(default=None, max_length=1000)
    execution_conditions: list[str] = Field(min_length=1)
    observed_outcomes: list[Claim] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    transferable_elements: list[str] = Field(min_length=1)
    non_transferable_elements: list[str] = Field(min_length=1)


class EvidenceBundle(DomainModel):
    """Cross-validated claim-to-evidence graph used by downstream reporting."""

    claims: list[Claim]
    evidence: list[EvidenceRecord]
    links: list[ClaimEvidenceLink]

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        claim_ids = {claim.claim_id for claim in self.claims}
        evidence_ids = {record.evidence_id for record in self.evidence}
        if len(claim_ids) != len(self.claims):
            raise ValueError("claim IDs must be unique")
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("evidence IDs must be unique")

        link_pairs = {(link.claim_id, link.evidence_id) for link in self.links}
        for link in self.links:
            if link.claim_id not in claim_ids or link.evidence_id not in evidence_ids:
                raise ValueError("claim-evidence links must reference existing records")
        for claim in self.claims:
            if any(evidence_id not in evidence_ids for evidence_id in claim.evidence_ids):
                raise ValueError("claims cannot reference missing evidence")
            missing_links = [
                evidence_id
                for evidence_id in claim.evidence_ids
                if (claim.claim_id, evidence_id) not in link_pairs
            ]
            if missing_links:
                raise ValueError("each claim evidence reference requires an explicit link")
        for record in self.evidence:
            if any(claim_id not in claim_ids for claim_id in record.supported_claim_ids):
                raise ValueError("evidence cannot reference missing claims")
        return self


class EvidenceCoverageStatus(StrEnum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    CONFLICTED = "conflicted"


class EvidenceConflict(DomainModel):
    conflict_id: str = Field(min_length=1, max_length=80)
    claim_ids: list[str] = Field(min_length=2)
    evidence_ids: list[str] = Field(min_length=2)
    summary: str = Field(min_length=5, max_length=1000)
    resolution_required: bool = True


class EvidenceCoverageResult(DomainModel):
    status: EvidenceCoverageStatus
    evidence_bundle: EvidenceBundle
    independent_source_count: int = Field(ge=0)
    has_high_credibility_source: bool
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    insufficiencies: list[str] = Field(default_factory=list)
    downgraded_claim_ids: list[str] = Field(default_factory=list)
    disclosure: str = Field(min_length=5, max_length=1500)
