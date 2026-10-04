"""Live PostgreSQL tests for durable and isolated LangGraph checkpoints."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast
from uuid import uuid4

import psycopg
import pytest
from ops_agent.persistence.models import Base
from psycopg import sql
from psycopg.conninfo import make_conninfo
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[3]
PROCESS_PROBE = Path(__file__).with_name("checkpoint_process.py")


def _run_probe(
    *,
    phase: str,
    thread_id: str,
    schema: str,
    database_url: str,
) -> dict[str, object]:
    environment = os.environ.copy()
    environment["OPS_AGENT_TEST_CHECKPOINT_URL"] = database_url
    environment["LANGGRAPH_STRICT_MSGPACK"] = "true"
    completed = subprocess.run(
        [sys.executable, str(PROCESS_PROBE), phase, thread_id, schema],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"checkpoint probe failed ({phase}):\n{completed.stderr.strip()}"
        )
    parsed = json.loads(completed.stdout.strip().splitlines()[-1])
    return cast(dict[str, object], parsed)


@pytest.mark.integration
def test_checkpoint_resumes_after_process_restart_and_isolated_from_business_tables() -> None:
    admin_url = os.getenv("OPS_AGENT_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("set OPS_AGENT_TEST_POSTGRES_ADMIN_URL for live PostgreSQL tests")

    database_name = f"ops_agent_checkpoint_test_{uuid4().hex[:12]}"
    checkpoint_schema = "langgraph_checkpoint"
    with psycopg.connect(admin_url, autocommit=True) as admin_connection:
        admin_connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )

    checkpoint_url = make_conninfo(admin_url, dbname=database_name)
    sqlalchemy_url = str(
        make_url(admin_url)
        .set(drivername="postgresql+asyncpg", database=database_name)
        .render_as_string(hide_password=False)
    )
    try:
        migration_environment = os.environ.copy()
        migration_environment["OPS_AGENT_DATABASE_URL"] = sqlalchemy_url
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env=migration_environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )

        thread_id = f"checkpoint-probe-{uuid4()}"
        interrupted = _run_probe(
            phase="start",
            thread_id=thread_id,
            schema=checkpoint_schema,
            database_url=checkpoint_url,
        )
        resumed = _run_probe(
            phase="resume",
            thread_id=thread_id,
            schema=checkpoint_schema,
            database_url=checkpoint_url,
        )

        assert interrupted == {
            "interrupted": True,
            "prepare_count": 1,
            "completed": False,
        }
        assert resumed == {
            "prepare_count": 1,
            "decision": "approved",
            "completed": True,
        }

        with psycopg.connect(checkpoint_url) as connection:
            public_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            }
            checkpoint_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = %s",
                    (checkpoint_schema,),
                )
            }
            user_count = connection.execute("SELECT count(*) FROM public.users").fetchone()

        business_tables = set(Base.metadata.tables)
        assert business_tables <= public_tables
        assert checkpoint_tables
        assert checkpoint_tables.isdisjoint(business_tables)
        assert user_count == (0,)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin_connection:
            admin_connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
