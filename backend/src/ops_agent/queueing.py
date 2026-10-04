"""Queue boundary used by the API to dispatch report jobs safely."""

import asyncio
from typing import Protocol

from celery import Celery

REPORT_JOB_TASK = "ops_agent.jobs.generate_report"


class JobQueue(Protocol):
    """Dispatch report work without exposing broker details to the API."""

    async def enqueue(self, job_id: str) -> None:
        """Enqueue a message containing only the persisted report-job identifier."""


class CeleryJobQueue:
    """Redis-backed Celery implementation of the report-job queue."""

    def __init__(self, celery_app: Celery) -> None:
        self._celery_app = celery_app

    async def enqueue(self, job_id: str) -> None:
        await asyncio.to_thread(
            self._celery_app.send_task,
            REPORT_JOB_TASK,
            args=[job_id],
            kwargs={},
        )
