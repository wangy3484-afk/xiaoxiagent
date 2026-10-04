"""Protected metadata endpoints demonstrating resource-level authorization."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ops_agent.api.dependencies import CurrentSubject, DatabaseSession
from ops_agent.auth.authorization import ResourceAuthorizationPolicy
from ops_agent.persistence.idempotency import (
    IdempotencyConflict,
    IdempotencyInProgress,
    IdempotencyService,
)
from ops_agent.persistence.models import (
    EvidenceRecordRow,
    ExportFileRecord,
    OperationsBriefRecord,
    ReportJobRecord,
    ReportVersionRecord,
)
from ops_agent.persistence.repositories import BriefRepository, ResourceNotFound

router = APIRouter(prefix="/api/v1", tags=["protected resources"])


class BriefResourceResponse(BaseModel):
    id: str
    status: str
    latest_revision_number: int


class JobResourceResponse(BaseModel):
    id: str
    brief_id: str
    brief_revision_id: str
    status: str
    stage: str
    progress_percent: int
    error_code: str | None = None
    error_message: str | None = None
    report_version_ids: list[str] = Field(default_factory=list)


class EvidenceResourceResponse(BaseModel):
    id: str
    title: str
    publisher: str


class ExportResourceResponse(BaseModel):
    id: str
    format: str
    content_type: str
    size_bytes: int
    created_at: datetime


class BriefCreateRequest(BaseModel):
    brief_payload: dict[str, Any] = Field(min_length=1)
    classification_payload: dict[str, Any] = Field(min_length=1)


class BriefCreateResponse(BaseModel):
    id: str
    revision_id: str
    latest_revision_number: int
    status: str


def _resource_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "RESOURCE_NOT_FOUND",
            "message": "资源不存在或当前账号无权访问。",
        },
    )


async def _authorized[ResourceT](call: Callable[[], Awaitable[ResourceT]]) -> ResourceT:
    try:
        return await call()
    except ResourceNotFound as exc:
        raise _resource_not_found() from exc


@router.post(
    "/briefs",
    response_model=BriefCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_brief(
    payload: BriefCreateRequest,
    response: Response,
    session: DatabaseSession,
    subject: CurrentSubject,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
) -> BriefCreateResponse:
    idempotency = IdempotencyService(session)
    try:
        reservation = await idempotency.reserve(
            subject,
            scope="POST:/api/v1/briefs",
            key=idempotency_key,
            request_payload=payload.model_dump(mode="json"),
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_CONFLICT",
                "message": "该幂等键已用于不同的请求内容。",
            },
        ) from exc
    except IdempotencyInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                "message": "相同请求正在处理中，请稍后重试。",
            },
        ) from exc

    if not reservation.is_new:
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = reservation.record.response_status or status.HTTP_201_CREATED
        return BriefCreateResponse.model_validate(reservation.response_payload)

    brief, revision = await BriefRepository(session).create(
        subject,
        brief_payload=payload.brief_payload,
        classification_payload=payload.classification_payload,
    )
    result = BriefCreateResponse(
        id=brief.id,
        revision_id=revision.id,
        latest_revision_number=brief.latest_revision_number,
        status=brief.status,
    )
    await idempotency.complete(
        reservation,
        resource_type="operations_brief",
        resource_id=brief.id,
        response_status=status.HTTP_201_CREATED,
        response_payload=result.model_dump(mode="json"),
    )
    return result


@router.get("/briefs/{brief_id}", response_model=BriefResourceResponse)
async def get_brief(
    brief_id: str,
    session: DatabaseSession,
    subject: CurrentSubject,
) -> BriefResourceResponse:
    row: OperationsBriefRecord = await _authorized(
        lambda: ResourceAuthorizationPolicy(session).require_brief(subject, brief_id)
    )
    return BriefResourceResponse(
        id=row.id,
        status=row.status,
        latest_revision_number=row.latest_revision_number,
    )


@router.get("/jobs/{job_id}", response_model=JobResourceResponse)
async def get_job(
    job_id: str,
    session: DatabaseSession,
    subject: CurrentSubject,
) -> JobResourceResponse:
    row: ReportJobRecord = await _authorized(
        lambda: ResourceAuthorizationPolicy(session).require_job(subject, job_id)
    )
    versions = await session.scalars(
        select(ReportVersionRecord)
        .where(
            ReportVersionRecord.job_id == row.id,
            ReportVersionRecord.owner_id == subject.user_id,
        )
        .order_by(ReportVersionRecord.version_number)
    )
    return JobResourceResponse(
        id=row.id,
        brief_id=row.brief_id,
        brief_revision_id=row.brief_revision_id,
        status=row.status,
        stage=row.stage,
        progress_percent=_job_progress(row.status, row.stage),
        error_code=row.error_code,
        error_message=row.error_message,
        report_version_ids=[version.id for version in versions],
    )


def _job_progress(job_status: str, stage: str) -> int:
    if job_status == "completed":
        return 100
    stage_progress = {
        "queued": 0,
        "initializing": 5,
        "load_context": 10,
        "research": 25,
        "diagnosis": 40,
        "strategy": 55,
        "planning": 70,
        "assembly": 82,
        "quality": 92,
        "finalize": 98,
    }
    return stage_progress.get(stage, 0)


@router.get("/evidence/{evidence_id}", response_model=EvidenceResourceResponse)
async def get_evidence(
    evidence_id: str,
    session: DatabaseSession,
    subject: CurrentSubject,
) -> EvidenceResourceResponse:
    row: EvidenceRecordRow = await _authorized(
        lambda: ResourceAuthorizationPolicy(session).require_evidence(subject, evidence_id)
    )
    return EvidenceResourceResponse(id=row.id, title=row.title, publisher=row.publisher)


@router.get("/exports/{export_id}", response_model=ExportResourceResponse)
async def get_export(
    export_id: str,
    session: DatabaseSession,
    subject: CurrentSubject,
) -> ExportResourceResponse:
    row: ExportFileRecord = await _authorized(
        lambda: ResourceAuthorizationPolicy(session).require_export(subject, export_id)
    )
    return ExportResourceResponse(
        id=row.id,
        format=row.format,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
    )
