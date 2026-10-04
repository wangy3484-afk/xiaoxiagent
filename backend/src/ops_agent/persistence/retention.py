"""Retention cleanup for old unlocked logs and temporary artifacts only."""

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_agent.artifacts import ArtifactNotFoundError, ArtifactStorage, LocalArtifactStorage
from ops_agent.config import Settings, get_settings
from ops_agent.persistence.database import create_database_engine, create_session_factory
from ops_agent.persistence.models import ExportFileRecord, JobEventRecord
from ops_agent.persistence.repositories import AuthorizationSubject


@dataclass(frozen=True, slots=True)
class RetentionCleanupResult:
    deleted_job_events: int
    deleted_temporary_files: int


async def cleanup_retained_data(
    session: AsyncSession,
    artifact_storage: ArtifactStorage,
    *,
    now: datetime,
    job_event_retention_days: int,
    temporary_artifact_retention_days: int,
) -> RetentionCleanupResult:
    """Delete only records strictly older than their retention boundary.

    Formal report versions are deliberately absent from this function. Non-temporary
    exports and any locked record are also outside the cleanup selection.
    """
    if now.tzinfo is None:
        raise ValueError("retention cleanup requires a timezone-aware current time")
    if job_event_retention_days < 1 or temporary_artifact_retention_days < 1:
        raise ValueError("retention periods must be at least one day")

    event_cutoff = now - timedelta(days=job_event_retention_days)
    temporary_cutoff = now - timedelta(days=temporary_artifact_retention_days)

    event_ids = list(
        await session.scalars(
            select(JobEventRecord.id).where(
                JobEventRecord.retention_locked.is_(False),
                JobEventRecord.created_at < event_cutoff,
            )
        )
    )
    if event_ids:
        await session.execute(
            delete(JobEventRecord).where(
                JobEventRecord.id.in_(event_ids),
                JobEventRecord.retention_locked.is_(False),
            )
        )

    temporary_files = list(
        await session.scalars(
            select(ExportFileRecord).where(
                ExportFileRecord.is_temporary.is_(True),
                ExportFileRecord.retention_locked.is_(False),
                ExportFileRecord.deleted_at.is_(None),
                or_(
                    ExportFileRecord.created_at < temporary_cutoff,
                    ExportFileRecord.expires_at < now,
                ),
            )
        )
    )
    deleted_temporary_files = 0
    for export_file in temporary_files:
        subject = AuthorizationSubject(user_id=export_file.owner_id)
        try:
            artifact_storage.delete(subject, export_file.storage_key)
        except ArtifactNotFoundError:
            pass
        export_file.deleted_at = now
        deleted_temporary_files += 1

    return RetentionCleanupResult(
        deleted_job_events=len(event_ids),
        deleted_temporary_files=deleted_temporary_files,
    )


async def run_retention_cleanup(settings: Settings) -> RetentionCleanupResult:
    engine = create_database_engine(settings.database_url.get_secret_value())
    session_factory = create_session_factory(engine)
    storage = LocalArtifactStorage(settings.artifact_storage_path)
    try:
        async with session_factory() as session, session.begin():
            return await cleanup_retained_data(
                session,
                storage,
                now=datetime.now(UTC),
                job_event_retention_days=settings.job_event_retention_days,
                temporary_artifact_retention_days=(
                    settings.temporary_artifact_retention_days
                ),
            )
    finally:
        await engine.dispose()


def main() -> None:
    result = asyncio.run(run_retention_cleanup(get_settings()))
    print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()
