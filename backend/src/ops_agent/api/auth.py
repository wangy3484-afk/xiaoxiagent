"""Local account and server-side session endpoints."""

from datetime import datetime
from typing import Self

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ops_agent.api.dependencies import CurrentUser, DatabaseSession, RequestSettings
from ops_agent.auth.service import (
    AuthService,
    EmailAlreadyRegistered,
    InvalidCredentials,
    normalize_email,
)
from ops_agent.persistence.models import UserRecord

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class CredentialsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = normalize_email(value)
        local, separator, domain = normalized.partition("@")
        if not separator or not local or "." not in domain or domain.startswith("."):
            raise ValueError("email must be a valid address")
        return normalized


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str

    @classmethod
    def from_user(cls, user: UserRecord) -> Self:
        return cls.model_validate(user)


def _set_session_cookie(
    response: Response,
    settings: RequestSettings,
    token: str,
    expires_at: datetime,
) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_minutes * 60,
        expires=expires_at,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=settings.session_cookie_same_site,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: CredentialsRequest,
    session: DatabaseSession,
    settings: RequestSettings,
) -> UserResponse:
    try:
        user = await AuthService(session, settings).register(payload.email, payload.password)
    except EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "EMAIL_ALREADY_REGISTERED", "message": "该邮箱已注册。"},
        ) from exc
    return UserResponse.from_user(user)


@router.post("/login", response_model=UserResponse)
async def login(
    payload: CredentialsRequest,
    response: Response,
    session: DatabaseSession,
    settings: RequestSettings,
) -> UserResponse:
    try:
        authenticated = await AuthService(session, settings).login(
            payload.email,
            payload.password,
        )
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "邮箱或密码错误。"},
        ) from exc
    _set_session_cookie(
        response,
        settings,
        authenticated.token,
        authenticated.expires_at,
    )
    return UserResponse.from_user(authenticated.user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    session: DatabaseSession,
    settings: RequestSettings,
) -> Response:
    token = request.cookies.get(settings.session_cookie_name)
    await AuthService(session, settings).logout(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=settings.session_cookie_same_site,
    )
    return response


@router.get("/me", response_model=UserResponse)
async def current_account(user: CurrentUser) -> UserResponse:
    return UserResponse.from_user(user)
