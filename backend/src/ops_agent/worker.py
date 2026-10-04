"""Celery worker entrypoint and persisted report-job consumer."""

import asyncio

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ops_agent.config import Settings, get_settings
from ops_agent.persistence.database import create_database_engine, create_session_factory
from ops_agent.persistence.job_state import JobTransitionResult, ReportJobStateMachine
from ops_agent.queueing import REPORT_JOB_TASK
from ops_agent.report_runner import run_durable_report_job

settings = get_settings()

celery_app = Celery(
    "ops_strategy_agent",
    broker=settings.redis_url.get_secret_value(),
)
celery_app.conf.update(
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    task_default_queue="report-jobs",
    task_routes={REPORT_JOB_TASK: {"queue": "report-jobs"}},
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)


async def consume_report_job(
    job_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    active_settings: Settings | None = None,
) -> JobTransitionResult:
    """Load a job from durable storage and record that worker processing began."""
    owned_engine = None
    if session_factory is None:
        runtime_settings = active_settings or get_settings()
        owned_engine = create_database_engine(
            runtime_settings.database_url.get_secret_value()
        )
        session_factory = create_session_factory(owned_engine)

    try:
        async with session_factory() as session:
            result = await ReportJobStateMachine(session).start(job_id)
            await session.commit()
            return result
    finally:
        if owned_engine is not None:
            await owned_engine.dispose()


@celery_app.task(name=REPORT_JOB_TASK, ignore_result=True)  # type: ignore[untyped-decorator]
def generate_report(job_id: str) -> None:
    """Celery message contract: the broker payload contains only ``job_id``."""
    asyncio.run(run_durable_report_job(job_id))
