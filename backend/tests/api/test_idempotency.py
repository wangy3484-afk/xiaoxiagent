"""Idempotent resource creation API tests."""

import pytest
from ops_agent.persistence.models import (
    BriefRevisionRecord,
    IdempotencyRecord,
    OperationsBriefRecord,
)
from sqlalchemy import func, select

from api.support import api_test_context, register_and_login


@pytest.mark.asyncio
async def test_same_user_key_and_body_create_exactly_one_brief() -> None:
    async with api_test_context() as context:
        await register_and_login(context.client)
        payload = {
            "brief_payload": {"operation_goal": "提高新用户次日留存"},
            "classification_payload": {"primary_scene": "retention"},
        }
        headers = {"Idempotency-Key": "brief-create-001"}

        first = await context.client.post("/api/v1/briefs", json=payload, headers=headers)
        replay = await context.client.post("/api/v1/briefs", json=payload, headers=headers)

        assert first.status_code == 201
        assert replay.status_code == 201
        assert replay.json() == first.json()
        assert replay.headers["Idempotency-Replayed"] == "true"

        async with context.session_factory() as session:
            brief_count = await session.scalar(select(func.count(OperationsBriefRecord.id)))
            revision_count = await session.scalar(select(func.count(BriefRevisionRecord.id)))
            idempotency_count = await session.scalar(select(func.count(IdempotencyRecord.id)))
            record = await session.scalar(select(IdempotencyRecord))
            assert brief_count == 1
            assert revision_count == 1
            assert idempotency_count == 1
            assert record is not None
            assert record.state == "completed"
            assert record.resource_id == first.json()["id"]


@pytest.mark.asyncio
async def test_same_user_key_with_different_body_returns_conflict() -> None:
    async with api_test_context() as context:
        await register_and_login(context.client)
        headers = {"Idempotency-Key": "brief-create-002"}
        first_payload = {
            "brief_payload": {"operation_goal": "提高拉新"},
            "classification_payload": {"primary_scene": "acquisition"},
        }
        changed_payload = {
            "brief_payload": {"operation_goal": "提高留存"},
            "classification_payload": {"primary_scene": "retention"},
        }

        first = await context.client.post(
            "/api/v1/briefs", json=first_payload, headers=headers
        )
        conflict = await context.client.post(
            "/api/v1/briefs", json=changed_payload, headers=headers
        )

        assert first.status_code == 201
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
        async with context.session_factory() as session:
            brief_count = await session.scalar(select(func.count(OperationsBriefRecord.id)))
            assert brief_count == 1
