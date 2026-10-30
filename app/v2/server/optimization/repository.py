"""RSI operation state in the existing managed-agent inventory."""

import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.v2.server.packages.orm import ManagedRecordRow as Row
from app.v2.server.packages.repository import key


class RsiRepository:
    lease_seconds = 60

    def __init__(self, packages):
        self.packages = packages

    async def by_request(self, owner, agent, request, digest):
        async with self.packages.database.session() as db:
            row = await self.packages._get(db, owner, "rsi_request", agent, request)
            if row is None:
                return None
            if row.payload["digest"] != digest:
                raise ValueError("RSI request_id conflict")
            return dict((await self._row(db, owner, agent, row.payload["run_id"])).payload)

    async def create(self, owner, agent, request, digest, value):
        try:
            return await self._create(owner, agent, request, digest, value)
        except IntegrityError:
            existing = await self.by_request(owner, agent, request, digest)
            if existing is None:
                raise
            return existing, False

    async def _create(self, owner, agent, request, digest, value):
        async with self.packages.transaction() as db:
            old = await self.packages._get(db, owner, "rsi_request", agent, request)
            if old is not None:
                if old.payload["digest"] != digest:
                    raise ValueError("RSI request_id conflict")
                row = await self._row(db, owner, agent, old.payload["run_id"])
                return dict(row.payload), False
            # Insert, rather than merge: a concurrent host must never replace
            # the first request's run identity after our initial read.
            db.add(Row(key=key(owner, "rsi_request", agent, request), owner=owner,
                kind="rsi_request", agent=agent, payload={"digest": digest, "run_id": value["id"]}))
            await db.flush()
            await self.packages._put(db, owner, "rsi_run", [agent, value["id"]], value,
                                     agent=agent, name=value.get("created_at", "") + value["id"])
            return dict(value), True

    async def _row(self, db, owner, agent, run, *, lock=False):
        query = select(Row).where(Row.key == key(owner, "rsi_run", agent, run),
                                  Row.owner == owner, Row.kind == "rsi_run", Row.agent == agent)
        row = await db.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise ValueError("RSI run not found")
        return row

    async def get(self, owner, agent, run):
        async with self.packages.database.session() as db:
            return dict((await self._row(db, owner, agent, run)).payload)

    async def list(self, owner, agent, *, limit=50, offset=0):
        async with self.packages.database.session() as db:
            rows = (await db.scalars(select(Row).where(Row.owner == owner, Row.kind == "rsi_run",
                Row.agent == agent).order_by(Row.name.desc()).limit(limit).offset(offset))).all()
            return [dict(row.payload) for row in rows]

    async def claim(self, owner, agent, run, token, *, now=None):
        now = time.time() if now is None else now
        async with self.packages.transaction() as db:
            row = await self._row(db, owner, agent, run, lock=True)
            value = dict(row.payload)
            if value.get("status") == "completed" or (
                value.get("status") == "running" and value.get("lease_until", 0) > now
            ):
                raise ValueError("RSI execution conflict: run is already active or completed")
            value.update(status="running", lease_token=token, lease_until=now + self.lease_seconds,
                         cancel_requested=False)
            row.payload = value
            return dict(value)

    async def update(self, owner, agent, run, token, changes):
        async with self.packages.transaction() as db:
            row = await self._row(db, owner, agent, run, lock=True)
            value = dict(row.payload)
            if value.get("lease_token") != token:
                raise ValueError("RSI execution lease lost")
            value.update(changes)
            row.payload = value
            return dict(value)

    async def cancel(self, owner, agent, run):
        async with self.packages.transaction() as db:
            row = await self._row(db, owner, agent, run, lock=True)
            value = dict(row.payload)
            if value.get("status") in {"queued", "running"}:
                value["cancel_requested"] = True
                if value.get("status") == "queued":
                    value["status"] = "interrupted"
                row.payload = value
            return dict(value)
