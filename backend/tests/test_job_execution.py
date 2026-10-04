"""Fault-injection tests for bounded external-provider retries."""

from collections.abc import Awaitable, Callable

import pytest
from ops_agent.job_execution import execute_report_operation
from ops_agent.persistence.database import create_database_engine, create_session_factory
from ops_agent.persistence.job_state import JobStatus
from ops_agent.persistence.models import Base, JobEventRecord, ReportJobRecord, UserRecord
from ops_agent.providers.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderQuotaError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


async def _database() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
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
    return engine, factory


async def _no_wait(_: float) -> None:
    return None


def _failing_operation(
    error_factory: Callable[[], ProviderError],
) -> tuple[Callable[[str], Awaitable[None]], list[str]]:
    calls: list[str] = []

    async def operation(job_id: str) -> None:
        calls.append(job_id)
        raise error_factory()

    return operation, calls


@pytest.mark.asyncio
async def test_search_rate_limit_retries_twice_then_exposes_retryable_state() -> None:
    engine, factory = await _database()
    operation, calls = _failing_operation(
        lambda: ProviderRateLimitError(
            "raw upstream details must stay hidden",
            provider="search",
            retryable=True,
        )
    )
    try:
        result = await execute_report_operation(
            "job-1",
            session_factory=factory,
            operation=operation,
            retry_delays=(0, 0),
            sleep=_no_wait,
        )

        assert len(calls) == 3
        assert result.status is JobStatus.RETRYABLE
        assert result.attempts == 3
        assert result.retryable is True
        assert result.error_code == "PROVIDER_RATE_LIMITED"
        assert "raw upstream" not in (result.user_message or "")
        async with factory() as session:
            job = await session.get(ReportJobRecord, "job-1")
            events = list(
                await session.scalars(
                    select(JobEventRecord).order_by(JobEventRecord.sequence)
                )
            )
            assert job is not None
            assert (job.status, job.stage) == ("retryable", "retryable_error")
            assert job.error_message == result.user_message
            assert [event.event_type for event in events] == [
                "stage_changed",
                "provider_error",
            ]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_factory", "expected_code"),
    [
        (
            lambda: ProviderQuotaError(
                "quota raw detail", provider="search", retryable=False
            ),
            "PROVIDER_QUOTA_EXHAUSTED",
        ),
        (
            lambda: ProviderAuthenticationError(
                "auth raw detail", provider="model", retryable=False
            ),
            "PROVIDER_AUTHENTICATION_ERROR",
        ),
    ],
)
async def test_quota_and_authentication_errors_fail_fast(
    error_factory: Callable[[], ProviderError],
    expected_code: str,
) -> None:
    engine, factory = await _database()
    operation, calls = _failing_operation(error_factory)
    try:
        result = await execute_report_operation(
            "job-1",
            session_factory=factory,
            operation=operation,
            retry_delays=(0, 0),
            sleep=_no_wait,
        )

        assert len(calls) == 1
        assert result.status is JobStatus.FAILED
        assert result.attempts == 1
        assert result.retryable is False
        assert result.error_code == expected_code
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_transient_operation_can_succeed_on_final_allowed_attempt() -> None:
    engine, factory = await _database()
    attempts = 0

    async def operation(_: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ProviderTimeoutError("temporary", provider="search", retryable=True)

    try:
        result = await execute_report_operation(
            "job-1",
            session_factory=factory,
            operation=operation,
            retry_delays=(0, 0),
            sleep=_no_wait,
        )

        assert attempts == 3
        assert result.status is JobStatus.COMPLETED
        assert result.attempts == 3
        assert result.error_code is None
    finally:
        await engine.dispose()
