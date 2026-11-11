"""Server persistence for Agent defaults, frozen Run revisions and operation receipts."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.v2.server.database.base import Base
from app.v2.server.database.upsert import upsert
from sagents.v2.agent.self_configuration.revision import apply_revision


class SelfConfigurationRecord(Base):
    __tablename__ = "agent_self_configuration_records"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


def record_key(owner, kind, *parts):
    return hashlib.sha256(json.dumps([owner, kind, *parts]).encode()).hexdigest()


class DatabaseSelfConfigurationStore:
    def __init__(self, database):
        self.database = database

    async def _lock_defaults(self, db, owner):
        key = record_key(owner, "defaults")
        await upsert(
            db, SelfConfigurationRecord.__table__,
            {"key": key, "payload": {"revision": 0, "skills": {}, "mcp_servers": {}}},
            key="key",
        )
        return await db.get(SelfConfigurationRecord, key, with_for_update=True)

    async def read(self, owner, run_id, *, create=True):
        key = record_key(owner, "run", run_id)
        async with self.database.session() as db:
            row = await db.get(SelfConfigurationRecord, key)
            if row is not None:
                return row.payload
        if not create:
            raise ValueError("saved Run capability revision is missing")
        async with self.database.transaction() as db:
            defaults = await self._lock_defaults(db, owner)
            row = await db.get(SelfConfigurationRecord, key)
            if row is not None:
                return row.payload
            snapshot = deepcopy(defaults.payload)
            db.add(SelfConfigurationRecord(key=key, payload=snapshot))
            return snapshot

    async def receipt(self, owner, run_id, operation):
        async with self.database.session() as db:
            row = await db.get(SelfConfigurationRecord, record_key(owner, "operation", run_id, operation))
            if row is not None:
                return row.payload["fingerprint"], row.payload["result"]
            return None

    async def commit(
        self, owner, run_id, operation, fingerprint, expected_revision, skills, servers, *, system_prompt=None
    ):
        async with self.database.transaction() as db:
            defaults = await self._lock_defaults(db, owner)
            key = record_key(owner, "operation", run_id, operation)
            receipt = await db.get(SelfConfigurationRecord, key)
            if receipt is not None:
                if receipt.payload["fingerprint"] != fingerprint:
                    raise ValueError("self configuration operation conflicts with an earlier request")
                return receipt.payload["result"]

            run = await db.get(SelfConfigurationRecord, record_key(owner, "run", run_id))
            if run is None:
                raise ValueError("saved Run capability revision is missing")
            current, future = deepcopy(run.payload), deepcopy(defaults.payload)
            result = apply_revision(current, future, expected_revision, skills, servers, system_prompt)
            run.payload = current
            defaults.payload = future
            db.add(SelfConfigurationRecord(key=key, payload={"fingerprint": fingerprint, "result": result}))
            return result
