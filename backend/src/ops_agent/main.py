"""FastAPI application factory and process entrypoint."""

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.responses import Response

from ops_agent.api.auth import router as auth_router
from ops_agent.api.briefs import router as briefs_router
from ops_agent.api.exports import router as exports_router
from ops_agent.api.jobs import router as jobs_router
from ops_agent.api.reports import router as reports_router
from ops_agent.api.resources import router as resources_router
from ops_agent.artifacts import ArtifactStorage, LocalArtifactStorage
from ops_agent.config import Settings, get_settings
from ops_agent.observability import (
    bind_observability_context,
    configure_observability,
    log_event,
)
from ops_agent.persistence.database import create_database_engine, create_session_factory
from ops_agent.playbooks import load_default_registry
from ops_agent.providers.contracts import ModelProvider
from ops_agent.providers.openai_compatible import OpenAICompatibleModelProvider
from ops_agent.queueing import CeleryJobQueue, JobQueue
from ops_agent.worker import celery_app


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    model_provider: ModelProvider | None = None,
    job_queue: JobQueue | None = None,
    artifact_storage: ArtifactStorage | None = None,
) -> FastAPI:
    """Build an app with injectable settings and database sessions for tests."""
    active_settings = settings or get_settings()
    configure_observability(active_settings.log_level)
    owned_engine: AsyncEngine | None = None
    if session_factory is None:
        owned_engine = create_database_engine(active_settings.database_url.get_secret_value())
        session_factory = create_session_factory(owned_engine)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.playbooks = load_default_registry()
        yield
        if owned_engine is not None:
            await owned_engine.dispose()

    application = FastAPI(
        title="Operations Strategy Agent",
        version="0.1.0",
        description="Evidence-based operations strategy decision support.",
        lifespan=lifespan,
    )
    application.state.settings = active_settings
    application.state.session_factory = session_factory
    if model_provider is None and active_settings.model_api_key is not None:
        model_provider = OpenAICompatibleModelProvider(
            base_url=str(active_settings.model_base_url),
            api_key=active_settings.model_api_key,
            model=active_settings.model_name,
            timeout_seconds=active_settings.model_timeout_seconds,
            schema_retries=active_settings.model_max_retries,
            structured_output_mode=active_settings.model_structured_output_mode,
            thinking_mode=active_settings.model_thinking_mode,
        )
    application.state.model_provider = model_provider
    application.state.job_queue = job_queue or CeleryJobQueue(celery_app)
    application.state.artifact_storage = artifact_storage or LocalArtifactStorage(
        active_settings.artifact_storage_path
    )

    @application.middleware("http")
    async def request_correlation(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", supplied)
            else str(uuid4())
        )
        started = perf_counter()
        with bind_observability_context(request_id=request_id):
            log_event(
                "http_request_started",
                method=request.method,
                path=request.url.path,
            )
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            log_event(
                "http_request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=max(0, round((perf_counter() - started) * 1_000)),
            )
            return response
    application.include_router(auth_router)
    application.include_router(briefs_router)
    application.include_router(exports_router)
    application.include_router(jobs_router)
    application.include_router(reports_router)
    application.include_router(resources_router)

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Return a lightweight liveness response."""
        return {"status": "ok"}

    return application


app = create_app()
