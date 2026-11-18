"""Best-effort diagnostic evidence backed by the Server database."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from hashlib import sha256
import json
from pathlib import Path
import time

from sqlalchemy import cast, delete, func, or_, select, text, tuple_, update
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.exc import SQLAlchemyError

from app.v2.server.database.upsert import upsert
from .orm import dropped, logs, models, expiry, events, timings, maintenance_lock
from .evidence_storage import EvidenceStorage
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
    max_storage_bytes = 4 * 1024 * 1024 * 1024

    def __init__(self, database, evidence_root: Path):
        self.database = database
        self.storage = EvidenceStorage(evidence_root)
        self.available = True
        self._evidence_writer = ObservationWriter(
            self._write_evidence, batch_size=64, max_bytes=self.max_pending_evidence_bytes,
            batch_bytes=8 * 1024 * 1024,
        )
        self._maintenance = asyncio.create_task(self._maintain())

    @property
    def capture_failures(self):
        return self._evidence_writer.failures

    async def _flush(self):
        return await self._evidence_writer.flush()

    async def close(self):
        self._maintenance.cancel()
        await asyncio.gather(self._maintenance, return_exceptions=True)
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
            if record.get("evidence_expired"):
                continue
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
                record.setdefault("capture_mode", "raw" if payload == "{}" else "legacy")
                record = self.storage.pack(key, {**record, **_model_scope(key)})
                rows[key] = self._encode(record, redact_content=False), token
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
                    else:
                        record = json.loads(payload)
                        observed = timestamp(record.get("completed_at")) or timestamp(record.get("started_at")) or time.time()
                        days = 3 if record.get("status") == "completed" else 7
                        await upsert(db, expiry, [{
                            **_model_scope(key), "expires_at": observed + days * 86400,
                            "summary_expires_at": observed + 30 * 86400,
                        }], key=MODEL_KEY, merge=lambda incoming: {
                            "expires_at": incoming.expires_at,
                            "summary_expires_at": incoming.summary_expires_at,
                        })
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
        except (SQLAlchemyError, ValueError, OSError):
            return {"models": [], "logs": [], "unavailable": True,
                    "capture_failures_since_start": self.capture_failures}

    def _evidence(self, model_rows, log_rows, dropped_count, flushed):
        restored = []
        for encoded in model_rows:
            row = json.loads(encoded)
            key = tuple(row[name] for name in MODEL_KEY)
            try:
                restored.append(self.storage.unpack(key, row))
            except (OSError, ValueError):
                row.pop("_parts", None)
                row.pop("_storage", None)
                row["evidence_unavailable"] = True
                restored.append(row)
        model_rows = restored
        log_rows = [json.loads(row) for row in log_rows]
        model_rows.sort(key=lambda row: (row.get("started_at", ""), row.get("request_id", "")))
        for index, row in enumerate(model_rows, 1):
            row["sequence"] = index
        result = {"source": "local", "raw_model_evidence": True, "capture_modes": ["raw", "redacted"],
                  "models": model_rows, "logs": log_rows, "dropped_logs": dropped_count,
                  "capture_failures_since_start": self.capture_failures,
                  **tool_evidence([], log_rows)}
        if not flushed:
            result["pending_writes"] = True
        return result

    async def _maintain(self):
        from .logging import get_logger

        while True:
            await asyncio.sleep(60)
            try:
                await self.prune()
            except Exception as exc:
                get_logger(__name__).exception(
                    "diagnostics.retention.failed", "Diagnostic retention will retry", exc,
                )

    async def prune(self, *, now=None):
        now = time.time() if now is None else now
        removed = []
        async def write(db):
            # Re-evaluate the budget after acquiring the shared SQL lock. During
            # rolling deployment two processes must not spend the same eviction
            # budget against different records.
            await upsert(db, maintenance_lock, [{"id": "retention"}], key="id")
            await db.execute(select(maintenance_lock.c.id).where(
                maintenance_lock.c.id == "retention",
            ).with_for_update())
            removed.clear()
            payloads = list(await db.scalars(select(models.c.payload).join(
                expiry, tuple_(*(models.c[n] for n in MODEL_KEY)) == tuple_(*(expiry.c[n] for n in MODEL_KEY)),
            )))
            usage = await asyncio.to_thread(self._file_usage, payloads)
            budget_excess = max(0, sum(usage.values()) - self.max_storage_bytes)
            identity = tuple_(*(models.c[n] for n in MODEL_KEY))
            retention_identity = tuple_(*(expiry.c[n] for n in MODEL_KEY))
            rows = (await db.execute(select(models).join(
                expiry, identity == retention_identity,
            ).where(expiry.c.expires_at > 0, or_(expiry.c.expires_at < now, budget_excess > 0))
              .order_by(expiry.c.expires_at).limit(100).with_for_update())).mappings().all()
            for row in rows:
                key = tuple(row[n] for n in MODEL_KEY)
                record = json.loads(row["payload"])
                expired = now >= (await db.scalar(select(expiry.c.expires_at).where(retention_identity == key)))
                if not expired and (budget_excess <= 0 or record.get("status") not in {"completed", "failed"}):
                    continue
                record.pop("_parts", None)
                record.pop("_storage", None)
                for name in ("request", "response", "stream", "error", "metadata", "request_metadata"):
                    record.pop(name, None)
                record["evidence_expired"] = True
                record["evidence_expired_reason"] = "retention" if expired else "storage_budget"
                result = await db.execute(update(models).where(
                    identity == key, models.c.payload == row["payload"],
                ).values(payload=json.dumps(record, ensure_ascii=False)))
                if result.rowcount:
                    await db.execute(update(expiry).where(retention_identity == key).values(expires_at=-1))
                    removed.append(key)
                    budget_excess -= usage.get(str(self.storage.directory(key)), 0)
            summaries = (await db.execute(select(expiry).where(
                expiry.c.summary_expires_at < now,
            ).limit(100).with_for_update())).mappings().all()
            for row in summaries:
                key = tuple(row[n] for n in MODEL_KEY)
                await db.execute(delete(models).where(identity == key))
                await db.execute(delete(expiry).where(retention_identity == key))
                if not await db.scalar(select(models.c.request_id).where(*_scope(models, *key[:2])).limit(1)):
                    await db.execute(delete(logs).where(*_scope(logs, *key[:2])))
                    await db.execute(delete(dropped).where(*_scope(dropped, *key[:2])))
                removed.append(key)
            cutoff = now - 30 * 86400
            for table, column, key_columns in (
                (events, events.c.at, (events.c.id,)),
                (timings, timings.c.started_at, tuple(timings.c[n] for n in MODEL_KEY)),
            ):
                old = (await db.execute(select(*key_columns).where(column < cutoff).limit(500))).all()
                if old:
                    await db.execute(delete(table).where(tuple_(*key_columns).in_(old)))

        await self.database.run_transaction(write)
        async with self.database.session() as db:
            payloads = list(await db.scalars(select(models.c.payload).join(
                expiry, tuple_(*(models.c[n] for n in MODEL_KEY)) == tuple_(*(expiry.c[n] for n in MODEL_KEY)),
            )))
        await asyncio.to_thread(self._remove_expired_files, payloads)
        return len(removed)

    def _file_usage(self, payloads=None):
        usage = defaultdict(int)
        if payloads is None:
            paths = self.storage.root.glob("*/*/*")
        else:
            # Files awaiting the orphan grace period have already been evicted.
            # Counting them again would evict another set on every maintenance pass.
            paths = set()
            for payload in payloads:
                record = json.loads(payload)
                key = tuple(record[n] for n in MODEL_KEY)
                paths.update(self.storage.path(key, digest) for digest in record.get("_parts", {}).values())
        for path in paths:
            if path.is_file():
                try:
                    size = path.stat().st_size
                except FileNotFoundError:
                    # Another Server process may have collected this orphan.
                    continue
                usage[str(path.parent)] += size
        return usage

    def _remove_expired_files(self, payloads):
        referenced = set()
        for payload in payloads:
            row = json.loads(payload)
            key = tuple(row[n] for n in MODEL_KEY)
            referenced.update(self.storage.path(key, digest) for digest in row.get("_parts", {}).values())
        cutoff = time.time() - 3600
        for path in self.storage.root.glob("*/*/*"):
            # Grace protects parts staged by other processes before SQL commit,
            # as well as readers that opened an older SQL snapshot.
            if path not in referenced and path.is_file():
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except FileNotFoundError:
                    continue
