"""Report-job creation, status-event, and queue handoff APIs."""

from hashlib import sha256
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from ops_agent.api.dependencies import CurrentSubject, DatabaseSession, RequestJobQueue
from ops_agent.observability import current_request_id, log_event
from ops_agent.persistence.idempotency import (
    IdempotencyConflict,
    IdempotencyInProgress,
    IdempotencyReservation,
    IdempotencyService,
)
from ops_agent.persistence.models import JobEventRecord
from ops_agent.persistence.repositories import (
    AuthorizationSubject,
    BriefNotConfirmed,
    ReportJobRepository,
    ResourceNotFound,
)
from ops_agent.queueing import JobQueue

router = APIRouter(prefix="/api/v1/jobs", tags=["report jobs"])


class ReportJobCreateRequest(BaseModel):
    brief_id: str
    brief_revision_id: str


class ReportJobCreateResponse(BaseModel):
    id: str
    status: str
    stage: str
    source_report_version_id: str | None = None
    target_version_number: int = 1


class JobEventSummary(BaseModel):
    sequence: int
    event_type: str
    stage: str | None = None
    status: str | None = None
    message: str | None = None
    error_code: str | None = None


class JobEventListResponse(BaseModel):
    job_id: str
    events: list[JobEventSummary]


def scoped_job_idempotency_key(scope: str, key: str) -> str:
    """Keep the legacy job uniqueness constraint isolated by API operation."""
    return sha256(f"{scope}\0{key}".encode()).hexdigest()


def _idempotency_error(error: Exception) -> HTTPException:
    if isinstance(error, IdempotencyConflict):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_CONFLICT",
                "message": "该幂等键已用于不同的请求内容。",
            },
        )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "IDEMPOTENCY_REQUEST_IN_PROGRESS",
            "message": "相同请求正在处理中，请稍后重试。",
        },
    )


async def create_and_enqueue_report_job(
    *,
    payload: ReportJobCreateRequest,
    response: Response,
    session: DatabaseSession,
    subject: AuthorizationSubject,
    queue: JobQueue,
    idempotency_key: str,
    scope: str,
    source_report_version_id: str | None = None,
    target_version_number: int = 1,
) -> ReportJobCreateResponse:
    """Create one durable job and publish it once for an idempotent API request."""
    idempotency = IdempotencyService(session)
    request_payload: dict[str, Any] = {
        **payload.model_dump(mode="json"),
        "source_report_version_id": source_report_version_id,
    }
    try:
        reservation = await idempotency.reserve(
            subject,
            scope=scope,
            key=idempotency_key,
            request_payload=request_payload,
        )
    except (IdempotencyConflict, IdempotencyInProgress) as exc:
        raise _idempotency_error(exc) from exc

    if not reservation.is_new:
        return _replay_job_response(response, reservation)

    try:
        job = await ReportJobRepository(session).create(
            subject,
            brief_id=payload.brief_id,
            brief_revision_id=payload.brief_revision_id,
            idempotency_key=scoped_job_idempotency_key(scope, idempotency_key),
            source_report_version_id=source_report_version_id,
            request_id=current_request_id(),
        )
    except ResourceNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "简报或来源报告不存在，或当前账号无权访问。",
            },
        ) from exc
    except BriefNotConfirmed as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BRIEF_NOT_CONFIRMED",
                "message": "只能基于最新且已确认的简报创建报告任务。",
            },
        ) from exc

    result = ReportJobCreateResponse(
        id=job.id,
        status=job.status,
        stage=job.stage,
        source_report_version_id=source_report_version_id,
        target_version_number=target_version_number,
    )
    # The worker may consume immediately, so both job and reservation must be visible.
    await session.commit()
    try:
        await queue.enqueue(job.id)
    except Exception as exc:
        await session.refresh(job)
        job.status = "failed"
        job.stage = "queue_error"
        job.error_code = "JOB_QUEUE_UNAVAILABLE"
        job.error_message = "任务队列暂时不可用，请稍后使用新的请求重试。"
        failure_payload = {
            "detail": {
                "code": job.error_code,
                "message": job.error_message,
            }
        }
        await idempotency.complete(
            reservation,
            resource_type="report_job",
            resource_id=job.id,
            response_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            response_payload=failure_payload,
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=failure_payload["detail"],
        ) from exc

    log_event("report_job_enqueued", job_id=job.id)

    await idempotency.complete(
        reservation,
        resource_type="report_job",
        resource_id=job.id,
        response_status=status.HTTP_202_ACCEPTED,
        response_payload=result.model_dump(mode="json"),
    )
    await session.commit()
    return result


def _replay_job_response(
    response: Response,
    reservation: IdempotencyReservation,
) -> ReportJobCreateResponse:
    response.headers["Idempotency-Replayed"] = "true"
    response_status = reservation.record.response_status or status.HTTP_202_ACCEPTED
    if response_status >= 400:
        detail = reservation.response_payload.get("detail", {})
        raise HTTPException(status_code=response_status, detail=detail)
    response.status_code = response_status
    return ReportJobCreateResponse.model_validate(reservation.response_payload)


@router.post(
    "",
    response_model=ReportJobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_report_job(
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
    return await create_and_enqueue_report_job(
        payload=payload,
        response=response,
        session=session,
        subject=subject,
        queue=queue,
        idempotency_key=idempotency_key,
        scope="POST:/api/v1/jobs",
    )


@router.get("/{job_id}/events", response_model=JobEventListResponse)
async def list_job_events(
    job_id: str,
    session: DatabaseSession,
    subject: CurrentSubject,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JobEventListResponse:
    job = await ReportJobRepository(session).get(subject, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "任务不存在或当前账号无权访问。",
            },
        )
    rows = list(
        await session.scalars(
            select(JobEventRecord)
            .where(JobEventRecord.job_id == job_id)
            .order_by(JobEventRecord.sequence.desc())
            .limit(limit)
        )
    )
    rows.reverse()
    return JobEventListResponse(
        job_id=job_id,
        events=[_summarize_event(row) for row in rows],
    )


def _summarize_event(row: JobEventRecord) -> JobEventSummary:
    payload = row.event_payload
    return JobEventSummary(
        sequence=row.sequence,
        event_type=row.event_type,
        stage=_optional_string(payload.get("stage")),
        status=_optional_string(payload.get("status")),
        message=_optional_string(payload.get("message")),
        error_code=_optional_string(payload.get("error_code")),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
