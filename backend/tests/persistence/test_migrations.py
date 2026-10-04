"""Migration smoke test against a truly empty temporary database."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

PROJECT_ROOT = Path(__file__).parents[3]
BUSINESS_TABLES = {
    "users",
    "sessions",
    "idempotency_records",
    "operations_briefs",
    "brief_revisions",
    "report_jobs",
    "job_events",
    "evidence_records",
    "claims",
    "claim_evidence_links",
    "report_versions",
    "quality_reviews",
    "export_files",
}


def test_empty_database_upgrades_and_fully_downgrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPS_AGENT_DATABASE_URL", raising=False)
    artifact_dir = PROJECT_ROOT / ".test-artifacts"
    artifact_dir.mkdir(exist_ok=True)
    database_path = (artifact_dir / "migration.sqlite3").resolve()
    database_path.unlink(missing_ok=True)
    async_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    sync_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", async_url)

    try:
        command.upgrade(config, "head")
        engine = create_engine(sync_url)
        try:
            assert BUSINESS_TABLES <= set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

        command.downgrade(config, "base")
        engine = create_engine(sync_url)
        try:
            remaining = set(inspect(engine).get_table_names())
            assert not (BUSINESS_TABLES & remaining)
        finally:
            engine.dispose()
    finally:
        database_path.unlink(missing_ok=True)
