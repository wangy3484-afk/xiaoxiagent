"""Worker-side durable LangGraph runner for complete report generation."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Any, cast
from uuid import UUID, uuid5

from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ops_agent.config import Settings, get_settings
from ops_agent.domain.intake import OperationsBrief, SceneClassification
from ops_agent.domain.quality import ProfessionalQualityReview
from ops_agent.domain.report import OperationsReport
from ops_agent.domain.research import EvidenceBundle
from ops_agent.job_execution import record_provider_failure
from ops_agent.observability import (
    RunMetrics,
    configure_observability,
    log_event,
    observe_provider_set,
    push_observability_context,
    reset_observability_context,
)
from ops_agent.persistence.checkpoints import open_postgres_checkpointer
from ops_agent.persistence.database import create_database_engine, create_session_factory
from ops_agent.persistence.job_state import (
    TERMINAL_JOB_STATUSES,
    JobRecordNotFound,
    JobStatus,
    ReportJobStateMachine,
)
from ops_agent.persistence.models import (
    BriefRevisionRecord,
    ReportJobRecord,
    ReportVersionRecord,
)
from ops_agent.persistence.repositories import (
    AuthorizationSubject,
    EvidenceRepository,
    QualityReviewRepository,
    ReportVersionRepository,
)
from ops_agent.playbooks.loader import load_default_registry
from ops_agent.providers.errors import ProviderError
from ops_agent.providers.wiring import build_production_providers
from ops_agent.workflows.report_graph import (
    ReportWorkflowState,
    build_production_report_nodes,
    build_report_workflow_graph,
    initial_report_workflow_state,
    instrument_report_nodes,
)


@dataclass(frozen=True)
class DurableReportRunResult:
    job_id: str
    status: JobStatus
    resumed: bool
    executed: bool
    completed_nodes: tuple[str, ...] = ()


async def run_durable_report_job(
    job_id: str,
    *,
    active_settings: Settings | None = None,
    retry_delays: tuple[float, ...] = (1.0, 3.0),
) -> DurableReportRunResult:
    """Run or resume one report graph while holding a PostgreSQL advisory lock."""
    settings = active_settings or get_settings()
    configure_observability(settings.log_level)
    engine = create_database_engine(settings.database_url.get_secret_value())
    session_factory = create_session_factory(engine)
    metrics = RunMetrics()
    started = perf_counter()
    context_tokens = push_observability_context(job_id=job_id, thread_id=job_id)
    try:
        log_event("report_job_run_started")
        # LangGraph setup can create indexes concurrently. Do it before the
        # job's advisory-lock transaction, which would otherwise block setup.
        async with open_postgres_checkpointer(
            settings.checkpoint_database_url.get_secret_value(),
            schema=settings.checkpoint_schema,
            setup=True,
        ):
            pass
        async with _job_execution_lock(engine, job_id) as acquired:
            if not acquired:
                return DurableReportRunResult(
                    job_id=job_id,
                    status=JobStatus.RUNNING,
                    resumed=False,
                    executed=False,
                )
            context = await _load_job_context(session_factory, job_id)
            context_tokens.extend(
                push_observability_context(request_id=context.request_id)
            )
            if context.status in TERMINAL_JOB_STATUSES:
                return DurableReportRunResult(
                    job_id=job_id,
                    status=context.status,
                    resumed=False,
                    executed=False,
                )
            resumed = context.status is JobStatus.RUNNING
            if not resumed:
                async with session_factory() as session:
                    transition = await ReportJobStateMachine(session).start(job_id)
                    await session.commit()
                if not transition.applied:
                    return DurableReportRunResult(
                        job_id=job_id,
                        status=transition.status,
                        resumed=False,
                        executed=False,
                    )

            try:
                providers = observe_provider_set(
                    build_production_providers(settings),
                    metrics,
                    settings,
                )
            except ValueError:
                await _record_configuration_failure(session_factory, job_id)
                return DurableReportRunResult(
                    job_id=job_id,
                    status=JobStatus.FAILED,
                    resumed=resumed,
                    executed=True,
                )

            try:
                async with open_postgres_checkpointer(
                    settings.checkpoint_database_url.get_secret_value(),
                    schema=settings.checkpoint_schema,
                    setup=False,
                ) as checkpointer:
                    graph = build_report_workflow_graph(
                        instrument_report_nodes(
                            build_production_report_nodes(providers, settings)
                        ),
                        checkpointer=checkpointer,
                    )
                    config: RunnableConfig = {"configurable": {"thread_id": job_id}}
                    snapshot = await graph.aget_state(config)
                    graph_input: ReportWorkflowState | None
                    if snapshot.values:
                        graph_input = None
                        resumed = True
                    else:
                        graph_input = initial_report_workflow_state(
                            job_id=job_id,
                            brief=context.brief,
                            classification=context.classification,
                        )
                    result = await _invoke_with_provider_retries(
                        graph,
                        graph_input,
                        config,
                        job_id=job_id,
                        session_factory=session_factory,
                        retry_delays=retry_delays,
                    )
                    if result is None:
                        return DurableReportRunResult(
                            job_id=job_id,
                            status=JobStatus.RETRYABLE,
                            resumed=resumed,
                            executed=True,
                        )

                await _persist_result(session_factory, settings, context, result)
            except Exception as exc:  # noqa: BLE001 - job must not remain running forever
                constraint_name = (
                    getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
                    if isinstance(exc, IntegrityError)
                    else None
                )
                log_event(
                    "report_job_internal_failed",
                    error_type=type(exc).__name__,
                    constraint_name=constraint_name,
                    validation_issues=(
                        [
                            {
                                "location": [str(part) for part in issue["loc"]],
                                "message": str(issue["msg"])[:160],
                            }
                            for issue in exc.errors(
                                include_input=False, include_context=False
                            )[:8]
                        ]
                        if isinstance(exc, ValidationError)
                        else []
                    ),
                )
                await _record_internal_failure(session_factory, job_id)
                return DurableReportRunResult(
                    job_id=job_id,
                    status=JobStatus.FAILED,
                    resumed=resumed,
                    executed=True,
                )
            async with session_factory() as session:
                completed = await ReportJobStateMachine(session).transition(
                    job_id,
                    target_status=JobStatus.COMPLETED,
                    stage="completed",
                )
                await session.commit()
            return DurableReportRunResult(
                job_id=job_id,
                status=completed.status,
                resumed=resumed,
                executed=completed.applied,
                completed_nodes=tuple(result["completed_nodes"]),
            )
    finally:
        log_event(
            "report_job_run_finished",
            duration_ms=max(0, round((perf_counter() - started) * 1_000)),
            metrics=metrics.summary(),
        )
        reset_observability_context(context_tokens)
        await engine.dispose()


@dataclass(frozen=True)
class _JobContext:
    job_id: str
    owner_id: str
    brief_revision_id: str
    target_version_number: int
    request_id: str | None
    status: JobStatus
    brief: OperationsBrief
    classification: SceneClassification


async def _load_job_context(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
) -> _JobContext:
    async with session_factory() as session:
        job = await session.get(ReportJobRecord, job_id)
        if job is None:
            raise JobRecordNotFound(f"report job {job_id} was not found")
        revision = await session.get(BriefRevisionRecord, job.brief_revision_id)
        if revision is None or not revision.is_confirmed:
            raise JobRecordNotFound("confirmed brief revision was not found")
        target_version_number = 1
        if job.source_report_version_id is not None:
            source_report = await session.get(
                ReportVersionRecord,
                job.source_report_version_id,
            )
            if source_report is None or source_report.owner_id != job.owner_id:
                raise JobRecordNotFound("source report version was not found")
            target_version_number = source_report.version_number + 1
        return _JobContext(
            job_id=job.id,
            owner_id=job.owner_id,
            brief_revision_id=job.brief_revision_id,
            target_version_number=target_version_number,
            request_id=job.request_id,
            status=JobStatus(job.status),
            brief=OperationsBrief.model_validate(revision.brief_payload),
            classification=SceneClassification.model_validate(
                revision.classification_payload
            ),
        )


async def _invoke_with_provider_retries(
    graph: Any,
    graph_input: ReportWorkflowState | None,
    config: RunnableConfig,
    *,
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession],
    retry_delays: tuple[float, ...],
) -> ReportWorkflowState | None:
    attempts = 0
    current_input = graph_input
    while True:
        attempts += 1
        try:
            result = await graph.ainvoke(current_input, config)
            return cast(ReportWorkflowState, result)
        except ProviderError as error:
            if (
                error.category == "transient"
                and error.retryable
                and attempts <= len(retry_delays)
            ):
                await asyncio.sleep(retry_delays[attempts - 1])
                current_input = None
                continue
            await record_provider_failure(
                job_id,
                session_factory=session_factory,
                error=error,
                attempts=attempts,
            )
            return None


async def _persist_result(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    context: _JobContext,
    result: ReportWorkflowState,
) -> None:
    report = OperationsReport.model_validate(result["finalized_report"])
    evidence = EvidenceBundle.model_validate(result["evidence_bundle"])
    report, evidence = _namespace_persisted_references(context.job_id, report, evidence)
    professional_review = ProfessionalQualityReview.model_validate(
        result["professional_review"]
    )
    subject = AuthorizationSubject(context.owner_id)
    registry = load_default_registry()
    playbook_versions = {
        "core": registry.core.playbook_version,
        context.classification.primary_scene.value: registry.for_scene(
            context.classification.primary_scene
        ).playbook_version,
    }
    async with session_factory() as session:
        report_repository = ReportVersionRepository(session)
        existing = await report_repository.list_for_job(subject, context.job_id)
        if existing:
            await session.commit()
            return
        await EvidenceRepository(session).add_bundle(subject, context.job_id, evidence)
        version = await report_repository.add_version(
            subject,
            job_id=context.job_id,
            brief_revision_id=context.brief_revision_id,
            version_number=context.target_version_number,
            delivery_status=report.delivery_status.value,
            report_payload=report.model_dump(mode="json"),
            playbook_versions=playbook_versions,
            model_configuration={
                "provider": settings.model_provider,
                "model": settings.model_name,
                "base_url": str(settings.model_base_url),
            },
        )
        await QualityReviewRepository(session).add(
            subject,
            report_version_id=version.id,
            revision_round=result.get("revision_round", 0),
            review_payload=professional_review.model_dump(mode="json"),
            blocking_issue_count=len(professional_review.blocking_issue_ids),
        )
        await session.commit()


_EVIDENCE_ID_FIELDS = frozenset({"evidence_id"})
_EVIDENCE_ID_LIST_FIELDS = frozenset({"evidence_ids"})
_CLAIM_ID_FIELDS = frozenset({"claim_id", "hypothesis_claim_id"})
_CLAIM_ID_LIST_FIELDS = frozenset(
    {
        "claim_ids",
        "supported_claim_ids",
        "supporting_claim_ids",
        "assumption_claim_ids",
        "outcome_claim_ids",
        "downgraded_claim_ids",
    }
)


def _namespace_persisted_references(
    job_id: str,
    report: OperationsReport,
    evidence: EvidenceBundle,
) -> tuple[OperationsReport, EvidenceBundle]:
    """Give model-generated IDs a stable job namespace before database storage."""
    namespace = UUID(job_id)

    def remap(value: Any) -> Any:
        if isinstance(value, list):
            return [remap(item) for item in value]
        if not isinstance(value, dict):
            return value
        adjusted: dict[str, Any] = {}
        for key, item in value.items():
            if key in _EVIDENCE_ID_FIELDS and isinstance(item, str):
                adjusted[key] = str(uuid5(namespace, f"evidence:{item}"))
            elif key in _CLAIM_ID_FIELDS and isinstance(item, str):
                adjusted[key] = str(uuid5(namespace, f"claim:{item}"))
            elif key in _EVIDENCE_ID_LIST_FIELDS and isinstance(item, list):
                adjusted[key] = [
                    str(uuid5(namespace, f"evidence:{entry}"))
                    if isinstance(entry, str)
                    else entry
                    for entry in item
                ]
            elif key in _CLAIM_ID_LIST_FIELDS and isinstance(item, list):
                adjusted[key] = [
                    str(uuid5(namespace, f"claim:{entry}"))
                    if isinstance(entry, str)
                    else entry
                    for entry in item
                ]
            else:
                adjusted[key] = remap(item)
        return adjusted

    return (
        OperationsReport.model_validate(remap(report.model_dump(mode="json"))),
        EvidenceBundle.model_validate(remap(evidence.model_dump(mode="json"))),
    )


async def _record_configuration_failure(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
) -> None:
    async with session_factory() as session:
        await ReportJobStateMachine(session).transition(
            job_id,
            target_status=JobStatus.FAILED,
            stage="configuration_error",
            event_type="configuration_error",
            error_code="PROVIDER_NOT_CONFIGURED",
            error_message="模型或搜索服务尚未配置，请联系管理员后重新生成。",
        )
        await session.commit()


async def _record_internal_failure(
    session_factory: async_sessionmaker[AsyncSession],
    job_id: str,
) -> None:
    async with session_factory() as session:
        await ReportJobStateMachine(session).transition(
            job_id,
            target_status=JobStatus.FAILED,
            stage="failed",
            event_type="internal_error",
            error_code="INTERNAL_REPORT_ERROR",
            error_message="报告生成遇到内部错误，请联系管理员并提供任务编号。",
        )
        await session.commit()


@asynccontextmanager
async def _job_execution_lock(
    engine: AsyncEngine,
    job_id: str,
) -> AsyncIterator[bool]:
    """Hold a session-level PostgreSQL advisory lock for the entire graph run."""
    async with engine.connect() as connection:
        if connection.dialect.name != "postgresql":
            yield True
            return
        acquired = bool(
            await connection.scalar(
                text("SELECT pg_try_advisory_lock(hashtextextended(:job_id, 0))"),
                {"job_id": job_id},
            )
        )
        try:
            yield acquired
        finally:
            if acquired:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:job_id, 0))"),
                    {"job_id": job_id},
                )
