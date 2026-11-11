"""Best-effort diagnostic evidence backed by the Server database."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from concurrent.futures import Future
from contextlib import asynccontextmanager
from contextvars import Context
import json
from threading import Lock

from sqlalchemy import case, delete, func, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.v2.server.database.upsert import upsert
from .orm import dropped, events, logs, models, timings
from sagents.v2.runtime.observability.evidence.capture import DiagnosticCapture
from sagents.v2.runtime.observability.evidence.tools import tool_evidence
from sagents.v2.runtime.observability.performance.aggregation import build_run, timing_report
from sagents.v2.runtime.observability.performance.projection import log_timings, model_timing


def _scope(table, session_id, run_id):
    return table.c.session_id == session_id, table.c.run_id == run_id


class DatabaseDiagnostics(DiagnosticCapture):
    def __init__(self, database):
        self.database = database
        self.available = True
        self.closed = False
        self.capture_failures = 0
        self._loop = asyncio.get_running_loop()
        self._lock = Lock()
        self._pending = deque()
        self._last_write: Future | None = None
        self._writer: asyncio.Task | None = None
        self._writing = False
        self._scheduled = False

    def _enqueue(self, operation, *args):
        with self._lock:
            if (self.closed or not self.available
                    or len(self._pending) + self._writing >= self.max_pending_writes):
                self.capture_failures += 1
                return
            self._last_write = Future()
            self._pending.append((operation, args, self._last_write))
            if not self._scheduled:
                self._scheduled = True
                # Log producers can be worker threads. The writer has no Run context.
                self._loop.call_soon_threadsafe(self._start_writer, context=Context())

    def _start_writer(self):
        self._writer = self._loop.create_task(self._drain())

    async def _drain(self):
        while True:
            with self._lock:
                if not self._pending:
                    self._scheduled = False
                    return
                operation, args, finished = self._pending.popleft()
                self._writing = True
            try:
                await operation(*args)
            except asyncio.CancelledError:
                with self._lock:
                    self.capture_failures += 1 + len(self._pending)
                    while self._pending:
                        _, _, pending = self._pending.popleft()
                        pending.set_result(None)
                    self._scheduled = False
                raise
            except Exception:
                with self._lock:
                    self.capture_failures += 1
            finally:
                with self._lock:
                    self._writing = False
                    finished.set_result(None)

    async def _flush(self):
        with self._lock:
            pending = self._last_write
        if pending is not None:
            try:
                await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(pending)), timeout=3)
            except TimeoutError:
                with self._lock:
                    self.capture_failures += 1
                return False
        return True

    async def close(self):
        with self._lock:
            if self.closed:
                return
            self.closed = True
        if not await self._flush() and self._writer is not None:
            self._writer.cancel()
            await asyncio.gather(self._writer, return_exceptions=True)

    def _model_payload(self, previous, change, scope):
        record = {**json.loads(previous), **change, **scope}
        return self._encode(record), model_timing(record)

    async def _update(self, session_id, request, change):
        scope = dict(session_id=session_id, run_id=request.run_id, request_id=request.request_id)
        match = (*_scope(models, session_id, request.run_id), models.c.request_id == request.request_id)
        async with self.database.transaction() as db:
            await upsert(db, models, {**scope, "payload": "{}"}, key=tuple(scope))
            previous = await db.scalar(select(models.c.payload).where(*match).with_for_update())
            encoded, timing = await asyncio.to_thread(self._model_payload, previous, change, scope)
            await db.execute(update(models).where(*match).values(payload=encoded))

            await upsert(db, timings, timing, key=tuple(scope), replace=True)

    def _log_payload(self, record):
        data = record.model_dump(mode="json")
        return self._encode(data), tuple(log_timings(data))

    async def _write_log(self, record):
        session_id, run_id = record.session_id, record.run_id
        scope = dict(session_id=session_id, run_id=run_id)
        payload, projections = await asyncio.to_thread(self._log_payload, record)
        async with self.database.transaction() as db:
            for timing in projections:
                await upsert(db, events, timing, key="id")
            await db.execute(logs.insert().values(**scope, payload=payload))
            match = _scope(logs, session_id, run_id)
            cutoff = await db.scalar(select(logs.c.id).where(*match).order_by(
                logs.c.id.desc()
            ).offset(self.max_logs_per_run).limit(1))
            if cutoff is not None:
                removed = await db.execute(delete(logs).where(*match, logs.c.id <= cutoff))
                if removed.rowcount:
                    await upsert(db, dropped, {**scope, "count": 0}, key=tuple(scope))
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
        await self._flush()
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
        await self._flush()
        event = events.c
        accepted = event.event == "server.run.performance.accepted"
        cohort = case((accepted, event.started_at), else_=event.at)
        candidates = select(event.run_id).where(or_(
            (event.event == "agent.run.started") & (event.at >= start) & (event.at < end),
            accepted & (event.started_at >= start) & (event.started_at < end),
        ))
        if agent_id:
            candidates = candidates.where(event.agent_id == agent_id)
        candidates = candidates.group_by(event.run_id).order_by(func.min(cohort).desc()).limit(max_runs + 1)
        by_event, by_model = defaultdict(list), defaultdict(list)
        async with self.database.session() as db:
            ids = (await db.scalars(candidates)).all()
            truncated = len(ids) > max_runs
            remaining = max_timing_rows
            ids = ids[:max_runs]
            for offset in range(0, len(ids), 400):
                batch = ids[offset:offset + 400]
                event_rows = (await db.execute(select(events).where(events.c.run_id.in_(batch))
                                               .limit(remaining + 1))).mappings().all()
                if len(event_rows) > remaining:
                    truncated = True
                    break
                model_rows = (await db.execute(select(timings).where(timings.c.run_id.in_(batch))
                                               .limit(remaining - len(event_rows) + 1))).mappings().all()
                remaining -= len(event_rows) + len(model_rows)
                if remaining < 0:
                    truncated = True
                    break
                for row in event_rows:
                    by_event[row["run_id"]].append(row)
                for row in model_rows:
                    by_model[row["run_id"]].append(row)
        result = await asyncio.to_thread(
            timing_report, by_event, by_model, start=start, end=end, agent_id=agent_id,
            bucket=bucket, timezone_name=timezone_name, truncated=truncated,
        )
        return {**result, "source": "local", "capture_failures": self.capture_failures}
