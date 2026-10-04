"""Local-account authentication with opaque, server-side sessions."""

import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ops_agent.config import Settings
from ops_agent.persistence.models import SessionRecord, UserRecord


class AuthenticationError(RuntimeError):
    """Base class for safe authentication failures."""


class EmailAlreadyRegistered(AuthenticationError):
    """Raised when a normalized email already belongs to an account."""


class InvalidCredentials(AuthenticationError):
    """Raised for both unknown users and incorrect passwords."""


@dataclass(frozen=True)
class AuthenticatedSession:
    """The only point at which a raw session token exists server-side."""

    user: UserRecord
    token: str
    expires_at: datetime


def normalize_email(email: str) -> str:
    """Normalize the local account identifier before storage and lookup."""
    return email.strip().casefold()


class AuthService:
    """Own password and session mechanics behind a replaceable auth boundary."""

    _password_hash = PasswordHash.recommended()
    _dummy_hash = _password_hash.hash("not-a-real-user-password")

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def register(self, email: str, password: str) -> UserRecord:
        password_hash = await run_in_threadpool(self._password_hash.hash, password)
        user = UserRecord(email=normalize_email(email), password_hash=password_hash)
        try:
            async with self.session.begin_nested():
                self.session.add(user)
                await self.session.flush()
        except IntegrityError as exc:
            raise EmailAlreadyRegistered("email is already registered") from exc
        return user

    async def login(self, email: str, password: str) -> AuthenticatedSession:
        user = await self.session.scalar(
            select(UserRecord).where(UserRecord.email == normalize_email(email))
        )
        stored_hash = user.password_hash if user is not None else self._dummy_hash
        try:
            valid, updated_hash = await run_in_threadpool(
                self._password_hash.verify_and_update,
                password,
                stored_hash,
            )
        except UnknownHashError as exc:
            raise InvalidCredentials("invalid email or password") from exc
        if user is None or not user.is_active or not valid:
            raise InvalidCredentials("invalid email or password")
        if updated_hash is not None:
            user.password_hash = updated_hash

        raw_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(minutes=self.settings.session_ttl_minutes)
        self.session.add(
            SessionRecord(
                user_id=user.id,
                token_hash=self._token_digest(raw_token),
                expires_at=expires_at,
            )
        )
        await self.session.flush()
        return AuthenticatedSession(user=user, token=raw_token, expires_at=expires_at)

    async def current_user(self, raw_token: str | None) -> UserRecord | None:
        if not raw_token:
            return None
        return await self.session.scalar(
            select(UserRecord)
            .join(SessionRecord, SessionRecord.user_id == UserRecord.id)
            .where(
                SessionRecord.token_hash == self._token_digest(raw_token),
                SessionRecord.revoked_at.is_(None),
                SessionRecord.expires_at > datetime.now(UTC),
                UserRecord.is_active.is_(True),
            )
        )

    async def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        record = await self.session.scalar(
            select(SessionRecord).where(
                SessionRecord.token_hash == self._token_digest(raw_token),
                SessionRecord.revoked_at.is_(None),
            )
        )
        if record is not None:
            record.revoked_at = datetime.now(UTC)
            await self.session.flush()

    def _token_digest(self, raw_token: str) -> str:
        return hmac.new(
            self.settings.session_secret.get_secret_value().encode(),
            raw_token.encode(),
            sha256,
        ).hexdigest()
