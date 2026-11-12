"""Best-effort diagnostic evidence backed by the Server database."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from hashlib import sha256
import json

from sqlalchemy import cast, delete, func, select, text, tuple_, update
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.exc import SQLAlchemyError

from app.v2.server.database.upsert import upsert
from .orm import dropped, logs, models
from .writer import ObservationWriter
from sagents.v2.runtime.observability.evidence.capture import DiagnosticCapture
from sagents.v2.runtime.observability.evidence.raw import retained_size
from sagents.v2.runtime.observability.evidence.tools import tool_evidence
from sagents.v2.runtime.observability.performance.aggregation import timestamp


def _scope(table, session_id, run_id):
    return table.c.session_id == session_id, table.c.run_id == run_id


MODEL_KEY = ("session_id", "run_id", "request_id")


def _model_scope(key):
    return dict(zip(MODEL_KEY, key))


def _earlier(observed, existing):
    return observed is not None and (existing is None or observed < existing)


class DatabaseDiagnostics(DiagnosticCapture):
    max_pending_writes = 4096
    max_pending_evidence_bytes = 64 * 1024 * 1024

    def __init__(self, database):
        self.database = database
        self.available = True
        self._evidence_writer = ObservationWriter(
            self._write_evidence, batch_size=64, max_bytes=self.max_pending_evidence_bytes,
            batch_bytes=8 * 1024 * 1024,
        )

    @property
    def capture_failures(self):
        return self._evidence_writer.failures

    async def _flush(self):
        return await self._evidence_writer.flush()

    async def close(self):
        await self._evidence_writer.close()

    def write(self, record):
        if record.session_id and record.run_id:
            self._enqueue_evidence(None, record)

    def _record_model_change(self, session_id, request, change):
        self._enqueue_evidence((session_id, request.run_id, request.request_id), change)

    def _enqueue_evidence(self, key, payload):
        value = key, payload
        try:
            size = retained_size(value, self.max_pending_evidence_bytes) + 256
        except RecursionError:
            self._evidence_writer.record_failure()
            return
        self._evidence_writer.enqueue(value, limit=self.max_pending_writes, key=key, size=size)

    def _prepare_evidence(self, batch):
        changes, log_rows = defaultdict(list), []
        for key, value in batch:
            if key is None:
                try:
                    payload = self._encode(value.model_dump(mode="json"))
                except (ValueError, TypeError):
                    self._evidence_writer.record_failure()
                    continue
                log_rows.append({
                    "session_id": value.session_id, "run_id": value.run_id, "payload": payload,
                })
            else:
                changes[key].append(value)
        return changes, log_rows

    def _merge_model_payloads(self, changes, previous, *, digest):
        rows = {}
        for key, patches in changes.items():
            payload = previous.get(key, "{}")
            record = json.loads(payload)
            changed = False
            for patch in patches:
                terminal = record.get("status") in {"completed", "failed"}
                if "started_at" in patch:
                    if not _earlier(timestamp(patch["started_at"]), timestamp(record.get("started_at"))):
                        continue
                    if terminal:
                        patch = {field: value for field, value in patch.items() if field != "status"}
                elif "completed_at" in patch and terminal:
                    continue
                elif "first_token_at" in patch and not _earlier(
                    timestamp(patch["first_token_at"]), timestamp(record.get("first_token_at")),
                ):
                    continue
                record.update(patch)
                changed = True
            if changed:
                token = sha256(payload.encode()).hexdigest() if digest else payload
                rows[key] = self._encode({**record, **_model_scope(key)}), token
        return rows

    async def _write_evidence(self, batch):
        changes, log_rows = await asyncio.to_thread(self._prepare_evidence, batch)
        # A concurrent writer may commit between the read and the update. The
        # original payload determines the CAS token, including for pre-existing rows.
        for _ in range(3):
            previous = {}
            mysql = False
            if changes:
                async with self.database.session() as db:
                    mysql = db.get_bind().dialect.name == "mysql"
                    result = await db.execute(select(models).where(
                        tuple_(*(models.c[name] for name in MODEL_KEY)).in_(list(changes)),
                    ))
                    previous = {
                        (row.session_id, row.run_id, row.request_id): row.payload for row in result
                    }
            rows = await asyncio.to_thread(self._merge_model_payloads, changes, previous, digest=mysql)
            if not rows and not log_rows:
                return

            async def write(db):
                missing = [_model_scope(key) | {"payload": "{}"}
                           for key in sorted(rows) if key not in previous]
                if missing:
                    await upsert(db, models, missing, key=MODEL_KEY)
                # MySQL sends a whole statement in one packet. Bind a digest
                # to keep large updates within one payload's wire size.
                version = models.c.payload
                if mysql:
                    version = func.sha2(cast(version, CHAR(charset="utf8mb4")), 256)
                conflicts = {}
                for key in sorted(rows):
                    session_id, run_id, request_id = key
                    payload, token = rows[key]
                    result = await db.execute(update(models).where(
                        *_scope(models, session_id, run_id), models.c.request_id == request_id,
                        version == token,
                    ).values(payload=payload))
                    if not result.rowcount:
                        conflicts[key] = changes[key]
                if log_rows:
                    await self._write_logs(db, log_rows)
                return conflicts

            changes = await self.database.run_transaction(write)
            log_rows = []
            if not changes:
                return
        raise RuntimeError("concurrent diagnostic updates did not settle")

    async def _write_logs(self, db, rows):
        scopes = sorted({(row["session_id"], row["run_id"]) for row in rows})
        await upsert(db, dropped, [
            {"session_id": session, "run_id": run, "count": 0} for session, run in scopes
        ], key=("session_id", "run_id"))
        # Serialize retention across writers on the existing per-Run counter.
        await db.execute(select(dropped.c.count).where(
            tuple_(dropped.c.session_id, dropped.c.run_id).in_(scopes),
        ).order_by(dropped.c.session_id, dropped.c.run_id).with_for_update())
        await db.execute(logs.insert(), rows)
        cutoff_query = select(logs.c.id).where(
            logs.c.session_id == dropped.c.session_id, logs.c.run_id == dropped.c.run_id,
        ).order_by(logs.c.id.desc()).offset(self.max_logs_per_run).limit(1).scalar_subquery()
        cutoffs = await db.execute(select(dropped.c.session_id, dropped.c.run_id, cutoff_query).where(
            tuple_(dropped.c.session_id, dropped.c.run_id).in_(scopes),
        ))
        for session_id, run_id, cutoff in cutoffs:
            if cutoff is not None:
                removed = await db.execute(delete(logs).where(
                    *_scope(logs, session_id, run_id), logs.c.id <= cutoff,
                ))
                await db.execute(update(dropped).where(*_scope(dropped, session_id, run_id)).values(
                    count=dropped.c.count + removed.rowcount,
                ))

    @asynccontextmanager
    async def _read_snapshot(self):
        async with self.database.session() as db:
            if db.get_bind().dialect.name == "sqlite":
                await db.execute(text("BEGIN"))
            else:
                await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            yield db

    async def export_evidence(self, session_id: str, run_ids: set[str]):
        flushed = await self._flush()
        model_rows, log_rows, dropped_count = [], [], 0
        try:
            ids = sorted(run_ids)
            async with self._read_snapshot() as db:
                for offset in range(0, len(ids), 400):
                    batch = ids[offset:offset + 400]
                    model_rows.extend(await db.scalars(select(models.c.payload).where(
                        models.c.session_id == session_id, models.c.run_id.in_(batch),
                    )))
                    log_rows.extend(await db.scalars(select(logs.c.payload).where(
                        logs.c.session_id == session_id, logs.c.run_id.in_(batch),
                    ).order_by(logs.c.run_id, logs.c.id)))
                    batch_dropped = await db.scalar(select(func.sum(dropped.c.count)).where(
                        dropped.c.session_id == session_id, dropped.c.run_id.in_(batch),
                    ))
                    dropped_count += int(batch_dropped or 0)
            return await asyncio.to_thread(self._evidence, model_rows, log_rows, dropped_count, flushed)
        except (SQLAlchemyError, ValueError):
            return {"models": [], "logs": [], "unavailable": True,
                    "capture_failures_since_start": self.capture_failures}

    def _evidence(self, model_rows, log_rows, dropped_count, flushed):
        model_rows = [json.loads(row) for row in model_rows]
        log_rows = [json.loads(row) for row in log_rows]
        model_rows.sort(key=lambda row: (row.get("started_at", ""), row.get("request_id", "")))
        for index, row in enumerate(model_rows, 1):
            row["sequence"] = index
        result = {"models": model_rows, "logs": log_rows, "dropped_logs": dropped_count,
                  "capture_failures_since_start": self.capture_failures,
                  **tool_evidence([], log_rows)}
        if not flushed:
            result["pending_writes"] = True
        return result
