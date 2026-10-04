"""Transactional idempotency reservations for resource-creating requests."""

import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ops_agent.persistence.models import IdempotencyRecord
from ops_agent.persistence.repositories import AuthorizationSubject


class IdempotencyError(RuntimeError):
    """Base class for safe idempotency failures."""


class IdempotencyConflict(IdempotencyError):
    """The same key was reused with a different request body."""


class IdempotencyInProgress(IdempotencyError):
    """A concurrent request still owns the reservation."""


@dataclass(frozen=True)
class IdempotencyReservation:
    record: IdempotencyRecord
    is_new: bool

    @property
    def response_payload(self) -> dict[str, Any]:
        if self.record.response_payload is None:
            raise IdempotencyInProgress("idempotent request is still in progress")
        return self.record.response_payload


def request_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()


class IdempotencyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reserve(
        self,
        subject: AuthorizationSubject,
        *,
        scope: str,
        key: str,
        request_payload: dict[str, Any],
    ) -> IdempotencyReservation:
        request_hash = request_payload_hash(request_payload)
        existing = await self._get(subject, scope, key)
        if existing is not None:
            return self._replay_or_conflict(existing, request_hash)

        record = IdempotencyRecord(
            owner_id=subject.user_id,
            scope=scope,
            idempotency_key=key,
            request_hash=request_hash,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(record)
                await self.session.flush()
        except IntegrityError:
            concurrent = await self._get(subject, scope, key)
            if concurrent is None:
                raise
            return self._replay_or_conflict(concurrent, request_hash)
        return IdempotencyReservation(record=record, is_new=True)

    async def complete(
        self,
        reservation: IdempotencyReservation,
        *,
        resource_type: str,
        resource_id: str,
        response_status: int,
        response_payload: dict[str, Any],
    ) -> None:
        if not reservation.is_new or reservation.record.state != "in_progress":
            raise IdempotencyConflict("idempotency reservation cannot be completed")
        reservation.record.state = "completed"
        reservation.record.resource_type = resource_type
        reservation.record.resource_id = resource_id
        reservation.record.response_status = response_status
        reservation.record.response_payload = response_payload
        reservation.record.completed_at = datetime.now(UTC)
        await self.session.flush()

    async def _get(
        self,
        subject: AuthorizationSubject,
        scope: str,
        key: str,
    ) -> IdempotencyRecord | None:
        return await self.session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.owner_id == subject.user_id,
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.idempotency_key == key,
            )
        )

    @staticmethod
    def _replay_or_conflict(
        record: IdempotencyRecord,
        request_hash: str,
    ) -> IdempotencyReservation:
        if not hmac_compare(record.request_hash, request_hash):
            raise IdempotencyConflict(
                "idempotency key was already used with a different request body"
            )
        if record.state != "completed" or record.response_payload is None:
            raise IdempotencyInProgress("idempotent request is still in progress")
        return IdempotencyReservation(record=record, is_new=False)


def hmac_compare(left: str, right: str) -> bool:
    """Keep digest comparisons constant-time even though hashes are not secret."""
    return hmac.compare_digest(left, right)
