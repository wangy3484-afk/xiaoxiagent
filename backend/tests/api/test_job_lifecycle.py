"""Report-job lifecycle, event-summary, and regeneration API tests."""

import pytest
from ops_agent.persistence.job_state import JobStatus, ReportJobStateMachine
from ops_agent.persistence.models import ReportJobRecord, ReportVersionRecord
from ops_agent.persistence.repositories import (
    AuthorizationSubject,
    BriefRepository,
    ReportJobRepository,
    ReportVersionRepository,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.support import ApiTestContext, api_test_context, register_and_login


class RecordingJobQueue:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    async def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


async def _confirmed_brief(
    context: ApiTestContext,
    subject: AuthorizationSubject,
    *,
    goal: str,
) -> tuple[str, str]:
    async with context.session_factory() as session:
        brief, revision = await BriefRepository(session).create(
            subject,
            brief_payload={"operation_goal": goal, "target_users": "新注册用户"},
            classification_payload={"primary_scene": "retention"},
        )
        await BriefRepository(session).confirm_revision(
            subject,
            brief.id,
            expected_revision=revision.revision_number,
        )
        await session.commit()
        return brief.id, revision.id


async def _source_report(
    session: AsyncSession,
    subject: AuthorizationSubject,
    *,
    brief_id: str,
    revision_id: str,
) -> ReportVersionRecord:
    job = await ReportJobRepository(session).create(
        subject,
        brief_id=brief_id,
        brief_revision_id=revision_id,
        idempotency_key="source-report-job",
    )
    report = await ReportVersionRepository(session).add_version(
        subject,
        job_id=job.id,
        brief_revision_id=revision_id,
        version_number=1,
        delivery_status="formal",
        report_payload={"title": "初版留存方案"},
        playbook_versions={"core": "1.0.0"},
        model_configuration={"model": "test"},
    )
    await session.commit()
    return report


@pytest.mark.asyncio
async def test_job_creation_is_idempotent_and_enqueues_once() -> None:
    queue = RecordingJobQueue()
    async with api_test_context(job_queue=queue) as context:
        identity = await register_and_login(context.client)
        subject = AuthorizationSubject(identity["id"])
        brief_id, revision_id = await _confirmed_brief(
            context,
            subject,
            goal="提升次月留存",
        )
        payload = {"brief_id": brief_id, "brief_revision_id": revision_id}
        headers = {"Idempotency-Key": "job-create-idempotent"}

        first = await context.client.post("/api/v1/jobs", json=payload, headers=headers)
        replay = await context.client.post("/api/v1/jobs", json=payload, headers=headers)

        assert first.status_code == replay.status_code == 202
        assert replay.json() == first.json()
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert queue.job_ids == [first.json()["id"]]
        async with context.session_factory() as session:
            count = await session.scalar(select(func.count(ReportJobRecord.id)))
            assert count == 1


@pytest.mark.asyncio
async def test_request_id_is_returned_and_persisted_for_worker_correlation() -> None:
    queue = RecordingJobQueue()
    async with api_test_context(job_queue=queue) as context:
        identity = await register_and_login(context.client)
        subject = AuthorizationSubject(identity["id"])
        brief_id, revision_id = await _confirmed_brief(
            context,
            subject,
            goal="提升次月留存",
        )
        response = await context.client.post(
            "/api/v1/jobs",
            json={"brief_id": brief_id, "brief_revision_id": revision_id},
            headers={
                "Idempotency-Key": "request-correlation-job",
                "X-Request-ID": "frontend-request-123",
            },
        )

        assert response.status_code == 202
        assert response.headers["X-Request-ID"] == "frontend-request-123"
        async with context.session_factory() as session:
            job = await session.get(ReportJobRecord, response.json()["id"])
            assert job is not None
            assert job.request_id == "frontend-request-123"


@pytest.mark.asyncio
async def test_job_idempotency_key_reuse_with_different_request_is_rejected() -> None:
    queue = RecordingJobQueue()
    async with api_test_context(job_queue=queue) as context:
        identity = await register_and_login(context.client)
        subject = AuthorizationSubject(identity["id"])
        first_brief = await _confirmed_brief(context, subject, goal="提升留存")
        second_brief = await _confirmed_brief(context, subject, goal="提升拉新")
        headers = {"Idempotency-Key": "job-create-conflict"}

        first = await context.client.post(
            "/api/v1/jobs",
            json={"brief_id": first_brief[0], "brief_revision_id": first_brief[1]},
            headers=headers,
        )
        conflict = await context.client.post(
            "/api/v1/jobs",
            json={"brief_id": second_brief[0], "brief_revision_id": second_brief[1]},
            headers=headers,
        )

        assert first.status_code == 202
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
        assert len(queue.job_ids) == 1


@pytest.mark.asyncio
async def test_status_and_event_summary_expose_progress_and_safe_failure() -> None:
    queue = RecordingJobQueue()
    async with api_test_context(job_queue=queue) as context:
        identity = await register_and_login(context.client)
        subject = AuthorizationSubject(identity["id"])
        brief_id, revision_id = await _confirmed_brief(
            context,
            subject,
            goal="提升次月留存",
        )
        created = await context.client.post(
            "/api/v1/jobs",
            json={"brief_id": brief_id, "brief_revision_id": revision_id},
            headers={"Idempotency-Key": "job-status-events"},
        )
        job_id = created.json()["id"]
        async with context.session_factory() as session:
            machine = ReportJobStateMachine(session)
            await machine.start(job_id)
            await machine.transition(
                job_id,
                target_status=JobStatus.FAILED,
                stage="research",
                event_type="provider_failed",
                error_code="SEARCH_TEMPORARILY_UNAVAILABLE",
                error_message="搜索服务暂时不可用，请稍后重新生成。",
            )
            await session.commit()

        status_response = await context.client.get(f"/api/v1/jobs/{job_id}")
        events_response = await context.client.get(f"/api/v1/jobs/{job_id}/events")

        assert status_response.status_code == 200
        assert status_response.json() == {
            "id": job_id,
            "brief_id": brief_id,
            "brief_revision_id": revision_id,
            "status": "failed",
            "stage": "research",
            "progress_percent": 25,
            "error_code": "SEARCH_TEMPORARILY_UNAVAILABLE",
            "error_message": "搜索服务暂时不可用，请稍后重新生成。",
            "report_version_ids": [],
        }
        assert events_response.status_code == 200
        events = events_response.json()["events"]
        assert [event["sequence"] for event in events] == [1, 2]
        assert events[-1]["error_code"] == "SEARCH_TEMPORARILY_UNAVAILABLE"
        assert events[-1]["message"] == "搜索服务暂时不可用，请稍后重新生成。"


@pytest.mark.asyncio
async def test_job_creation_rejects_stale_brief_revision() -> None:
    queue = RecordingJobQueue()
    async with api_test_context(job_queue=queue) as context:
        identity = await register_and_login(context.client)
        subject = AuthorizationSubject(identity["id"])
        async with context.session_factory() as session:
            repository = BriefRepository(session)
            brief, first_revision = await repository.create(
                subject,
                brief_payload={"operation_goal": "旧目标"},
                classification_payload={"primary_scene": "retention"},
            )
            latest = await repository.add_revision(
                subject,
                brief.id,
                expected_latest_revision=1,
                brief_payload={"operation_goal": "新目标"},
                classification_payload={"primary_scene": "retention"},
            )
            await repository.confirm_revision(subject, brief.id, expected_revision=2)
            await session.commit()

        response = await context.client.post(
            "/api/v1/jobs",
            json={"brief_id": brief.id, "brief_revision_id": first_revision.id},
            headers={"Idempotency-Key": "stale-brief-job"},
        )

        assert latest.is_confirmed is True
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "BRIEF_NOT_CONFIRMED"
        assert queue.job_ids == []


@pytest.mark.asyncio
async def test_regeneration_creates_versioned_job_and_preserves_source_report() -> None:
    queue = RecordingJobQueue()
    async with api_test_context(job_queue=queue) as context:
        identity = await register_and_login(context.client)
        subject = AuthorizationSubject(identity["id"])
        source_brief = await _confirmed_brief(context, subject, goal="提升次月留存")
        revised_brief = await _confirmed_brief(context, subject, goal="提升次月留存至25%")
        async with context.session_factory() as session:
            source_report = await _source_report(
                session,
                subject,
                brief_id=source_brief[0],
                revision_id=source_brief[1],
            )
            source_report_id = source_report.id

        response = await context.client.post(
            f"/api/v1/reports/{source_report_id}/regenerate",
            json={"brief_id": revised_brief[0], "brief_revision_id": revised_brief[1]},
            headers={"Idempotency-Key": "regenerate-report-v2"},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["source_report_version_id"] == source_report_id
        assert body["target_version_number"] == 2
        assert queue.job_ids == [body["id"]]
        async with context.session_factory() as session:
            new_job = await session.get(ReportJobRecord, body["id"])
            original = await session.get(ReportVersionRecord, source_report_id)
            assert new_job is not None
            assert new_job.source_report_version_id == source_report_id
            assert original is not None
            assert original.version_number == 1
            second_version = await ReportVersionRepository(session).add_version(
                subject,
                job_id=new_job.id,
                brief_revision_id=revised_brief[1],
                version_number=2,
                delivery_status="formal",
                report_payload={"title": "留存方案优化版", "executive_summary": "新版摘要"},
                playbook_versions={"core": "1.0.0"},
                model_configuration={"model": "test"},
            )
            await session.commit()
            second_version_id = second_version.id

        history = await context.client.get("/api/v1/reports")
        detail = await context.client.get(f"/api/v1/reports/{second_version_id}")

        assert history.status_code == 200
        history_rows = history.json()["reports"]
        assert [row["version_number"] for row in history_rows] == [2, 1]
        assert {row["series_id"] for row in history_rows} == {source_report_id}
        assert history_rows[0]["scene"] == "retention"
        assert detail.status_code == 200
        assert detail.json()["title"] == "留存方案优化版"
        assert detail.json()["report_payload"]["executive_summary"] == "新版摘要"
        assert [row["version_number"] for row in detail.json()["available_versions"]] == [
            1,
            2,
        ]
