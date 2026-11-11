"""Best-effort diagnostic evidence backed by the Server database."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from hashlib import sha256
import json

from sqlalchemy import case, cast, delete, func, or_, select, text, tuple_, update
from sqlalchemy.dialects.mysql import CHAR
from sqlalchemy.exc import SQLAlchemyError

from app.v2.server.database.upsert import upsert
from .orm import dropped, events, logs, models, timings
from .writer import ObservationWriter
from sagents.v2.runtime.observability.evidence.capture import DiagnosticCapture
from sagents.v2.runtime.observability.evidence.tools import tool_evidence
from sagents.v2.runtime.observability.performance.aggregation import EVENTS, build_run, timestamp, timing_report
from sagents.v2.runtime.observability.performance.projection import log_timings, model_timing


def _scope(table, session_id, run_id):
    return table.c.session_id == session_id, table.c.run_id == run_id


MODEL_KEY = ("session_id", "run_id", "request_id")


def _model_scope(key):
    return dict(zip(MODEL_KEY, key))


def _earlier(observed, existing):
    return observed is not None and (existing is None or observed < existing)


def _earlier_sql(observed, existing):
    return observed.is_not(None) & (existing.is_(None) | (observed < existing))


def _timing_changes(incoming):
    current = timings.c
    earlier_start = _earlier_sql(incoming.started_at, current.started_at)
    earlier_token = _earlier_sql(incoming.first_token_at, current.first_token_at)
    return {
        "purpose": case((earlier_start, incoming.purpose), else_=current.purpose),
        "turn_id": case((earlier_start, incoming.turn_id), else_=current.turn_id),
        "started_at": case((earlier_start, incoming.started_at), else_=current.started_at),
        "first_token_at": case((earlier_token, incoming.first_token_at), else_=current.first_token_at),
        "ended_at": func.coalesce(current.ended_at, incoming.ended_at),
    }


class DatabaseDiagnostics(DiagnosticCapture):
    max_pending_timings = 4096

    def __init__(self, database):
        self.database = database
        self.available = True
        self._timings = ObservationWriter(self._write_timings, batch_size=64)
        self._evidence_writer = ObservationWriter(self._write_evidence, batch_size=16)

    @property
    def capture_failures(self):
        return self._timings.failures + self._evidence_writer.failures

    async def _flush(self):
        evidence, timing = await asyncio.gather(
            self._evidence_writer.flush(), self._timings.flush(),
        )
        return evidence and timing

    async def close(self):
        await asyncio.gather(self._evidence_writer.close(), self._timings.close())

    def write(self, record):
        if not record.session_id or not record.run_id:
            return
        if record.event in EVENTS:
            try:
                projections = tuple(log_timings({
                    "event": record.event, "timestamp": record.timestamp,
                    "session_id": record.session_id, "run_id": record.run_id,
                    "turn_id": record.turn_id, "tool_call_id": record.tool_call_id,
                    "request_id": record.request_id, "attributes": record.attributes,
                }))
            except (ValueError, TypeError, OverflowError):
                self._timings.record_failure()
            else:
                self._timings.enqueue((None, projections), limit=self.max_pending_timings)
        self._evidence_writer.enqueue((None, record), limit=self.max_pending_writes)

    def _record_model_change(self, session_id, request, change):
        key = session_id, request.run_id, request.request_id
        if any(field in change for field in ("started_at", "completed_at", "first_token_at")):
            self._timings.enqueue(
                (key, model_timing({**_model_scope(key), **change})),
                limit=self.max_pending_timings,
            )
        self._evidence_writer.enqueue((key, change), limit=self.max_pending_writes)

    async def _write_timings(self, batch):
        requests, stages = {}, {}
        for key, value in batch:
            if key is None:
                stages.update((event["id"], event) for event in value)
                continue
            previous = requests.get(key)
            if previous is None:
                requests[key] = value
                continue
            if _earlier(value["started_at"], previous["started_at"]):
                for field in ("started_at", "purpose", "turn_id"):
                    previous[field] = value[field]
            if _earlier(value["first_token_at"], previous["first_token_at"]):
                previous["first_token_at"] = value["first_token_at"]
            if previous["ended_at"] is None:
                previous["ended_at"] = value["ended_at"]

        async def write(db):
            if requests:
                await upsert(db, timings, [requests[key] for key in sorted(requests)],
                             key=MODEL_KEY, merge=_timing_changes)
            if stages:
                await upsert(db, events, [stages[key] for key in sorted(stages)], key="id")

        await self.database.run_transaction(write)

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
        for session_id, run_id in scopes:
            match = _scope(logs, session_id, run_id)
            cutoff = await db.scalar(select(logs.c.id).where(*match).order_by(
                logs.c.id.desc()
            ).offset(self.max_logs_per_run).limit(1))
            if cutoff is not None:
                removed = await db.execute(delete(logs).where(*match, logs.c.id <= cutoff))
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

    async def run_timing(self, *, session_id, run_id, start, end):
        await self._timings.flush()
        async with self._read_snapshot() as db:
            event_rows = (await db.execute(select(events).where(*_scope(events, session_id, run_id))
                                           .limit(10001))).mappings().all()
            if not event_rows or len(event_rows) > 10000:
                return None
            model_rows = (await db.execute(select(timings).where(*_scope(timings, session_id, run_id))
                                           .limit(10001))).mappings().all()
        if len(model_rows) <= 10000:
            return build_run(event_rows, model_rows, include_timeline=True)
        return None

    async def report(self, *, start, end, agent_id="", bucket="hour", timezone_name="Asia/Shanghai",
                     max_runs=10000, max_timing_rows=100000):
        flushed = await self._timings.flush()
        event = events.c
        accepted = event.event == "server.run.performance.accepted"
        cohort = case((accepted, event.started_at), else_=event.at)
        candidates = select(event.session_id, event.run_id).where(or_(
            (event.event == "agent.run.started") & (event.at >= start) & (event.at < end),
            accepted & (event.started_at >= start) & (event.started_at < end),
        ))
        if agent_id:
            candidates = candidates.where(event.agent_id == agent_id)
        candidates = candidates.group_by(event.session_id, event.run_id).order_by(func.min(cohort).desc()).limit(max_runs + 1)
        by_event, by_model = defaultdict(list), defaultdict(list)
        async with self.database.session() as db:
            ids = (await db.execute(candidates)).all()
            truncated = len(ids) > max_runs
            remaining = max_timing_rows
            ids = ids[:max_runs]
            for offset in range(0, len(ids), 400):
                batch = ids[offset:offset + 400]
                event_rows = (await db.execute(select(events).where(tuple_(events.c.session_id, events.c.run_id).in_(batch))
                                               .limit(remaining + 1))).mappings().all()
                if len(event_rows) > remaining:
                    truncated = True
                    break
                model_rows = (await db.execute(select(timings).where(tuple_(timings.c.session_id, timings.c.run_id).in_(batch))
                                               .limit(remaining - len(event_rows) + 1))).mappings().all()
                remaining -= len(event_rows) + len(model_rows)
                if remaining < 0:
                    truncated = True
                    break
                for row in event_rows:
                    by_event[row["session_id"], row["run_id"]].append(row)
                for row in model_rows:
                    by_model[row["session_id"], row["run_id"]].append(row)
        result = await asyncio.to_thread(
            timing_report, by_event, by_model, start=start, end=end, agent_id=agent_id,
            bucket=bucket, timezone_name=timezone_name, truncated=truncated,
        )
        return {**result, "source": "local", "capture_failures": self._timings.failures + int(not flushed)}
