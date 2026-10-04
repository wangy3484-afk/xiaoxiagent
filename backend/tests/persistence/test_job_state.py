"""Report-job state machine and duplicate-delivery tests."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from ops_agent.persistence.database import create_database_engine, create_session_factory
from ops_agent.persistence.job_state import JobStatus, ReportJobStateMachine
from ops_agent.persistence.models import (
    Base,
    JobEventRecord,
    ReportJobRecord,
    UserRecord,
)
from ops_agent.worker import consume_report_job
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


async def _database(
    name: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], Path]:
    artifact_dir = Path(__file__).parents[3] / ".test-artifacts"
    artifact_dir.mkdir(exist_ok=True)
    path = artifact_dir / f"{name}-{uuid4()}.sqlite3"
    engine = create_database_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        session.add(UserRecord(id="owner-1", email="owner@example.com", password_hash="hash"))
        session.add(
            ReportJobRecord(
                id="job-1",
                owner_id="owner-1",
                brief_id="brief-1",
                brief_revision_id="revision-1",
                idempotency_key="job-key-1",
            )
        )
        await session.commit()
    return engine, factory, path


@pytest.mark.asyncio
async def test_concurrent_duplicate_delivery_claims_only_one_execution() -> None:
    engine, factory, path = await _database("concurrent-job")
    try:
        first, second = await asyncio.gather(
            consume_report_job("job-1", session_factory=factory),
            consume_report_job("job-1", session_factory=factory),
        )

        assert sorted([first.applied, second.applied]) == [False, True]
        async with factory() as session:
            event_count = await session.scalar(
                select(func.count(JobEventRecord.id)).where(
                    JobEventRecord.job_id == "job-1"
                )
            )
            job = await session.get(ReportJobRecord, "job-1")
            assert event_count == 1
            assert job is not None
            assert (job.status, job.stage) == ("running", "initializing")
    finally:
        await engine.dispose()
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_terminal_state_rejects_late_and_regressive_events() -> None:
    engine, factory, path = await _database("terminal-job")
    try:
        async with factory() as session:
            machine = ReportJobStateMachine(session)
            started = await machine.start("job-1")
            completed = await machine.transition(
                "job-1",
                target_status=JobStatus.COMPLETED,
                stage="completed",
            )
            await session.commit()
            assert started.applied is True
            assert completed.applied is True

        async with factory() as session:
            machine = ReportJobStateMachine(session)
            late_start = await machine.start("job-1")
            late_failure = await machine.transition(
                "job-1",
                target_status=JobStatus.FAILED,
                stage="failed",
            )
            await session.commit()
            assert late_start.applied is False
            assert late_start.reason == "terminal_state"
            assert late_failure.applied is False
            assert late_failure.reason == "terminal_state"

        async with factory() as session:
            job = await session.get(ReportJobRecord, "job-1")
            events = list(
                await session.scalars(
                    select(JobEventRecord)
                    .where(JobEventRecord.job_id == "job-1")
                    .order_by(JobEventRecord.sequence)
                )
            )
            assert job is not None
            assert (job.status, job.stage) == ("completed", "completed")
            assert [event.event_payload["status"] for event in events] == [
                "running",
                "completed",
            ]
    finally:
        await engine.dispose()
        path.unlink(missing_ok=True)
