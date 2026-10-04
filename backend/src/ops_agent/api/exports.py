"""Authorized deterministic report export creation and download APIs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from ops_agent.api.dependencies import (
    CurrentSubject,
    DatabaseSession,
    RequestArtifactStorage,
    RequestSettings,
)
from ops_agent.artifacts import (
    ArtifactCorruptedError,
    ArtifactNotFoundError,
    BrandAssetError,
    ReportBranding,
    render_operations_report_markdown,
    render_operations_report_pdf,
)
from ops_agent.auth.authorization import ResourceAuthorizationPolicy
from ops_agent.domain.report import OperationsReport
from ops_agent.persistence.idempotency import (
    IdempotencyConflict,
    IdempotencyInProgress,
    IdempotencyService,
)
from ops_agent.persistence.models import ExportFileRecord
from ops_agent.persistence.repositories import ResourceNotFound

router = APIRouter(tags=["report exports"])


class ExportCreateRequest(BaseModel):
    format: Literal["pdf", "markdown"]
    temporary: bool = False


class ExportCreateResponse(BaseModel):
    id: str
    report_version_id: str
    format: Literal["pdf", "markdown"]
    content_type: str
    size_bytes: int
    checksum_sha256: str
    temporary: bool
    expires_at: datetime | None
    download_url: str
    created_at: datetime


def _resource_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "RESOURCE_NOT_FOUND",
            "message": "资源不存在、已过期或当前账号无权访问。",
        },
    )


@router.post(
    "/api/v1/reports/{report_version_id}/exports",
    response_model=ExportCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_report_export(
    report_version_id: str,
    payload: ExportCreateRequest,
    response: Response,
    session: DatabaseSession,
    subject: CurrentSubject,
    settings: RequestSettings,
    storage: RequestArtifactStorage,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
) -> ExportCreateResponse:
    try:
        report_record = await ResourceAuthorizationPolicy(session).require_report(
            subject, report_version_id
        )
    except ResourceNotFound as exc:
        raise _resource_not_found() from exc

    idempotency = IdempotencyService(session)
    try:
        reservation = await idempotency.reserve(
            subject,
            scope=f"POST:/api/v1/reports/{report_version_id}/exports",
            key=idempotency_key,
            request_payload=payload.model_dump(mode="json"),
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_CONFLICT",
                "message": "该幂等键已用于不同的导出请求。",
            },
        ) from exc
    except IdempotencyInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                "message": "相同导出正在生成，请稍后重试。",
            },
        ) from exc

    if not reservation.is_new:
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = reservation.record.response_status or status.HTTP_201_CREATED
        return ExportCreateResponse.model_validate(reservation.response_payload)

    try:
        report = OperationsReport.model_validate(report_record.report_payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REPORT_NOT_EXPORTABLE",
                "message": "报告结构不完整，暂时无法导出。",
            },
        ) from exc

    branding = ReportBranding(
        title=settings.report_brand_title,
        header_text=settings.report_brand_header,
        logo_path=settings.report_brand_logo_path,
    )
    try:
        content, extension, content_type = await run_in_threadpool(
            _render_export, report, payload.format, branding
        )
    except BrandAssetError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "REPORT_BRAND_CONFIGURATION_INVALID",
                "message": "报告品牌素材配置无效，请联系管理员。",
            },
        ) from exc
    export_id = str(uuid4())
    storage_key = (
        f"exports/{subject.user_id}/{report_version_id}/{export_id}.{extension}"
    )
    try:
        artifact_metadata = await run_in_threadpool(
            storage.write,
            subject,
            storage_key,
            content,
            content_type=content_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "EXPORT_STORAGE_UNAVAILABLE",
                "message": "导出文件暂时无法保存，请稍后重试。",
            },
        ) from exc

    expires_at = (
        datetime.now(UTC) + timedelta(days=settings.temporary_artifact_retention_days)
        if payload.temporary
        else None
    )
    row = ExportFileRecord(
        id=export_id,
        owner_id=subject.user_id,
        report_version_id=report_version_id,
        format=payload.format,
        storage_key=storage_key,
        checksum_sha256=artifact_metadata.checksum_sha256,
        size_bytes=artifact_metadata.size_bytes,
        content_type=content_type,
        is_temporary=payload.temporary,
        expires_at=expires_at,
    )
    try:
        session.add(row)
        await session.flush()
    except Exception:
        await run_in_threadpool(storage.delete, subject, storage_key)
        raise

    result = ExportCreateResponse(
        id=row.id,
        report_version_id=row.report_version_id,
        format=payload.format,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        checksum_sha256=row.checksum_sha256,
        temporary=row.is_temporary,
        expires_at=row.expires_at,
        download_url=f"/api/v1/exports/{row.id}/download",
        created_at=row.created_at,
    )
    await idempotency.complete(
        reservation,
        resource_type="export_file",
        resource_id=row.id,
        response_status=status.HTTP_201_CREATED,
        response_payload=result.model_dump(mode="json"),
    )
    return result


@router.get("/api/v1/exports/{export_id}/download")
async def download_report_export(
    export_id: str,
    session: DatabaseSession,
    subject: CurrentSubject,
    storage: RequestArtifactStorage,
) -> Response:
    try:
        row = await ResourceAuthorizationPolicy(session).require_export(subject, export_id)
    except ResourceNotFound as exc:
        raise _resource_not_found() from exc

    try:
        metadata, content = await run_in_threadpool(
            storage.read, subject, row.storage_key
        )
    except ArtifactNotFoundError as exc:
        raise _resource_not_found() from exc
    except ArtifactCorruptedError as exc:
        raise _integrity_error() from exc

    if (
        metadata.checksum_sha256 != row.checksum_sha256
        or metadata.size_bytes != row.size_bytes
        or metadata.content_type != row.content_type
    ):
        raise _integrity_error()

    extension = "pdf" if row.format == "pdf" else "md"
    filename = f"operations-report-{row.report_version_id}.{extension}"
    encoded_filename = quote(filename, safe="")
    return Response(
        content=content,
        media_type=row.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="report.{extension}"; '
                f"filename*=UTF-8''{encoded_filename}"
            ),
            "Content-Length": str(row.size_bytes),
            "X-Checksum-SHA256": row.checksum_sha256,
            "ETag": f'"{row.checksum_sha256}"',
            "Cache-Control": "private, no-store",
        },
    )


def _render_export(
    report: OperationsReport,
    export_format: Literal["pdf", "markdown"],
    branding: ReportBranding,
) -> tuple[bytes, str, str]:
    if export_format == "pdf":
        return (
            render_operations_report_pdf(report, branding=branding),
            "pdf",
            "application/pdf",
        )
    markdown = render_operations_report_markdown(
        report, branding=branding
    ).encode("utf-8")
    return markdown, "md", "text/markdown; charset=utf-8"


def _integrity_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "code": "EXPORT_INTEGRITY_CHECK_FAILED",
            "message": "导出文件校验失败，请重新生成。",
        },
    )
