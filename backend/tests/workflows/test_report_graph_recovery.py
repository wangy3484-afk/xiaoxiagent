"""Live PostgreSQL recovery tests for research and quality interruptions."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[3]
PROCESS_PROBE = Path(__file__).with_name("report_graph_process.py")
EXPECTED_NODES = [
    "load_context",
    "research",
    "diagnosis",
    "strategy",
    "planning",
    "assembly",
    "quality",
    "finalize",
]


def _run_probe(
    *,
    phase: str,
    crash_node: str,
    thread_id: str,
    schema: str,
    database_url: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["OPS_AGENT_TEST_CHECKPOINT_URL"] = database_url
    environment["LANGGRAPH_STRICT_MSGPACK"] = "true"
    return subprocess.run(
        [
            sys.executable,
            str(PROCESS_PROBE),
            phase,
            crash_node,
            thread_id,
            schema,
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.integration
@pytest.mark.parametrize("crash_node", ["research", "quality"])
def test_report_graph_resumes_after_worker_process_is_forced_to_stop(
    crash_node: str,
) -> None:
    admin_url = os.getenv("OPS_AGENT_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("set OPS_AGENT_TEST_POSTGRES_ADMIN_URL for live PostgreSQL tests")

    database_name = f"ops_agent_report_recovery_{uuid4().hex[:12]}"
    schema = "langgraph_checkpoint"
    with psycopg.connect(
        admin_url, autocommit=True, connect_timeout=5
    ) as admin_connection:
        admin_connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
        database_url = make_conninfo(
            admin_url,
            dbname=database_name,
            connect_timeout=5,
        )
    try:
        thread_id = f"report-recovery-{crash_node}-{uuid4()}"
        crashed = _run_probe(
            phase="crash",
            crash_node=crash_node,
            thread_id=thread_id,
            schema=schema,
            database_url=database_url,
        )
        assert crashed.returncode == 23

        resumed = _run_probe(
            phase="resume",
            crash_node=crash_node,
            thread_id=thread_id,
            schema=schema,
            database_url=database_url,
        )
        if resumed.returncode != 0:
            raise AssertionError(f"resume probe failed:\n{resumed.stderr}")
        payload = cast(
            dict[str, object],
            json.loads(resumed.stdout.strip().splitlines()[-1]),
        )
        assert payload["completed_nodes"] == EXPECTED_NODES
        assert payload["node_counts"] == {node: 1 for node in EXPECTED_NODES}
    finally:
        with psycopg.connect(
            admin_url, autocommit=True, connect_timeout=5
        ) as admin_connection:
            admin_connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database_name)
                )
            )
