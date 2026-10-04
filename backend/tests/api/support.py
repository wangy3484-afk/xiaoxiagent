"""Project-local SQLite app harness for HTTP integration tests."""

import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from ops_agent.config import Settings
from ops_agent.main import create_app
from ops_agent.persistence.database import create_database_engine, create_session_factory
from ops_agent.persistence.models import Base
from ops_agent.providers.contracts import ModelProvider
from ops_agent.queueing import JobQueue
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

PROJECT_ROOT = Path(__file__).parents[3]


@dataclass(frozen=True)
class ApiTestContext:
    app: FastAPI
    client: AsyncClient
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings


@asynccontextmanager
async def api_test_context(
    *,
    secure_cookie: bool = True,
    model_provider: ModelProvider | None = None,
    job_queue: JobQueue | None = None,
) -> AsyncIterator[ApiTestContext]:
    artifact_dir = PROJECT_ROOT / ".test-artifacts"
    artifact_dir.mkdir(exist_ok=True)
    database_path = artifact_dir / f"api-{uuid4()}.sqlite3"
    export_artifact_path = artifact_dir / f"api-artifacts-{uuid4()}"
    database_url = f"sqlite+aiosqlite:///{database_path.resolve().as_posix()}"
    engine = create_database_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = create_session_factory(engine)
    settings = Settings.model_validate(
        {
            "environment": "test",
            "database_url": database_url,
            "session_secret": "test-session-secret-with-sufficient-entropy",
            "session_cookie_secure": secure_cookie,
            "session_cookie_same_site": "lax",
            "session_ttl_minutes": 60,
            "artifact_storage_path": export_artifact_path,
        }
    )
    app = create_app(
        settings=settings,
        session_factory=session_factory,
        model_provider=model_provider,
        job_queue=job_queue,
    )
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="https://testserver",
        ) as client:
            yield ApiTestContext(app, client, engine, session_factory, settings)
    finally:
        await engine.dispose()
        database_path.unlink(missing_ok=True)
        shutil.rmtree(export_artifact_path, ignore_errors=True)


async def register_and_login(
    client: AsyncClient,
    *,
    email: str = "owner@example.com",
    password: str = "correct-horse-battery-staple",
) -> dict[str, str]:
    credentials = {"email": email, "password": password}
    register_response = await client.post("/api/v1/auth/register", json=credentials)
    assert register_response.status_code == 201
    login_response = await client.post("/api/v1/auth/login", json=credentials)
    assert login_response.status_code == 200
    return cast(dict[str, str], login_response.json())
