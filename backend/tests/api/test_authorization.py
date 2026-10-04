"""Authentication and owner-isolation tests for protected API resources."""

from datetime import UTC, datetime

import pytest
from ops_agent.persistence.models import (
    BriefRevisionRecord,
    EvidenceRecordRow,
    ExportFileRecord,
    OperationsBriefRecord,
    ReportJobRecord,
    ReportVersionRecord,
)

from api.support import ApiTestContext, api_test_context, register_and_login


async def _seed_all_resource_types(
    context: ApiTestContext, owner_id: str
) -> dict[str, str]:
    async with context.session_factory() as session:
        brief = OperationsBriefRecord(owner_id=owner_id, latest_revision_number=1)
        session.add(brief)
        await session.flush()
        revision = BriefRevisionRecord(
            brief_id=brief.id,
            owner_id=owner_id,
            revision_number=1,
            brief_payload={"operation_goal": "提高留存"},
            classification_payload={"primary_scene": "retention"},
        )
        session.add(revision)
        await session.flush()
        job = ReportJobRecord(
            owner_id=owner_id,
            brief_id=brief.id,
            brief_revision_id=revision.id,
            idempotency_key="authorization-seed",
        )
        session.add(job)
        await session.flush()
        evidence = EvidenceRecordRow(
            owner_id=owner_id,
            job_id=job.id,
            normalized_url="https://example.com/case",
            title="公开案例",
            publisher="示例企业",
            source_type="official_primary",
            publication_date=None,
            publication_date_unknown=True,
            accessed_at=datetime.now(UTC),
            supporting_excerpt="公开片段",
            context_summary="公开上下文",
            content_hash="a" * 64,
            credibility_payload={"level": "high"},
            adaptation_payload=[],
        )
        session.add(evidence)
        report = ReportVersionRecord(
            owner_id=owner_id,
            job_id=job.id,
            brief_revision_id=revision.id,
            version_number=1,
            delivery_status="directional_draft",
            report_payload={"title": "留存方案"},
            playbook_versions={"retention": "1.0.0"},
            model_configuration={"provider": "test"},
        )
        session.add(report)
        await session.flush()
        export = ExportFileRecord(
            owner_id=owner_id,
            report_version_id=report.id,
            format="markdown",
            storage_key=f"reports/{report.id}.md",
            checksum_sha256="b" * 64,
            size_bytes=128,
            content_type="text/markdown",
        )
        session.add(export)
        await session.commit()
        return {
            "briefs": brief.id,
            "jobs": job.id,
            "evidence": evidence.id,
            "reports": report.id,
            "exports": export.id,
        }


@pytest.mark.asyncio
async def test_protected_resources_require_authentication() -> None:
    async with api_test_context() as context:
        for resource_type in ("briefs", "jobs", "evidence", "reports", "exports"):
            response = await context.client.get(f"/api/v1/{resource_type}/missing")
            assert response.status_code == 401
            assert response.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_owner_can_read_all_resources_but_cross_user_cannot_probe_them() -> None:
    async with api_test_context() as context:
        owner = await register_and_login(context.client, email="owner@example.com")
        resource_ids = await _seed_all_resource_types(context, owner["id"])

        for resource_type, resource_id in resource_ids.items():
            response = await context.client.get(f"/api/v1/{resource_type}/{resource_id}")
            assert response.status_code == 200
            assert response.json()["id"] == resource_id

        await context.client.post("/api/v1/auth/logout")
        await register_and_login(context.client, email="stranger@example.com")

        for resource_type, resource_id in resource_ids.items():
            denied = await context.client.get(f"/api/v1/{resource_type}/{resource_id}")
            absent = await context.client.get(f"/api/v1/{resource_type}/missing")
            assert denied.status_code == 404
            assert absent.status_code == 404
            assert denied.json() == absent.json()
            assert denied.json()["detail"]["code"] == "RESOURCE_NOT_FOUND"
