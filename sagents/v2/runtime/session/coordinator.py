# pyright: strict
"""Per-Session CAS and idempotency coordination over a repository."""

from __future__ import annotations

import asyncio
import hashlib
import json

from sagents.v2.runtime.session.aggregate import SessionAggregate
from sagents.v2.runtime.session.journal import SessionStateDeltaMutation
from sagents.v2.runtime.session.repository import SessionRepository


class SessionStoreCoordinator:
    def __init__(self, repository: SessionRepository) -> None:
        self.repository = repository
        self._locks: dict[str, asyncio.Lock] = {}

    async def load(self, session_id: str) -> SessionAggregate | None:
        async with self._lock(session_id):
            return await self.repository.load(session_id)

    async def commit(
        self,
        session_id: str,
        *,
        expected_revision: int,
        idempotency_key: str,
        mutation: SessionStateDeltaMutation,
    ) -> SessionAggregate:
        async with self._lock(session_id):
            current = await self.repository.load(session_id)
            if current is None:
                raise KeyError(session_id)
            digest = self._digest(mutation)
            duplicate = next(
                (
                    value
                    for value in current.snapshot.coordinator_command_results
                    if value.idempotency_key == idempotency_key
                ),
                None,
            )
            if duplicate is not None:
                if duplicate.request_digest != digest:
                    raise ValueError(
                        "idempotency key was already used for a different mutation"
                    )
                return current
            if current.revision != expected_revision:
                raise ValueError(
                    f"Session revision conflict: expected {expected_revision}, "
                    f"got {current.revision}"
                )
            values = {
                key: list(rows) for key, rows in mutation.upserts.items()
            }
            values.setdefault("coordinator_command_results", []).append(
                {
                    "idempotency_key": idempotency_key,
                    "request_digest": digest,
                    "result_revision": expected_revision + 1,
                }
            )
            updated = current.apply(mutation.model_copy(update={"upserts": values}))
            if updated.revision <= current.revision:
                raise ValueError("Session mutation must advance the revision")
            await self.repository.commit(updated)
            return updated

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    @staticmethod
    def _digest(mutation: SessionStateDeltaMutation) -> str:
        encoded = json.dumps(
            mutation.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
