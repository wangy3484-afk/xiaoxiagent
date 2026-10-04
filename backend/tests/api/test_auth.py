"""Authentication API integration tests."""

from datetime import UTC, datetime, timedelta

import pytest
from ops_agent.persistence.models import SessionRecord, UserRecord
from pwdlib import PasswordHash
from sqlalchemy import select, update

from api.support import api_test_context

EMAIL = "operator@example.com"
PASSWORD = "correct-horse-battery-staple"


@pytest.mark.asyncio
async def test_registration_login_and_cookie_security_properties() -> None:
    async with api_test_context() as context:
        credentials = {"email": f"  {EMAIL.upper()}  ", "password": PASSWORD}
        registered = await context.client.post("/api/v1/auth/register", json=credentials)
        assert registered.status_code == 201
        assert registered.json()["email"] == EMAIL

        async with context.session_factory() as session:
            user = await session.scalar(select(UserRecord).where(UserRecord.email == EMAIL))
            assert user is not None
            assert user.password_hash.startswith("$argon2id$")
            assert PasswordHash.recommended().verify(PASSWORD, user.password_hash)
            assert PASSWORD not in user.password_hash

        login = await context.client.post("/api/v1/auth/login", json=credentials)
        assert login.status_code == 200
        cookie = login.headers["set-cookie"].lower()
        assert "secure" in cookie
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert "path=/" in cookie
        assert "max-age=3600" in cookie

        current = await context.client.get("/api/v1/auth/me")
        assert current.status_code == 200
        assert current.json() == registered.json()


@pytest.mark.asyncio
async def test_wrong_password_and_unknown_email_share_safe_error() -> None:
    async with api_test_context() as context:
        await context.client.post(
            "/api/v1/auth/register",
            json={"email": EMAIL, "password": PASSWORD},
        )
        wrong_password = await context.client.post(
            "/api/v1/auth/login",
            json={"email": EMAIL, "password": "another-long-password"},
        )
        unknown_email = await context.client.post(
            "/api/v1/auth/login",
            json={"email": "missing@example.com", "password": "another-long-password"},
        )

        assert wrong_password.status_code == 401
        assert unknown_email.status_code == 401
        assert wrong_password.json() == unknown_email.json()
        assert wrong_password.json()["detail"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_expired_session_is_rejected() -> None:
    async with api_test_context() as context:
        credentials = {"email": EMAIL, "password": PASSWORD}
        await context.client.post("/api/v1/auth/register", json=credentials)
        await context.client.post("/api/v1/auth/login", json=credentials)

        async with context.session_factory() as session:
            await session.execute(
                update(SessionRecord).values(
                    expires_at=datetime.now(UTC) - timedelta(minutes=1)
                )
            )
            await session.commit()

        response = await context.client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.asyncio
async def test_logout_revokes_server_session_and_clears_cookie() -> None:
    async with api_test_context() as context:
        credentials = {"email": EMAIL, "password": PASSWORD}
        await context.client.post("/api/v1/auth/register", json=credentials)
        await context.client.post("/api/v1/auth/login", json=credentials)

        response = await context.client.post("/api/v1/auth/logout")
        assert response.status_code == 204
        cookie = response.headers["set-cookie"].lower()
        assert "max-age=0" in cookie
        assert "secure" in cookie
        assert "httponly" in cookie
        assert "samesite=lax" in cookie

        current = await context.client.get("/api/v1/auth/me")
        assert current.status_code == 401

        async with context.session_factory() as session:
            server_session = await session.scalar(select(SessionRecord))
            assert server_session is not None
            assert server_session.revoked_at is not None
