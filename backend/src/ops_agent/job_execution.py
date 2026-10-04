"""Bounded provider retry policy for report-job execution."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ops_agent.persistence.job_state import JobStatus, ReportJobStateMachine
from ops_agent.providers.errors import ProviderError, ProviderErrorCategory

ReportOperation = Callable[[str], Awaitable[None]]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class ReportJobExecutionResult:
    status: JobStatus
    attempts: int
    executed: bool
    retryable: bool
    error_code: str | None = None
    user_message: str | None = None


_USER_MESSAGES: dict[ProviderErrorCategory, str] = {
    "transient": "外部服务暂时不可用，已达到自动重试上限，可稍后重新生成。",
    "quota": "外部服务配额不足，请联系管理员检查供应商配额后重试。",
    "authentication": "外部服务认证失败，请联系管理员检查供应商配置。",
    "content": "外部内容无法安全处理，请调整输入或稍后重新生成。",
    "provider": "外部服务返回不可恢复错误，请稍后重新生成或联系管理员。",
}


async def execute_report_operation(
    job_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    operation: ReportOperation,
    retry_delays: Sequence[float] = (1.0, 3.0),
    sleep: Sleep = asyncio.sleep,
) -> ReportJobExecutionResult:
    """Claim one job and execute it with at most two transient retries."""
    async with session_factory() as session:
        claimed = await ReportJobStateMachine(session).start(job_id)
        await session.commit()
    if not claimed.applied:
        return ReportJobExecutionResult(
            status=claimed.status,
            attempts=0,
            executed=False,
            retryable=claimed.status is JobStatus.RETRYABLE,
        )

    attempts = 0
    while True:
        attempts += 1
        try:
            await operation(job_id)
        except ProviderError as error:
            can_retry = (
                error.category == "transient"
                and error.retryable
                and attempts <= len(retry_delays)
            )
            if can_retry:
                await sleep(retry_delays[attempts - 1])
                continue
            return await record_provider_failure(
                job_id,
                session_factory=session_factory,
                error=error,
                attempts=attempts,
            )

        async with session_factory() as session:
            completed = await ReportJobStateMachine(session).transition(
                job_id,
                target_status=JobStatus.COMPLETED,
                stage="completed",
            )
            await session.commit()
        return ReportJobExecutionResult(
            status=completed.status,
            attempts=attempts,
            executed=completed.applied,
            retryable=False,
        )


async def record_provider_failure(
    job_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    error: ProviderError,
    attempts: int,
) -> ReportJobExecutionResult:
    retryable = error.category == "transient" and error.retryable
    target_status = JobStatus.RETRYABLE if retryable else JobStatus.FAILED
    stage = "retryable_error" if retryable else "failed"
    user_message = _USER_MESSAGES[error.category]
    async with session_factory() as session:
        transition = await ReportJobStateMachine(session).transition(
            job_id,
            target_status=target_status,
            stage=stage,
            event_type="provider_error",
            error_code=error.code,
            error_message=user_message,
        )
        await session.commit()
    return ReportJobExecutionResult(
        status=transition.status,
        attempts=attempts,
        executed=True,
        retryable=retryable,
        error_code=error.code,
        user_message=user_message,
    )
