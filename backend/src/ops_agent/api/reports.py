"""Report history, immutable version reading, and regeneration APIs."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ops_agent.api.dependencies import CurrentSubject, DatabaseSession, RequestJobQueue
from ops_agent.api.jobs import (
    ReportJobCreateRequest,
    ReportJobCreateResponse,
    create_and_enqueue_report_job,
)
from ops_agent.persistence.models import (
    BriefRevisionRecord,
    ReportJobRecord,
    ReportVersionRecord,
)
from ops_agent.persistence.repositories import ReportVersionRepository

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


class ReportVersionSummary(BaseModel):
    report_version_id: str
    series_id: str
    job_id: str
    version_number: int
    title: str
    scene: str
    delivery_status: str
    generated_at: datetime


class ReportHistoryResponse(BaseModel):
    reports: list[ReportVersionSummary] = Field(default_factory=list)


class ReportVersionDetail(ReportVersionSummary):
    id: str
    brief_revision_id: str
    report_payload: dict[str, object]
    available_versions: list[ReportVersionSummary]


@router.get("", response_model=ReportHistoryResponse)
async def list_report_history(
    session: DatabaseSession,
    subject: CurrentSubject,
) -> ReportHistoryResponse:
    entries = await _report_entries(session, subject.user_id)
    return ReportHistoryResponse(reports=entries)


@router.get("/{report_id}", response_model=ReportVersionDetail)
async def get_report_version(
    report_id: str,
    session: DatabaseSession,
    subject: CurrentSubject,
) -> ReportVersionDetail:
    entries = await _report_entries(session, subject.user_id)
    selected = next(
        (entry for entry in entries if entry.report_version_id == report_id),
        None,
    )
    if selected is None:
        raise _report_not_found()
    report = await session.scalar(
        select(ReportVersionRecord).where(
            ReportVersionRecord.id == report_id,
            ReportVersionRecord.owner_id == subject.user_id,
        )
    )
    if report is None:
        raise _report_not_found()
    versions = sorted(
        (entry for entry in entries if entry.series_id == selected.series_id),
        key=lambda entry: entry.version_number,
    )
    return ReportVersionDetail(
        **selected.model_dump(),
        id=selected.report_version_id,
        brief_revision_id=report.brief_revision_id,
        report_payload=report.report_payload,
        available_versions=versions,
    )


async def _report_entries(
    session: DatabaseSession,
    owner_id: str,
) -> list[ReportVersionSummary]:
    rows = (
        await session.execute(
            select(ReportVersionRecord, ReportJobRecord, BriefRevisionRecord)
            .join(ReportJobRecord, ReportVersionRecord.job_id == ReportJobRecord.id)
            .join(
                BriefRevisionRecord,
                ReportVersionRecord.brief_revision_id == BriefRevisionRecord.id,
            )
            .where(ReportVersionRecord.owner_id == owner_id)
            .order_by(ReportVersionRecord.generated_at.desc())
        )
    ).all()
    source_by_report = {
        report.id: job.source_report_version_id for report, job, _revision in rows
    }

    def series_root(report_id: str) -> str:
        current = report_id
        visited: set[str] = set()
        while current not in visited:
            visited.add(current)
            source = source_by_report.get(current)
            if source is None or source not in source_by_report:
                return current if source is None else source
            current = source
        return report_id

    entries: list[ReportVersionSummary] = []
    for report, job, revision in rows:
        title = report.report_payload.get("title")
        classification = revision.classification_payload
        scene = classification.get("primary_scene")
        entries.append(
            ReportVersionSummary(
                report_version_id=report.id,
                series_id=series_root(report.id),
                job_id=job.id,
                version_number=report.version_number,
                title=title if isinstance(title, str) else "未命名运营报告",
                scene=scene if isinstance(scene, str) else "unknown",
                delivery_status=report.delivery_status,
                generated_at=report.generated_at,
            )
        )
    return entries


def _report_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "RESOURCE_NOT_FOUND",
            "message": "报告不存在或当前账号无权访问。",
        },
    )


@router.post(
    "/{report_version_id}/regenerate",
    response_model=ReportJobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def regenerate_report(
    report_version_id: str,
    payload: ReportJobCreateRequest,
    response: Response,
    session: DatabaseSession,
    subject: CurrentSubject,
    queue: RequestJobQueue,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
) -> ReportJobCreateResponse:
    """Start the next immutable version from a newly confirmed brief revision."""
    source = await ReportVersionRepository(session).get_version(
        subject,
        report_version_id,
    )
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "来源报告不存在或当前账号无权访问。",
            },
        )
    if source.brief_revision_id == payload.brief_revision_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BRIEF_REVISION_UNCHANGED",
                "message": "重新生成需要选择新的已确认运营简报。",
            },
        )
    return await create_and_enqueue_report_job(
        payload=payload,
        response=response,
        session=session,
        subject=subject,
        queue=queue,
        idempotency_key=idempotency_key,
        scope=f"POST:/api/v1/reports/{report_version_id}/regenerate",
        source_report_version_id=source.id,
        target_version_number=source.version_number + 1,
    )
