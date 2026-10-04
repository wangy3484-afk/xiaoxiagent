"""Atomic report-job state transitions and duplicate-delivery protection."""

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ops_agent.persistence.models import JobEventRecord, ReportJobRecord, utc_now


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYABLE = "retryable"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_JOB_STATUSES = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
)

_ALLOWED_PREVIOUS_STATUSES: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.RUNNING: frozenset({JobStatus.QUEUED, JobStatus.RETRYABLE}),
    JobStatus.RETRYABLE: frozenset({JobStatus.RUNNING}),
    JobStatus.COMPLETED: frozenset({JobStatus.RUNNING}),
    JobStatus.FAILED: frozenset({JobStatus.RUNNING}),
    JobStatus.CANCELLED: frozenset(
        {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRYABLE}
    ),
}


class JobStateError(RuntimeError):
    pass


class JobRecordNotFound(JobStateError):
    pass


class InvalidJobTransition(JobStateError):
    pass


@dataclass(frozen=True)
class JobTransitionResult:
    applied: bool
    status: JobStatus
    stage: str
    reason: str


class ReportJobStateMachine:
    """Apply state changes with a database compare-and-set guard."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def start(self, job_id: str) -> JobTransitionResult:
        return await self.transition(
            job_id,
            target_status=JobStatus.RUNNING,
            stage="initializing",
            event_type="stage_changed",
        )

    async def transition(
        self,
        job_id: str,
        *,
        target_status: JobStatus,
        stage: str,
        event_type: str = "stage_changed",
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> JobTransitionResult:
        if target_status is JobStatus.QUEUED:
            raise InvalidJobTransition("queued is an initial state, not a transition target")
        if not stage.strip():
            raise InvalidJobTransition("job stage must not be empty")

        allowed_previous = _ALLOWED_PREVIOUS_STATUSES[target_status]
        statement = (
            update(ReportJobRecord)
            .where(
                ReportJobRecord.id == job_id,
                ReportJobRecord.status.in_(status.value for status in allowed_previous),
            )
            .values(
                status=target_status.value,
                stage=stage,
                error_code=error_code,
                error_message=error_message,
                updated_at=utc_now(),
            )
            .returning(ReportJobRecord.id)
        )
        changed_job_id = await self.session.scalar(statement)
        if changed_job_id is None:
            current = await self.session.get(ReportJobRecord, job_id)
            if current is None:
                raise JobRecordNotFound(f"report job {job_id} was not found")
            current_status = JobStatus(current.status)
            reason = (
                "terminal_state"
                if current_status in TERMINAL_JOB_STATUSES
                else "duplicate_or_out_of_order"
            )
            return JobTransitionResult(
                applied=False,
                status=current_status,
                stage=current.stage,
                reason=reason,
            )

        current_sequence = await self.session.scalar(
            select(func.max(JobEventRecord.sequence)).where(
                JobEventRecord.job_id == job_id
            )
        )
        event_payload = {"status": target_status.value, "stage": stage}
        if error_code is not None:
            event_payload["error_code"] = error_code
        if error_message is not None:
            event_payload["message"] = error_message
        self.session.add(
            JobEventRecord(
                job_id=job_id,
                sequence=(current_sequence or 0) + 1,
                event_type=event_type,
                event_payload=event_payload,
            )
        )
        await self.session.flush()
        return JobTransitionResult(
            applied=True,
            status=target_status,
            stage=stage,
            reason="transition_applied",
        )
