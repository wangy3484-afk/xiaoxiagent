"""Report export creation, integrity, expiry, and owner-isolation tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from domain.test_report_models import _valid_report
from ops_agent.persistence.models import (
    BriefRevisionRecord,
    ExportFileRecord,
    OperationsBriefRecord,
    ReportJobRecord,
    ReportVersionRecord,
)

from api.support import ApiTestContext, api_test_context, register_and_login


async def _seed_exportable_report(
    context: ApiTestContext,
    owner_id: str,
) -> str:
    async with context.session_factory() as session:
        brief = OperationsBriefRecord(
            owner_id=owner_id,
            status="confirmed",
            latest_revision_number=1,
        )
        session.add(brief)
        await session.flush()
        revision = BriefRevisionRecord(
            brief_id=brief.id,
            owner_id=owner_id,
            revision_number=1,
            brief_payload={"operation_goal": "提高次月留存"},
            classification_payload={"primary_scene": "retention"},
            is_confirmed=True,
        )
        session.add(revision)
        await session.flush()
        job = ReportJobRecord(
            owner_id=owner_id,
            brief_id=brief.id,
            brief_revision_id=revision.id,
            idempotency_key=f"export-source-{owner_id}",
            status="completed",
            stage="finalize",
        )
        session.add(job)
        await session.flush()
        report = ReportVersionRecord(
            owner_id=owner_id,
            job_id=job.id,
            brief_revision_id=revision.id,
            version_number=1,
            delivery_status="directional_draft",
            report_payload=_valid_report().model_dump(mode="json"),
            playbook_versions={"retention": "1.0.0"},
            model_configuration={"provider": "test"},
        )
        session.add(report)
        await session.commit()
        return report.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("export_format", "content_type", "prefix"),
    [
        ("markdown", "text/markdown", b"# "),
        ("pdf", "application/pdf", b"%PDF-"),
    ],
)
async def test_export_creation_download_checksum_and_idempotency(
    export_format: str,
    content_type: str,
    prefix: bytes,
) -> None:
    async with api_test_context() as context:
        identity = await register_and_login(context.client)
        report_id = await _seed_exportable_report(context, identity["id"])
        headers = {"Idempotency-Key": f"export-{export_format}"}
        payload = {"format": export_format, "temporary": False}

        created = await context.client.post(
            f"/api/v1/reports/{report_id}/exports",
            json=payload,
            headers=headers,
        )
        replay = await context.client.post(
            f"/api/v1/reports/{report_id}/exports",
            json=payload,
            headers=headers,
        )

        assert created.status_code == replay.status_code == 201
        assert replay.json() == created.json()
        assert replay.headers["Idempotency-Replayed"] == "true"
        export = created.json()
        downloaded = await context.client.get(export["download_url"])
        assert downloaded.status_code == 200
        assert downloaded.content.startswith(prefix)
        assert downloaded.headers["content-type"].startswith(content_type)
        digest = hashlib.sha256(downloaded.content).hexdigest()
        assert digest == export["checksum_sha256"]
        assert digest == downloaded.headers["x-checksum-sha256"]
        assert int(downloaded.headers["content-length"]) == export["size_bytes"]
        async with context.session_factory() as session:
            row = await session.get(ExportFileRecord, export["id"])
            assert row is not None
            assert row.checksum_sha256 == digest
            assert row.size_bytes == len(downloaded.content)


@pytest.mark.asyncio
async def test_export_requires_login_and_hides_cross_user_resources() -> None:
    async with api_test_context() as context:
        owner = await register_and_login(context.client, email="export-owner@example.com")
        report_id = await _seed_exportable_report(context, owner["id"])
        created = await context.client.post(
            f"/api/v1/reports/{report_id}/exports",
            json={"format": "markdown"},
            headers={"Idempotency-Key": "private-export"},
        )
        export_id = created.json()["id"]
        await context.client.post("/api/v1/auth/logout")

        unauthenticated = await context.client.get(
            f"/api/v1/exports/{export_id}/download"
        )
        assert unauthenticated.status_code == 401

        await register_and_login(context.client, email="export-stranger@example.com")
        cross_user_create = await context.client.post(
            f"/api/v1/reports/{report_id}/exports",
            json={"format": "pdf"},
            headers={"Idempotency-Key": "cross-user-export"},
        )
        cross_user_download = await context.client.get(
            f"/api/v1/exports/{export_id}/download"
        )
        missing_download = await context.client.get(
            "/api/v1/exports/missing/download"
        )

        assert cross_user_create.status_code == 404
        assert cross_user_download.status_code == 404
        assert cross_user_download.json() == missing_download.json()


@pytest.mark.asyncio
async def test_expired_temporary_export_is_not_downloadable() -> None:
    async with api_test_context() as context:
        identity = await register_and_login(context.client)
        report_id = await _seed_exportable_report(context, identity["id"])
        created = await context.client.post(
            f"/api/v1/reports/{report_id}/exports",
            json={"format": "markdown", "temporary": True},
            headers={"Idempotency-Key": "expiring-export"},
        )
        export_id = created.json()["id"]
        async with context.session_factory() as session:
            row = await session.get(ExportFileRecord, export_id)
            assert row is not None
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

        expired = await context.client.get(
            f"/api/v1/exports/{export_id}/download"
        )

        assert expired.status_code == 404
        assert expired.json()["detail"]["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_download_rejects_database_to_file_checksum_mismatch() -> None:
    async with api_test_context() as context:
        identity = await register_and_login(context.client)
        report_id = await _seed_exportable_report(context, identity["id"])
        created = await context.client.post(
            f"/api/v1/reports/{report_id}/exports",
            json={"format": "markdown"},
            headers={"Idempotency-Key": "checksum-mismatch-export"},
        )
        export_id = created.json()["id"]
        async with context.session_factory() as session:
            row = await session.get(ExportFileRecord, export_id)
            assert row is not None
            row.checksum_sha256 = "0" * 64
            await session.commit()

        response = await context.client.get(
            f"/api/v1/exports/{export_id}/download"
        )

        assert response.status_code == 500
        assert response.json()["detail"]["code"] == "EXPORT_INTEGRITY_CHECK_FAILED"
