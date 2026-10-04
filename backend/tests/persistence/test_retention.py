"""Boundary tests for conservative retention cleanup."""

import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from ops_agent.artifacts import ArtifactNotFoundError, LocalArtifactStorage
from ops_agent.persistence.models import (
    Base,
    ExportFileRecord,
    JobEventRecord,
    ReportVersionRecord,
)
from ops_agent.persistence.repositories import AuthorizationSubject
from ops_agent.persistence.retention import cleanup_retained_data
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def retention_context() -> AsyncIterator[
    tuple[async_sessionmaker[AsyncSession], LocalArtifactStorage]
]:
    workspace = Path.cwd().resolve()
    root = (workspace / ".test-artifacts" / f"retention-{uuid4()}").resolve()
    root.relative_to(workspace)
    root.mkdir(parents=True)
    engine = create_async_engine(f"sqlite+aiosqlite:///{(root / 'retention.sqlite3').as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False), LocalArtifactStorage(
            root / "artifacts"
        )
    finally:
        await engine.dispose()
        shutil.rmtree(root)


@pytest.mark.asyncio
async def test_cleanup_respects_boundary_locks_and_formal_reports(
    retention_context: tuple[async_sessionmaker[AsyncSession], LocalArtifactStorage],
) -> None:
    session_factory, storage = retention_context
    now = datetime(2026, 9, 29, 9, 0, tzinfo=UTC)
    event_cutoff = now - timedelta(days=30)
    temporary_cutoff = now - timedelta(days=7)
    owner = AuthorizationSubject(user_id="owner-a")

    async with session_factory() as session:
        session.add_all(
            [
                JobEventRecord(
                    id="old-event",
                    job_id="job-1",
                    sequence=1,
                    event_type="old",
                    event_payload={},
                    retention_locked=False,
                    created_at=event_cutoff - timedelta(seconds=1),
                ),
                JobEventRecord(
                    id="boundary-event",
                    job_id="job-1",
                    sequence=2,
                    event_type="boundary",
                    event_payload={},
                    retention_locked=False,
                    created_at=event_cutoff,
                ),
                JobEventRecord(
                    id="locked-event",
                    job_id="job-1",
                    sequence=3,
                    event_type="locked",
                    event_payload={},
                    retention_locked=True,
                    created_at=event_cutoff - timedelta(days=1),
                ),
            ]
        )
        session.add(
            ReportVersionRecord(
                id="formal-report",
                owner_id=owner.user_id,
                job_id="job-1",
                brief_revision_id="revision-1",
                version_number=1,
                delivery_status="formal",
                report_payload={"status": "must-survive"},
                playbook_versions={},
                model_configuration={},
                generated_at=now - timedelta(days=3650),
            )
        )

        exports = [
            ExportFileRecord(
                id="old-temporary",
                owner_id=owner.user_id,
                report_version_id="formal-report",
                format="md",
                storage_key="temporary/old.md",
                checksum_sha256="unused",
                size_bytes=3,
                content_type="text/markdown",
                is_temporary=True,
                retention_locked=False,
                created_at=temporary_cutoff - timedelta(seconds=1),
            ),
            ExportFileRecord(
                id="boundary-temporary",
                owner_id=owner.user_id,
                report_version_id="formal-report",
                format="md",
                storage_key="temporary/boundary.md",
                checksum_sha256="unused",
                size_bytes=3,
                content_type="text/markdown",
                is_temporary=True,
                retention_locked=False,
                created_at=temporary_cutoff,
            ),
            ExportFileRecord(
                id="locked-temporary",
                owner_id=owner.user_id,
                report_version_id="formal-report",
                format="md",
                storage_key="temporary/locked.md",
                checksum_sha256="unused",
                size_bytes=3,
                content_type="text/markdown",
                is_temporary=True,
                retention_locked=True,
                created_at=temporary_cutoff - timedelta(days=1),
            ),
            ExportFileRecord(
                id="formal-export",
                owner_id=owner.user_id,
                report_version_id="formal-report",
                format="pdf",
                storage_key="formal/report.pdf",
                checksum_sha256="unused",
                size_bytes=3,
                content_type="application/pdf",
                is_temporary=False,
                retention_locked=False,
                created_at=temporary_cutoff - timedelta(days=365),
            ),
        ]
        session.add_all(exports)
        for export_file in exports:
            storage.write(
                owner,
                export_file.storage_key,
                b"old",
                content_type=export_file.content_type,
            )
        await session.commit()

        result = await cleanup_retained_data(
            session,
            storage,
            now=now,
            job_event_retention_days=30,
            temporary_artifact_retention_days=7,
        )
        await session.commit()

        remaining_events = set(await session.scalars(select(JobEventRecord.id)))
        persisted_exports = {
            item.id: item
            for item in await session.scalars(select(ExportFileRecord))
        }
        formal_report = await session.get(ReportVersionRecord, "formal-report")

    assert result.deleted_job_events == 1
    assert result.deleted_temporary_files == 1
    assert remaining_events == {"boundary-event", "locked-event"}
    assert persisted_exports["old-temporary"].deleted_at == now
    assert persisted_exports["boundary-temporary"].deleted_at is None
    assert persisted_exports["locked-temporary"].deleted_at is None
    assert persisted_exports["formal-export"].deleted_at is None
    assert formal_report is not None
    assert formal_report.report_payload == {"status": "must-survive"}

    with pytest.raises(ArtifactNotFoundError):
        storage.read(owner, "temporary/old.md")
    for preserved_key in (
        "temporary/boundary.md",
        "temporary/locked.md",
        "formal/report.pdf",
    ):
        assert storage.read(owner, preserved_key)[1] == b"old"


@pytest.mark.asyncio
async def test_cleanup_rejects_naive_time_and_zero_retention(
    retention_context: tuple[async_sessionmaker[AsyncSession], LocalArtifactStorage],
) -> None:
    session_factory, storage = retention_context
    async with session_factory() as session:
        with pytest.raises(ValueError, match="timezone-aware"):
            await cleanup_retained_data(
                session,
                storage,
                now=datetime(2026, 9, 29),
                job_event_retention_days=30,
                temporary_artifact_retention_days=7,
            )
        with pytest.raises(ValueError, match="at least one day"):
            await cleanup_retained_data(
                session,
                storage,
                now=datetime(2026, 9, 29, tzinfo=UTC),
                job_event_retention_days=0,
                temporary_artifact_retention_days=7,
            )
