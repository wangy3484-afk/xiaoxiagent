"""Checkpoint DDL must not run while a report advisory lock is held."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from ops_agent import report_runner
from ops_agent.config import Settings
from ops_agent.persistence.job_state import JobStatus
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.asyncio
async def test_checkpoint_setup_precedes_job_advisory_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    @asynccontextmanager
    async def fake_checkpointer(
        _database_url: str, *, schema: str, setup: bool
    ) -> AsyncIterator[None]:
        assert schema == "langgraph_checkpoint"
        order.append(f"checkpointer_setup={setup}")
        yield

    @asynccontextmanager
    async def fake_lock(_engine: AsyncEngine, _job_id: str) -> AsyncIterator[bool]:
        order.append("advisory_lock")
        yield False

    monkeypatch.setattr(report_runner, "open_postgres_checkpointer", fake_checkpointer)
    monkeypatch.setattr(report_runner, "_job_execution_lock", fake_lock)
    settings = Settings(
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
        checkpoint_database_url=SecretStr("postgresql://unused"),
    )

    result = await report_runner.run_durable_report_job(
        "job-setup-order", active_settings=settings
    )

    assert order == ["checkpointer_setup=True", "advisory_lock"]
    assert result.status is JobStatus.RUNNING
    assert result.executed is False


@pytest.mark.asyncio
async def test_unexpected_graph_error_marks_job_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[str] = []

    @asynccontextmanager
    async def fake_checkpointer(
        _database_url: str, *, schema: str, setup: bool
    ) -> AsyncIterator[None]:
        assert schema == "langgraph_checkpoint"
        yield

    @asynccontextmanager
    async def fake_lock(_engine: AsyncEngine, _job_id: str) -> AsyncIterator[bool]:
        yield True

    async def fake_context(_factory: object, _job_id: str) -> SimpleNamespace:
        return SimpleNamespace(status=JobStatus.RUNNING, request_id=None)

    class FakeGraph:
        async def aget_state(self, _config: object) -> SimpleNamespace:
            return SimpleNamespace(values={"already_started": True})

        async def ainvoke(self, _input: object, _config: object) -> None:
            raise ValueError("synthetic assembly error")

    async def fake_record(_factory: object, job_id: str) -> None:
        recorded.append(job_id)

    monkeypatch.setattr(report_runner, "open_postgres_checkpointer", fake_checkpointer)
    monkeypatch.setattr(report_runner, "_job_execution_lock", fake_lock)
    monkeypatch.setattr(report_runner, "_load_job_context", fake_context)
    monkeypatch.setattr(report_runner, "build_production_providers", lambda _settings: object())
    monkeypatch.setattr(report_runner, "observe_provider_set", lambda *args: object())
    monkeypatch.setattr(report_runner, "build_production_report_nodes", lambda *args: object())
    monkeypatch.setattr(report_runner, "instrument_report_nodes", lambda nodes: nodes)
    monkeypatch.setattr(
        report_runner, "build_report_workflow_graph", lambda *args, **kwargs: FakeGraph()
    )
    monkeypatch.setattr(report_runner, "_record_internal_failure", fake_record)
    settings = Settings(
        database_url=SecretStr("sqlite+aiosqlite:///:memory:"),
        checkpoint_database_url=SecretStr("postgresql://unused"),
    )

    result = await report_runner.run_durable_report_job(
        "job-unexpected-error", active_settings=settings
    )

    assert result.status is JobStatus.FAILED
    assert result.executed is True
    assert recorded == ["job-unexpected-error"]
