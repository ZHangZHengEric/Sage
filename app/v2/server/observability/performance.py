"""SQL projection of the execution timing contract."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from hashlib import sha256

from sqlalchemy import case, func, or_, select, text, tuple_

from app.v2.server.database.upsert import upsert
from sagents.v2.runtime.observability.performance.aggregation import EVENTS, build_run, timing_report
from sagents.v2.runtime.observability.performance.recording import ModelTiming, RunTimingStage

from .orm import events, timings
from .writer import ObservationWriter

MODEL_KEY = ("session_id", "run_id", "request_id")


def _scope(table, session_id, run_id):
    return table.c.session_id == session_id, table.c.run_id == run_id


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


def _stage_row(stage: RunTimingStage):
    key = "\0".join((stage.session_id, stage.run_id, stage.event, stage.segment))
    return {
        "id": sha256(key.encode()).hexdigest(),
        "session_id": stage.session_id,
        "run_id": stage.run_id,
        "event": stage.event,
        "at": stage.at.timestamp(),
        "identity": stage.identity,
        "agent_id": stage.agent_id,
        "purpose": stage.purpose,
        "started_at": stage.started_at.timestamp() if stage.started_at is not None else None,
        "turn_id": stage.turn_id,
        "state": stage.state,
    }


class DatabasePerformance:
    max_pending_timings = 4096
    available = True

    def __init__(self, database):
        self.database = database
        self._timings = ObservationWriter(self._write_timings, batch_size=64)

    @property
    def capture_failures(self):
        return self._timings.failures

    async def close(self):
        await self._timings.close()

    def record_stage(self, stage: RunTimingStage) -> None:
        if stage.event not in EVENTS:
            self._timings.record_failure()
            return
        self._timings.enqueue(stage, limit=self.max_pending_timings)

    def record_model(self, timing: ModelTiming) -> None:
        self._timings.enqueue(timing, limit=self.max_pending_timings)

    async def _write_timings(self, batch):
        requests, stages = {}, {}
        for timing in batch:
            if isinstance(timing, RunTimingStage):
                row = _stage_row(timing)
                stages.setdefault(row["id"], row)
                continue
            key = timing.session_id, timing.run_id, timing.request_id
            row = requests.setdefault(key, dict(zip(MODEL_KEY, key)) | {
                "started_at": None, "ended_at": None, "first_token_at": None,
                "purpose": None, "turn_id": None,
            })
            started = timing.started_at.timestamp()
            if _earlier(started, row["started_at"]):
                row.update(started_at=started, purpose=timing.purpose, turn_id=timing.turn_id)
            if timing.first_token_at is not None:
                token = timing.first_token_at.timestamp()
                if _earlier(token, row["first_token_at"]):
                    row["first_token_at"] = token
            if timing.ended_at is not None and row["ended_at"] is None:
                row["ended_at"] = timing.ended_at.timestamp()
            stage = None
            if timing.ended_at is None:
                stage = RunTimingStage(*key[:2], "model.request.started", key[2], timing.started_at,
                                       identity=key[2], purpose=timing.purpose, turn_id=timing.turn_id)
            elif timing.first_text_at is not None:
                stage = RunTimingStage(*key[:2], "model.first_text", key[2], timing.first_text_at,
                                       identity=key[2], purpose=timing.purpose, turn_id=timing.turn_id)
            if stage is not None:
                stage_row = _stage_row(stage)
                stages.setdefault(stage_row["id"], stage_row)

        async def write(db):
            if requests:
                await upsert(db, timings, [requests[key] for key in sorted(requests)],
                             key=MODEL_KEY, merge=_timing_changes)
            if stages:
                await upsert(db, events, [stages[key] for key in sorted(stages)], key="id")

        await self.database.run_transaction(write)

    @asynccontextmanager
    async def _read_snapshot(self):
        async with self.database.session() as db:
            if db.get_bind().dialect.name == "sqlite":
                await db.execute(text("BEGIN"))
            else:
                await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            yield db

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

    supports_business_report = True

    async def report(self, *, start, end, agent_id="", bucket="hour", timezone_name="Asia/Shanghai",
                     max_runs=10000, max_timing_rows=100000, business=None):
        flushed = True if business is not None else await self._timings.flush()
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
        async with self._read_snapshot() as db:
            ids = list(business.runs) if business is not None else (await db.execute(candidates)).all()
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
            bucket=bucket, timezone_name=timezone_name, truncated=truncated, business=business,
        )
        return {**result, "source": "local", "capture_failures": self._timings.failures + int(not flushed)}
