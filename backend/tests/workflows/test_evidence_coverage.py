"""Evidence conflict and coverage review tests."""

from datetime import UTC, date, datetime

from ops_agent.domain.research import (
    Claim,
    ClaimEvidenceLink,
    ClaimType,
    CredibilityAssessment,
    CredibilityLevel,
    EvidenceBundle,
    EvidenceRecord,
    EvidenceSupportType,
    EvidenceVerificationStatus,
    PublicationDateStatus,
    SourceType,
)
from ops_agent.workflows.research import review_evidence_coverage
from pydantic import HttpUrl


def _claim(claim_id: str, text: str, evidence_id: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        text=text,
        claim_type=ClaimType.FACT,
        evidence_ids=[evidence_id],
        reasoning="来源原文支持该事实。",
        verification_status=EvidenceVerificationStatus.VERIFIED,
    )


def _evidence(
    evidence_id: str,
    *,
    publisher: str,
    url: str,
    level: CredibilityLevel,
    source_type: SourceType,
    publication_date: date | None,
    publication_status: PublicationDateStatus,
    supported_claim_ids: list[str],
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        title=f"{publisher} 案例",
        publisher=publisher,
        source_type=source_type,
        url=HttpUrl(url),
        publication_date=publication_date,
        publication_date_status=publication_status,
        accessed_at=datetime(2026, 9, 30, tzinfo=UTC),
        supporting_excerpt="来源原文支持该事实。",
        context_summary="测试证据。",
        supported_claim_ids=supported_claim_ids,
        credibility=CredibilityAssessment(
            level=level,
            rationale="测试可信度说明，满足最小长度要求。",
            independence_notes="测试独立性说明。",
        ),
        verification_status=EvidenceVerificationStatus.VERIFIED,
        source_accessible=True,
        content_hash="a" * 64,
    )


def _bundle(claims: list[Claim], evidence: list[EvidenceRecord]) -> EvidenceBundle:
    return EvidenceBundle(
        claims=claims,
        evidence=evidence,
        links=[
            ClaimEvidenceLink(
                claim_id=claim.claim_id,
                evidence_id=evidence_id,
                support_type=EvidenceSupportType.DIRECT,
                rationale="原文直接支持。",
            )
            for claim in claims
            for evidence_id in claim.evidence_ids
        ],
    )


def test_detects_conflicting_numeric_claims_and_downgrades_them() -> None:
    claim_a = _claim("claim-a", "该活动GMV提升30%", "ev-a")
    claim_b = _claim("claim-b", "该活动GMV提升10%", "ev-b")
    bundle = _bundle(
        [claim_a, claim_b],
        [
            _evidence(
                "ev-a",
                publisher="官方公告",
                url="https://example.com/a",
                level=CredibilityLevel.HIGH,
                source_type=SourceType.OFFICIAL_PRIMARY,
                publication_date=date(2026, 1, 1),
                publication_status=PublicationDateStatus.KNOWN,
                supported_claim_ids=["claim-a"],
            ),
            _evidence(
                "ev-b",
                publisher="行业研究",
                url="https://research.example.com/b",
                level=CredibilityLevel.MEDIUM,
                source_type=SourceType.TRUSTED_THIRD_PARTY,
                publication_date=date(2026, 2, 1),
                publication_status=PublicationDateStatus.KNOWN,
                supported_claim_ids=["claim-b"],
            ),
        ],
    )

    result = review_evidence_coverage(bundle)

    assert result.status.value == "conflicted"
    assert result.conflicts
    assert set(result.downgraded_claim_ids) == {"claim-a", "claim-b"}
    assert {
        claim.claim_type for claim in result.evidence_bundle.claims
    } == {ClaimType.HYPOTHESIS}


def test_single_low_unknown_source_is_insufficient_and_downgrades_fact() -> None:
    claim = _claim("claim-low", "该玩法显著提升转化", "ev-low")
    bundle = _bundle(
        [claim],
        [
            _evidence(
                "ev-low",
                publisher="个人博客",
                url="https://blog.example.com/low",
                level=CredibilityLevel.LOW,
                source_type=SourceType.GENERAL_SECONDARY,
                publication_date=None,
                publication_status=PublicationDateStatus.UNKNOWN,
                supported_claim_ids=["claim-low"],
            )
        ],
    )

    result = review_evidence_coverage(bundle)

    assert result.status.value == "insufficient"
    assert result.independent_source_count == 1
    assert result.has_high_credibility_source is False
    assert result.downgraded_claim_ids == ["claim-low"]
    assert "少于三个" in result.disclosure
    assert "发布日期未知" in result.disclosure
    assert result.evidence_bundle.claims[0].verification_status is (
        EvidenceVerificationStatus.UNVERIFIED
    )


def test_no_public_evidence_is_reported_as_insufficient() -> None:
    result = review_evidence_coverage(
        EvidenceBundle(claims=[], evidence=[], links=[])
    )

    assert result.status.value == "insufficient"
    assert result.independent_source_count == 0
    assert "公开信息不足" in result.disclosure
