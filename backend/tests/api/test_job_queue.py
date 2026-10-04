"""API-to-worker report queue contract tests."""

import pytest
from ops_agent.persistence.models import JobEventRecord, ReportJobRecord
from ops_agent.persistence.repositories import (
    AuthorizationSubject,
    BriefRepository,
)
from ops_agent.worker import consume_report_job
from sqlalchemy import select

from api.support import api_test_context, register_and_login


class RecordingJobQueue:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    async def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


@pytest.mark.asyncio
async def test_api_enqueues_job_id_and_worker_persists_stage_event() -> None:
    queue = RecordingJobQueue()
    async with api_test_context(job_queue=queue) as context:
        identity = await register_and_login(context.client)
        subject = AuthorizationSubject(identity["id"])
        async with context.session_factory() as session:
            brief, revision = await BriefRepository(session).create(
                subject,
                brief_payload={"operation_goal": "提升次月留存"},
                classification_payload={"primary_scene": "retention"},
            )
            await BriefRepository(session).confirm_revision(
                subject,
                brief.id,
                expected_revision=revision.revision_number,
            )
            await session.commit()
            brief_id = brief.id
            revision_id = revision.id

        response = await context.client.post(
            "/api/v1/jobs",
            json={"brief_id": brief_id, "brief_revision_id": revision_id},
            headers={"Idempotency-Key": "report-job-1"},
        )

        assert response.status_code == 202
        job_id = response.json()["id"]
        assert queue.job_ids == [job_id]

        await consume_report_job(job_id, session_factory=context.session_factory)

        async with context.session_factory() as session:
            job = await session.get(ReportJobRecord, job_id)
            event = await session.scalar(
                select(JobEventRecord).where(JobEventRecord.job_id == job_id)
            )
            assert job is not None
            assert (job.status, job.stage) == ("running", "initializing")
            assert event is not None
            assert event.event_payload["stage"] == "initializing"
