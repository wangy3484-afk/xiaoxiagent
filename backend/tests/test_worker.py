from unittest.mock import Mock

import pytest
from ops_agent.persistence.database import create_database_engine, create_session_factory
from ops_agent.persistence.models import (
    Base,
    JobEventRecord,
    ReportJobRecord,
    UserRecord,
)
from ops_agent.queueing import REPORT_JOB_TASK, CeleryJobQueue
from ops_agent.worker import celery_app, consume_report_job, generate_report
from sqlalchemy import select


def test_worker_uses_json_messages() -> None:
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.task_default_queue == "report-jobs"
    assert celery_app.conf.task_routes[REPORT_JOB_TASK] == {"queue": "report-jobs"}
    assert generate_report.name == REPORT_JOB_TASK


@pytest.mark.asyncio
async def test_celery_queue_message_contains_only_job_id() -> None:
    app = Mock()
    queue = CeleryJobQueue(app)

    await queue.enqueue("job-123")

    app.send_task.assert_called_once_with(
        REPORT_JOB_TASK,
        args=["job-123"],
        kwargs={},
    )


@pytest.mark.asyncio
async def test_worker_consumes_job_and_persists_stage_event() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            session.add(
                UserRecord(id="user-1", email="owner@example.com", password_hash="hash")
            )
            session.add(
                ReportJobRecord(
                    id="job-1",
                    owner_id="user-1",
                    brief_id="brief-1",
                    brief_revision_id="revision-1",
                    idempotency_key="job-key-1",
                )
            )
            # The foreign keys are not enforced by this in-memory SQLite probe.
            await session.commit()

        transition = await consume_report_job("job-1", session_factory=session_factory)

        async with session_factory() as session:
            job = await session.get(ReportJobRecord, "job-1")
            event = await session.scalar(select(JobEventRecord))
            assert job is not None
            assert job.status == "running"
            assert job.stage == "initializing"
            assert event is not None
            assert event.sequence == 1
            assert event.event_type == "stage_changed"
            assert event.event_payload == {
                "status": "running",
                "stage": "initializing",
            }
            assert transition.applied is True
    finally:
        await engine.dispose()
