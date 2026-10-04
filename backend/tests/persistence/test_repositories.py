"""Integration tests for authorization-scoped business repositories."""

from datetime import UTC, date, datetime

import pytest
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
from ops_agent.persistence.database import create_database_engine, create_session_factory
from ops_agent.persistence.models import (
    Base,
    ClaimEvidenceLinkRecord,
    ClaimRecordRow,
    UserRecord,
)
from ops_agent.persistence.repositories import (
    AuthorizationSubject,
    BriefNotConfirmed,
    BriefRepository,
    EvidenceRepository,
    QualityReviewRepository,
    ReportJobRepository,
    ReportVersionRepository,
    ResourceNotFound,
    VersionConflict,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


async def _database() -> tuple[
    AsyncEngine,
    AsyncSession,
    AuthorizationSubject,
    AuthorizationSubject,
]:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session = create_session_factory(engine)()
    owner = AuthorizationSubject("user-owner")
    stranger = AuthorizationSubject("user-stranger")
    session.add_all(
        [
            UserRecord(id=owner.user_id, email="owner@example.com", password_hash="hash"),
            UserRecord(id=stranger.user_id, email="stranger@example.com", password_hash="hash"),
        ]
    )
    await session.flush()
    return engine, session, owner, stranger


async def _seed_brief_and_job(
    session: AsyncSession, subject: AuthorizationSubject
) -> tuple[str, str, str]:
    brief, revision = await BriefRepository(session).create(
        subject,
        brief_payload={"operation_goal": "提高留存"},
        classification_payload={"primary_scene": "retention"},
    )
    await BriefRepository(session).confirm_revision(
        subject,
        brief.id,
        expected_revision=revision.revision_number,
    )
    job = await ReportJobRepository(session).create(
        subject,
        brief_id=brief.id,
        brief_revision_id=revision.id,
        idempotency_key="job-key",
    )
    return brief.id, revision.id, job.id


@pytest.mark.asyncio
async def test_report_job_requires_latest_confirmed_brief_revision() -> None:
    engine, session, owner, _ = await _database()
    try:
        brief, revision = await BriefRepository(session).create(
            owner,
            brief_payload={"operation_goal": "提高留存"},
            classification_payload={"primary_scene": "retention"},
        )

        with pytest.raises(BriefNotConfirmed, match="latest confirmed"):
            await ReportJobRepository(session).create(
                owner,
                brief.id,
                revision.id,
                "unconfirmed-job",
            )

        confirmed = await BriefRepository(session).confirm_revision(
            owner,
            brief.id,
            expected_revision=1,
        )
        job = await ReportJobRepository(session).create(
            owner,
            brief.id,
            confirmed.id,
            "confirmed-job",
        )

        assert confirmed.is_confirmed is True
        assert brief.status == "confirmed"
        assert job.brief_revision_id == confirmed.id
    finally:
        await session.close()
        await engine.dispose()


def _evidence() -> EvidenceRecord:
    return EvidenceRecord.model_validate(
        {
            "evidence_id": "evidence-1",
            "title": "官方说明",
            "publisher": "示例企业",
            "source_type": SourceType.OFFICIAL_PRIMARY,
            "url": "https://example.com/case",
            "publication_date": date(2025, 1, 1),
            "publication_date_status": PublicationDateStatus.KNOWN,
            "accessed_at": datetime(2026, 9, 29, tzinfo=UTC),
            "supporting_excerpt": "企业上线了分层引导。",
            "context_summary": "只能证明实施动作。",
            "supported_claim_ids": ["claim-1"],
            "credibility": CredibilityAssessment(
                level=CredibilityLevel.HIGH,
                rationale="企业官方材料可直接确认实施动作。",
                independence_notes="效果仍需第三方材料验证。",
            ),
            "verification_status": EvidenceVerificationStatus.VERIFIED,
            "source_accessible": True,
            "content_hash": "c" * 64,
        }
    )


def _evidence_with(
    evidence_id: str,
    *,
    excerpt: str,
    content_hash: str,
) -> EvidenceRecord:
    data = _evidence().model_dump(mode="python")
    data.update(
        {
            "evidence_id": evidence_id,
            "supporting_excerpt": excerpt,
            "context_summary": f"上下文 {evidence_id}",
            "supported_claim_ids": [evidence_id.replace("evidence", "claim")],
            "content_hash": content_hash,
        }
    )
    return EvidenceRecord.model_validate(data)


def _claim(claim_id: str, evidence_id: str) -> Claim:
    return Claim(
        claim_id=claim_id,
        text=f"{claim_id} 对应的事实主张",
        claim_type=ClaimType.FACT,
        evidence_ids=[evidence_id],
        reasoning="原文片段直接支持。",
        verification_status=EvidenceVerificationStatus.VERIFIED,
    )


@pytest.mark.asyncio
async def test_repositories_create_read_and_hide_cross_user_resources() -> None:
    engine, session, owner, stranger = await _database()
    try:
        brief_id, revision_id, job_id = await _seed_brief_and_job(session, owner)
        evidence = await EvidenceRepository(session).add(owner, job_id, _evidence())
        report = await ReportVersionRepository(session).add_version(
            owner,
            job_id=job_id,
            brief_revision_id=revision_id,
            version_number=1,
            delivery_status="directional_draft",
            report_payload={"title": "留存方案"},
            playbook_versions={"retention": "1.0.0"},
            model_configuration={"provider": "test"},
        )
        await QualityReviewRepository(session).add(
            owner,
            report_version_id=report.id,
            revision_round=1,
            review_payload={"result": "needs_revision"},
            blocking_issue_count=1,
        )

        assert await BriefRepository(session).get(owner, brief_id) is not None
        assert await ReportJobRepository(session).get(owner, job_id) is not None
        assert await EvidenceRepository(session).get(owner, evidence.id) is not None
        assert await ReportVersionRepository(session).get_version(owner, report.id) is not None
        assert len(await QualityReviewRepository(session).list_for_report(owner, report.id)) == 1

        assert await BriefRepository(session).get(stranger, brief_id) is None
        assert await ReportJobRepository(session).get(stranger, job_id) is None
        assert await EvidenceRepository(session).get(stranger, evidence.id) is None
        assert await ReportVersionRepository(session).get_version(stranger, report.id) is None
        assert await QualityReviewRepository(session).list_for_report(stranger, report.id) == []
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_cross_user_writes_are_rejected_without_leaking_resource() -> None:
    engine, session, owner, stranger = await _database()
    try:
        _, _, job_id = await _seed_brief_and_job(session, owner)
        with pytest.raises(ResourceNotFound, match="report job not found"):
            await EvidenceRepository(session).add(stranger, job_id, _evidence())
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_evidence_bundle_persists_limited_fragments_and_merges_duplicates() -> None:
    engine, session, owner, _ = await _database()
    try:
        _, _, job_id = await _seed_brief_and_job(session, owner)
        evidence_a = _evidence_with(
            "evidence-a",
            excerpt="企业上线了首单任务。",
            content_hash="a" * 64,
        )
        evidence_b = _evidence_with(
            "evidence-b",
            excerpt="首单任务使用优惠券激励。",
            content_hash="b" * 64,
        )
        claim_a = _claim("claim-a", evidence_a.evidence_id)
        claim_b = _claim("claim-b", evidence_b.evidence_id)
        bundle = EvidenceBundle(
            claims=[claim_a, claim_b],
            evidence=[evidence_a, evidence_b],
            links=[
                ClaimEvidenceLink(
                    claim_id=claim_a.claim_id,
                    evidence_id=evidence_a.evidence_id,
                    support_type=EvidenceSupportType.DIRECT,
                    rationale="原文直接支持。",
                ),
                ClaimEvidenceLink(
                    claim_id=claim_b.claim_id,
                    evidence_id=evidence_b.evidence_id,
                    support_type=EvidenceSupportType.DIRECT,
                    rationale="原文直接支持。",
                ),
            ],
        )

        result = await EvidenceRepository(session).add_bundle(owner, job_id, bundle)
        rows = await EvidenceRepository(session).list_for_job(owner, job_id)
        claims = list(
            await session.scalars(
                select(ClaimRecordRow).where(ClaimRecordRow.job_id == job_id)
            )
        )
        links = list(await session.scalars(select(ClaimEvidenceLinkRecord)))

        assert len(rows) == 1
        assert set(result.evidence_id_map) == {"evidence-a", "evidence-b"}
        assert set(result.evidence_id_map.values()) == {rows[0].id}
        assert len(claims) == 2
        assert len(links) == 2
        assert rows[0].accessed_at == evidence_a.accessed_at.replace(tzinfo=None)
        assert rows[0].content_hash == evidence_a.content_hash
        assert len(rows[0].supporting_excerpt) <= 1_500
        assert "企业上线了首单任务" in rows[0].supporting_excerpt
        assert "首单任务使用优惠券激励" in rows[0].supporting_excerpt
        assert "FULL_PAGE_SENTINEL" not in rows[0].supporting_excerpt
        assert "FULL_PAGE_SENTINEL" not in rows[0].context_summary
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_report_versions_are_append_only_and_cannot_be_overwritten() -> None:
    engine, session, owner, _ = await _database()
    try:
        _, revision_id, job_id = await _seed_brief_and_job(session, owner)
        repository = ReportVersionRepository(session)
        await repository.add_version(
            owner,
            job_id,
            revision_id,
            1,
            "formal",
            {"title": "第一版"},
            {"retention": "1.0.0"},
            {"provider": "test"},
        )

        with pytest.raises(VersionConflict, match="immutable"):
            await repository.add_version(
                owner,
                job_id,
                revision_id,
                1,
                "formal",
                {"title": "试图覆盖第一版"},
                {"retention": "1.0.0"},
                {"provider": "test"},
            )

        versions = await repository.list_for_job(owner, job_id)
        assert len(versions) == 1
        assert versions[0].report_payload["title"] == "第一版"
    finally:
        await session.close()
        await engine.dispose()
