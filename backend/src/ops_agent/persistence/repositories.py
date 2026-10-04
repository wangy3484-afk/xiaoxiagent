"""Owner-scoped repositories for business state and immutable report versions."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ops_agent.domain.research import EvidenceBundle, EvidenceRecord
from ops_agent.persistence.models import (
    BriefRevisionRecord,
    ClaimEvidenceLinkRecord,
    ClaimRecordRow,
    EvidenceRecordRow,
    ExportFileRecord,
    OperationsBriefRecord,
    QualityReviewRecord,
    ReportJobRecord,
    ReportVersionRecord,
)


@dataclass(frozen=True)
class AuthorizationSubject:
    user_id: str


class RepositoryError(RuntimeError):
    pass


class ResourceNotFound(RepositoryError):
    """Used for missing and unauthorized records to avoid existence leakage."""


class VersionConflict(RepositoryError):
    pass


class InvalidStateTransition(RepositoryError):
    pass


class BriefNotConfirmed(RepositoryError):
    pass


@dataclass(frozen=True)
class EvidenceBundlePersistenceResult:
    evidence_id_map: dict[str, str]
    claim_ids: list[str]
    link_count: int


class BriefRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        subject: AuthorizationSubject,
        brief_payload: dict[str, Any],
        classification_payload: dict[str, Any],
    ) -> tuple[OperationsBriefRecord, BriefRevisionRecord]:
        brief = OperationsBriefRecord(owner_id=subject.user_id, latest_revision_number=1)
        self.session.add(brief)
        await self.session.flush()
        revision = BriefRevisionRecord(
            brief_id=brief.id,
            owner_id=subject.user_id,
            revision_number=1,
            brief_payload=brief_payload,
            classification_payload=classification_payload,
        )
        self.session.add(revision)
        await self.session.flush()
        return brief, revision

    async def get(
        self, subject: AuthorizationSubject, brief_id: str
    ) -> OperationsBriefRecord | None:
        return await self.session.scalar(
            select(OperationsBriefRecord).where(
                OperationsBriefRecord.id == brief_id,
                OperationsBriefRecord.owner_id == subject.user_id,
            )
        )

    async def get_revision(
        self,
        subject: AuthorizationSubject,
        brief_id: str,
        revision_number: int,
    ) -> BriefRevisionRecord | None:
        return await self.session.scalar(
            select(BriefRevisionRecord).where(
                BriefRevisionRecord.brief_id == brief_id,
                BriefRevisionRecord.revision_number == revision_number,
                BriefRevisionRecord.owner_id == subject.user_id,
            )
        )

    async def add_revision(
        self,
        subject: AuthorizationSubject,
        brief_id: str,
        expected_latest_revision: int,
        brief_payload: dict[str, Any],
        classification_payload: dict[str, Any],
    ) -> BriefRevisionRecord:
        brief = await self.get(subject, brief_id)
        if brief is None:
            raise ResourceNotFound("brief not found")
        if brief.status != "draft":
            raise InvalidStateTransition("confirmed briefs cannot be modified")
        if brief.latest_revision_number != expected_latest_revision:
            raise VersionConflict("brief was modified by another request")
        next_revision = expected_latest_revision + 1
        revision = BriefRevisionRecord(
            brief_id=brief.id,
            owner_id=subject.user_id,
            revision_number=next_revision,
            brief_payload=brief_payload,
            classification_payload=classification_payload,
        )
        try:
            async with self.session.begin_nested():
                brief.latest_revision_number = next_revision
                self.session.add(revision)
                await self.session.flush()
        except IntegrityError as exc:
            raise VersionConflict("brief was modified by another request") from exc
        return revision

    async def get_latest_revision(
        self,
        subject: AuthorizationSubject,
        brief_id: str,
    ) -> BriefRevisionRecord | None:
        brief = await self.get(subject, brief_id)
        if brief is None:
            return None
        return await self.get_revision(subject, brief_id, brief.latest_revision_number)

    async def confirm_revision(
        self,
        subject: AuthorizationSubject,
        brief_id: str,
        expected_revision: int,
    ) -> BriefRevisionRecord:
        brief = await self.get(subject, brief_id)
        if brief is None:
            raise ResourceNotFound("brief not found")
        if brief.latest_revision_number != expected_revision:
            raise VersionConflict("brief was modified by another request")
        revision = await self.get_revision(subject, brief_id, expected_revision)
        if revision is None:
            raise ResourceNotFound("brief revision not found")
        if brief.status == "confirmed":
            if revision.is_confirmed:
                return revision
            raise InvalidStateTransition("brief confirmation state is inconsistent")
        if brief.status != "draft":
            raise InvalidStateTransition("brief cannot be confirmed from its current state")
        revision.is_confirmed = True
        brief.status = "confirmed"
        await self.session.flush()
        return revision


class ReportJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        subject: AuthorizationSubject,
        brief_id: str,
        brief_revision_id: str,
        idempotency_key: str,
        source_report_version_id: str | None = None,
        request_id: str | None = None,
    ) -> ReportJobRecord:
        revision = await self.session.scalar(
            select(BriefRevisionRecord).where(
                BriefRevisionRecord.id == brief_revision_id,
                BriefRevisionRecord.brief_id == brief_id,
                BriefRevisionRecord.owner_id == subject.user_id,
            )
        )
        if revision is None:
            raise ResourceNotFound("brief revision not found")
        brief = await self.session.scalar(
            select(OperationsBriefRecord).where(
                OperationsBriefRecord.id == brief_id,
                OperationsBriefRecord.owner_id == subject.user_id,
            )
        )
        if (
            brief is None
            or brief.status != "confirmed"
            or not revision.is_confirmed
            or brief.latest_revision_number != revision.revision_number
        ):
            raise BriefNotConfirmed(
                "report jobs require the latest confirmed brief revision"
            )
        if source_report_version_id is not None:
            source_report = await self.session.scalar(
                select(ReportVersionRecord).where(
                    ReportVersionRecord.id == source_report_version_id,
                    ReportVersionRecord.owner_id == subject.user_id,
                )
            )
            if source_report is None:
                raise ResourceNotFound("source report version not found")
        job = ReportJobRecord(
            owner_id=subject.user_id,
            brief_id=brief_id,
            brief_revision_id=brief_revision_id,
            source_report_version_id=source_report_version_id,
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(
        self, subject: AuthorizationSubject, job_id: str
    ) -> ReportJobRecord | None:
        return await self.session.scalar(self._authorized_query(subject, job_id))

    @staticmethod
    def _authorized_query(
        subject: AuthorizationSubject, job_id: str
    ) -> Select[ReportJobRecord]:
        return select(ReportJobRecord).where(
            ReportJobRecord.id == job_id,
            ReportJobRecord.owner_id == subject.user_id,
        )


class EvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        subject: AuthorizationSubject,
        job_id: str,
        evidence: EvidenceRecord,
    ) -> EvidenceRecordRow:
        job = await self.session.scalar(ReportJobRepository._authorized_query(subject, job_id))
        if job is None:
            raise ResourceNotFound("report job not found")
        row = EvidenceRecordRow(
            id=evidence.evidence_id,
            owner_id=subject.user_id,
            job_id=job_id,
            normalized_url=str(evidence.url),
            title=evidence.title,
            publisher=evidence.publisher,
            source_type=evidence.source_type.value,
            publication_date=evidence.publication_date,
            publication_date_unknown=evidence.publication_date is None,
            accessed_at=evidence.accessed_at,
            supporting_excerpt=evidence.supporting_excerpt,
            context_summary=evidence.context_summary,
            content_hash=evidence.content_hash,
            credibility_payload=evidence.credibility.model_dump(mode="json"),
            adaptation_payload=[item.model_dump(mode="json") for item in evidence.adaptation],
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def add_bundle(
        self,
        subject: AuthorizationSubject,
        job_id: str,
        bundle: EvidenceBundle,
    ) -> EvidenceBundlePersistenceResult:
        job = await self.session.scalar(ReportJobRepository._authorized_query(subject, job_id))
        if job is None:
            raise ResourceNotFound("report job not found")

        evidence_id_map: dict[str, str] = {}
        for evidence in bundle.evidence:
            row = await self._get_by_normalized_url(
                subject,
                job_id,
                str(evidence.url),
            )
            if row is None:
                row = EvidenceRecordRow(
                    id=evidence.evidence_id,
                    owner_id=subject.user_id,
                    job_id=job_id,
                    normalized_url=str(evidence.url),
                    title=evidence.title,
                    publisher=evidence.publisher,
                    source_type=evidence.source_type.value,
                    publication_date=evidence.publication_date,
                    publication_date_unknown=evidence.publication_date is None,
                    accessed_at=evidence.accessed_at,
                    supporting_excerpt=_bounded_text(evidence.supporting_excerpt),
                    context_summary=_bounded_text(evidence.context_summary),
                    content_hash=evidence.content_hash,
                    credibility_payload=evidence.credibility.model_dump(mode="json"),
                    adaptation_payload=[
                        item.model_dump(mode="json") for item in evidence.adaptation
                    ],
                )
                self.session.add(row)
                await self.session.flush()
            else:
                row.supporting_excerpt = _merge_limited_text(
                    row.supporting_excerpt,
                    evidence.supporting_excerpt,
                )
                row.context_summary = _merge_limited_text(
                    row.context_summary,
                    evidence.context_summary,
                )
            evidence_id_map[evidence.evidence_id] = row.id

        claim_ids: list[str] = []
        for claim in bundle.claims:
            existing_claim = await self.session.scalar(
                select(ClaimRecordRow).where(
                    ClaimRecordRow.id == claim.claim_id,
                    ClaimRecordRow.owner_id == subject.user_id,
                    ClaimRecordRow.job_id == job_id,
                )
            )
            if existing_claim is None:
                self.session.add(
                    ClaimRecordRow(
                        id=claim.claim_id,
                        owner_id=subject.user_id,
                        job_id=job_id,
                        text=claim.text,
                        claim_type=claim.claim_type.value,
                        verification_status=claim.verification_status.value,
                        reasoning=claim.reasoning,
                    )
                )
            claim_ids.append(claim.claim_id)

        link_count = 0
        for link in bundle.links:
            persisted_evidence_id = evidence_id_map.get(link.evidence_id)
            if persisted_evidence_id is None:
                continue
            existing_link = await self.session.scalar(
                select(ClaimEvidenceLinkRecord).where(
                    ClaimEvidenceLinkRecord.claim_id == link.claim_id,
                    ClaimEvidenceLinkRecord.evidence_id == persisted_evidence_id,
                )
            )
            if existing_link is not None:
                continue
            self.session.add(
                ClaimEvidenceLinkRecord(
                    claim_id=link.claim_id,
                    evidence_id=persisted_evidence_id,
                    support_type=link.support_type.value,
                    rationale=link.rationale,
                )
            )
            link_count += 1
        await self.session.flush()
        return EvidenceBundlePersistenceResult(
            evidence_id_map=evidence_id_map,
            claim_ids=claim_ids,
            link_count=link_count,
        )

    async def get(
        self, subject: AuthorizationSubject, evidence_id: str
    ) -> EvidenceRecordRow | None:
        return await self.session.scalar(
            select(EvidenceRecordRow).where(
                EvidenceRecordRow.id == evidence_id,
                EvidenceRecordRow.owner_id == subject.user_id,
            )
        )

    async def list_for_job(
        self, subject: AuthorizationSubject, job_id: str
    ) -> list[EvidenceRecordRow]:
        result = await self.session.scalars(
            select(EvidenceRecordRow)
            .where(
                EvidenceRecordRow.job_id == job_id,
                EvidenceRecordRow.owner_id == subject.user_id,
            )
            .order_by(EvidenceRecordRow.created_at, EvidenceRecordRow.id)
        )
        return list(result)

    async def _get_by_normalized_url(
        self,
        subject: AuthorizationSubject,
        job_id: str,
        normalized_url: str,
    ) -> EvidenceRecordRow | None:
        return await self.session.scalar(
            select(EvidenceRecordRow).where(
                EvidenceRecordRow.job_id == job_id,
                EvidenceRecordRow.owner_id == subject.user_id,
                EvidenceRecordRow.normalized_url == normalized_url,
            )
        )


def _bounded_text(value: str, limit: int = 1_500) -> str:
    stripped = value.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rstrip()


def _merge_limited_text(existing: str, incoming: str, limit: int = 1_500) -> str:
    existing_text = existing.strip()
    incoming_text = incoming.strip()
    if not incoming_text or incoming_text in existing_text:
        return _bounded_text(existing_text, limit)
    if not existing_text:
        return _bounded_text(incoming_text, limit)
    return _bounded_text(f"{existing_text}\n---\n{incoming_text}", limit)


class ReportVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_version(
        self,
        subject: AuthorizationSubject,
        job_id: str,
        brief_revision_id: str,
        version_number: int,
        delivery_status: str,
        report_payload: dict[str, Any],
        playbook_versions: dict[str, str],
        model_configuration: dict[str, Any],
    ) -> ReportVersionRecord:
        job = await self.session.scalar(ReportJobRepository._authorized_query(subject, job_id))
        if job is None or job.brief_revision_id != brief_revision_id:
            raise ResourceNotFound("report job not found")
        row = ReportVersionRecord(
            owner_id=subject.user_id,
            job_id=job_id,
            brief_revision_id=brief_revision_id,
            version_number=version_number,
            delivery_status=delivery_status,
            report_payload=report_payload,
            playbook_versions=playbook_versions,
            model_configuration=model_configuration,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as exc:
            raise VersionConflict(
                "report versions are immutable and cannot be overwritten"
            ) from exc
        return row

    async def get_version(
        self,
        subject: AuthorizationSubject,
        report_version_id: str,
    ) -> ReportVersionRecord | None:
        return await self.session.scalar(
            select(ReportVersionRecord).where(
                ReportVersionRecord.id == report_version_id,
                ReportVersionRecord.owner_id == subject.user_id,
            )
        )

    async def list_for_job(
        self, subject: AuthorizationSubject, job_id: str
    ) -> list[ReportVersionRecord]:
        result = await self.session.scalars(
            select(ReportVersionRecord)
            .where(
                ReportVersionRecord.job_id == job_id,
                ReportVersionRecord.owner_id == subject.user_id,
            )
            .order_by(ReportVersionRecord.version_number)
        )
        return list(result)


class QualityReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        subject: AuthorizationSubject,
        report_version_id: str,
        revision_round: int,
        review_payload: dict[str, Any],
        blocking_issue_count: int,
    ) -> QualityReviewRecord:
        report = await self.session.scalar(
            select(ReportVersionRecord).where(
                ReportVersionRecord.id == report_version_id,
                ReportVersionRecord.owner_id == subject.user_id,
            )
        )
        if report is None:
            raise ResourceNotFound("report version not found")
        review = QualityReviewRecord(
            owner_id=subject.user_id,
            report_version_id=report_version_id,
            revision_round=revision_round,
            review_payload=review_payload,
            blocking_issue_count=blocking_issue_count,
        )
        self.session.add(review)
        await self.session.flush()
        return review

    async def list_for_report(
        self, subject: AuthorizationSubject, report_version_id: str
    ) -> list[QualityReviewRecord]:
        result = await self.session.scalars(
            select(QualityReviewRecord)
            .where(
                QualityReviewRecord.report_version_id == report_version_id,
                QualityReviewRecord.owner_id == subject.user_id,
            )
            .order_by(QualityReviewRecord.revision_round)
        )
        return list(result)


class ExportFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, subject: AuthorizationSubject, export_id: str
    ) -> ExportFileRecord | None:
        now = datetime.now(UTC)
        return await self.session.scalar(
            select(ExportFileRecord).where(
                ExportFileRecord.id == export_id,
                ExportFileRecord.owner_id == subject.user_id,
                ExportFileRecord.deleted_at.is_(None),
                or_(
                    ExportFileRecord.is_temporary.is_(False),
                    ExportFileRecord.expires_at.is_(None),
                    ExportFileRecord.expires_at > now,
                ),
            )
        )
