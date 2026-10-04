"""Request-scoped database, settings, and authentication dependencies."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ops_agent.artifacts import ArtifactStorage
from ops_agent.auth.service import AuthService
from ops_agent.config import Settings
from ops_agent.persistence.models import UserRecord
from ops_agent.persistence.repositories import AuthorizationSubject
from ops_agent.providers.contracts import ModelProvider
from ops_agent.queueing import JobQueue


def get_request_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DatabaseSession = Annotated[AsyncSession, Depends(get_database_session)]
RequestSettings = Annotated[Settings, Depends(get_request_settings)]


def get_artifact_storage(request: Request) -> ArtifactStorage:
    storage: ArtifactStorage = request.app.state.artifact_storage
    return storage


RequestArtifactStorage = Annotated[ArtifactStorage, Depends(get_artifact_storage)]


def authentication_required() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "AUTHENTICATION_REQUIRED",
            "message": "请先登录后再访问该资源。",
        },
    )


async def get_current_user(
    request: Request,
    session: DatabaseSession,
    settings: RequestSettings,
) -> UserRecord:
    token = request.cookies.get(settings.session_cookie_name)
    user = await AuthService(session, settings).current_user(token)
    if user is None:
        raise authentication_required()
    return user


CurrentUser = Annotated[UserRecord, Depends(get_current_user)]


async def get_authorization_subject(user: CurrentUser) -> AuthorizationSubject:
    return AuthorizationSubject(user_id=user.id)


CurrentSubject = Annotated[AuthorizationSubject, Depends(get_authorization_subject)]


def get_model_provider(request: Request) -> ModelProvider:
    provider: ModelProvider | None = request.app.state.model_provider
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "MODEL_PROVIDER_NOT_CONFIGURED",
                "message": "模型服务尚未配置，请联系管理员设置模型 API Key。",
            },
        )
    return provider


RequestModelProvider = Annotated[ModelProvider, Depends(get_model_provider)]


def get_job_queue(request: Request) -> JobQueue:
    queue: JobQueue = request.app.state.job_queue
    return queue


RequestJobQueue = Annotated[JobQueue, Depends(get_job_queue)]
