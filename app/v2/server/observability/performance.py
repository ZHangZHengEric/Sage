"""Content-free timing projection, independent of diagnostic payload size.

A row represents one user request (Run), combining its internal model steps.
Residual wall time is never reported as framework time for incomplete captures.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import math
import sqlite3
from zoneinfo import ZoneInfo

EVENTS = frozenset(
    {
        "server.run.performance.accepted",
        "server.run.performance.resuming",
        "server.run.performance.finished",
        "agent.run.started",
        "agent.run.completed",
        "agent.run.failed",
        "agent.run.cancelled",
        "agent.run.suspended",
        "agent.run.deferred",
        "agent.run.stopped",
        "tool.call.started",
        "tool.call.completed",
        "tool.call.failed",
        "tool.call.interrupted",
        "model.first_text",
        "model.request.started",
        "model.request.completed",
        "model.request.failed",
    }
)
SCHEMA = """
CREATE TABLE IF NOT EXISTS performance_events (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
 event TEXT NOT NULL, at REAL NOT NULL, agent_id TEXT, identity TEXT, purpose TEXT,
 started_at REAL, turn_id TEXT, state TEXT);
CREATE INDEX IF NOT EXISTS performance_events_time ON performance_events(event,at);
CREATE INDEX IF NOT EXISTS performance_events_entry ON performance_events(event,started_at);
CREATE INDEX IF NOT EXISTS performance_events_run ON performance_events(run_id,at);
CREATE TABLE IF NOT EXISTS performance_models (
 run_id TEXT NOT NULL, request_id TEXT NOT NULL, session_id TEXT NOT NULL,
 started_at REAL, ended_at REAL, first_token_at REAL, purpose TEXT, turn_id TEXT,
 PRIMARY KEY(run_id,request_id));
CREATE INDEX IF NOT EXISTS performance_models_run ON performance_models(run_id,started_at);
"""


def timestamp(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return value.timestamp()


def project_log(db, row):
    event = row.get("event")
    if event not in EVENTS or not row.get("run_id") or not row.get("session_id"):
        return
    attrs = row.get("attributes") or {}
    # Deliberate allowlist: no messages, arguments, errors or model content.
    at = timestamp(row["timestamp"])
    identity = (
        row.get("tool_call_id") if event.startswith("tool.") else row.get("request_id")
    )
    key = hashlib.sha256(
        f"{row['run_id']}\0{event}\0{at}\0{identity}".encode()
    ).hexdigest()
    db.execute(
        "INSERT OR IGNORE INTO performance_events VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            key,
            row["session_id"],
            row["run_id"],
            event,
            at,
            attrs.get("agent_id"),
            identity,
            attrs.get("purpose"),
            timestamp(attrs.get("started_at")),
            row.get("turn_id"),
            attrs.get("run_state"),
        ),
    )
    # First text is also available from completion telemetry at info log level.
    if (
        event == "model.request.completed"
        and attrs.get("first_text_ms") is not None
        and attrs.get("duration_ms") is not None
    ):
        first = at - (attrs["duration_ms"] - attrs["first_text_ms"]) / 1000
        projected = {**row, "event": "model.first_text", "timestamp": first}
        project_log(db, projected)


def project_model(db, row):
    db.execute(
        "INSERT OR REPLACE INTO performance_models VALUES(?,?,?,?,?,?,?,?)",
        (
            row["run_id"],
            row["request_id"],
            row["session_id"],
            timestamp(row.get("started_at")),
            timestamp(row.get("completed_at")),
            timestamp(row.get("first_token_at")),
            row.get("purpose") or "agent",
            row.get("turn_id"),
        ),
    )


def backfill(path):
    """Explicit maintenance operation; reads only allowlisted timing fields."""
    with closing(sqlite3.connect(path, timeout=15)) as db, db:
        db.executescript(SCHEMA)
        names = ",".join("?" for _ in EVENTS)
        rows = db.execute(
            f"""SELECT session_id,run_id,json_extract(payload,'$.timestamp'),
          json_extract(payload,'$.event'),json_extract(payload,'$.tool_call_id'),json_extract(payload,'$.request_id'),
          json_extract(payload,'$.turn_id'),json_extract(payload,'$.attributes.agent_id'),
          json_extract(payload,'$.attributes.purpose'),json_extract(payload,'$.attributes.started_at'),
          json_extract(payload,'$.attributes.first_text_ms'),json_extract(payload,'$.attributes.duration_ms'),
          json_extract(payload,'$.attributes.run_state')
          FROM logs WHERE json_extract(payload,'$.event') IN ({names})""",
            tuple(EVENTS),
        )
        count = 0
        for (
            sid,
            rid,
            at,
            event,
            call,
            request,
            turn,
            agent,
            purpose,
            start,
            first,
            duration,
            state,
        ) in rows:
            project_log(
                db,
                dict(
                    session_id=sid,
                    run_id=rid,
                    timestamp=at,
                    event=event,
                    tool_call_id=call,
                    request_id=request,
                    turn_id=turn,
                    attributes=dict(
                        agent_id=agent,
                        purpose=purpose,
                        started_at=start,
                        first_text_ms=first,
                        duration_ms=duration,
                        run_state=state,
                    ),
                ),
            )
            count += 1
        rows = db.execute("""SELECT session_id,run_id,request_id,json_extract(payload,'$.started_at'),
          json_extract(payload,'$.completed_at'),json_extract(payload,'$.first_token_at'),
          json_extract(payload,'$.purpose'),json_extract(payload,'$.turn_id') FROM models""")
        models = 0
        for row in rows:
            project_model(
                db,
                dict(
                    zip(
                        (
                            "session_id",
                            "run_id",
                            "request_id",
                            "started_at",
                            "completed_at",
                            "first_token_at",
                            "purpose",
                            "turn_id",
                        ),
                        row,
                    )
                ),
            )
            models += 1
        return {"events": count, "models": models}


def intervals(values):
    result = []
    for start, end in sorted(
        (a, b) for a, b in values if a is not None and b is not None and b >= a
    ):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def seconds(values):
    return sum(b - a for a, b in intervals(values))


def percentile(values, quantile):
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return None
    index = (len(ordered) - 1) * quantile
    low = math.floor(index)
    return ordered[low] + (ordered[math.ceil(index)] - ordered[low]) * (index - low)


def summarize(rows):
    finished = [r for r in rows if r["state"] == "completed"]
    complete = [r for r in finished if r["scope"] == "sdk_entry"]
    measured = [r for r in complete if r["coverage"] == "complete"]
    result = {
        "requests": len(rows),
        "completed": len(finished),
        "measured": len(measured),
        "incomplete": len(finished) - len(measured),
    }
    for field in (
        "total_ms",
        "first_token_ms",
        "first_text_ms",
        "model_ttft_ms",
        "framework_ms",
    ):
        result[field] = {
            q: percentile(
                [r[field] for r in measured],
                p,
            )
            for q, p in (("p50", 0.5), ("p95", 0.95))
        }
    elapsed = sum(r["total_ms"] for r in measured)
    result["framework_ratio"] = (
        sum(r["framework_ms"] for r in measured) / elapsed if elapsed else None
    )
    return result


def build_run(events, models):
    events.sort(key=lambda r: r["at"])
    starts = [r for r in events if r["event"] == "agent.run.started"]
    if not starts:
        return None
    accepted = [
        r["started_at"]
        for r in events
        if r["event"] == "server.run.performance.accepted" and r["started_at"]
    ]
    start = min(accepted) if accepted else starts[0]["at"]
    finish_events = [
        r
        for r in events
        if r["event"].startswith("agent.run.") and r["event"] != "agent.run.started"
    ]
    end = finish_events[-1]["at"] if finish_events else None
    state = finish_events[-1]["event"].rsplit(".", 1)[-1] if end else "running"
    outer = [e for e in events if e["event"] == "server.run.performance.finished"]
    if outer:
        end, state = outer[-1]["at"], outer[-1]["state"]
    scope = "sdk_entry" if accepted else "execution_only"
    # Resumption is a separate execution segment; exclude user waiting between segments.
    spans = []
    pending = None
    unclosed_execution = False
    for e in events:
        if e["event"] == "agent.run.started":
            if pending is not None:
                unclosed_execution = True
            pending = e["at"]
        elif e["event"].startswith("agent.run.") and pending is not None:
            spans.append((pending, e["at"]))
            pending = None
    if end is None or pending is not None:
        return dict(
            run_id=starts[0]["run_id"],
            session_id=starts[0]["session_id"],
            agent_id=next((e["agent_id"] for e in starts if e["agent_id"]), ""),
            started_at=datetime.fromtimestamp(start, timezone.utc).isoformat(),
            state=state,
            scope=scope,
            total_ms=None,
            first_token_ms=None,
            first_text_ms=None,
            model_ttft_ms=None,
            framework_ms=None,
            model_ms=None,
            tool_ms=None,
            overlap_ms=None,
            waiting_ms=None,
            coverage="incomplete",
            model_calls=len(models),
            tool_calls=0,
            purposes={},
        )
    resumed = [
        e["started_at"]
        for e in events
        if e["event"] == "server.run.performance.resuming"
        and e["started_at"] is not None
    ]
    active_segments = list(spans)
    missing_resume = False
    for i in range(1, len(spans)):
        candidates = [t for t in resumed if spans[i - 1][1] <= t <= spans[i][0]]
        if candidates:
            active_segments[i] = (max(candidates), spans[i][1])
        else:
            missing_resume = True
    active = intervals(
        [(start, starts[0]["at"]), *active_segments, (spans[-1][1], end)]
        if spans
        else []
    )
    total = seconds(active)

    def clipped(values):
        return [
            (max(a, s), min(b, e))
            for a, b in values
            for s, e in active
            if a < e and b > s
        ]

    model_spans = clipped(
        [
            (m["started_at"], m["ended_at"])
            for m in models
            if m["started_at"] and m["ended_at"]
        ]
    )
    open_models = any(
        not m["started_at"] or not m["ended_at"] or m["ended_at"] < m["started_at"]
        for m in models
    )
    tools = []
    pending_tools = {}
    tool_count = 0
    incomplete_tools = False
    for e in events:
        if e["event"] == "tool.call.started":
            if e["identity"] in pending_tools:
                incomplete_tools = True
            pending_tools[e["identity"]] = e["at"]
            tool_count += 1
        elif e["event"].startswith("tool.call."):
            t = pending_tools.pop(e["identity"], None)
            if t is None:
                incomplete_tools = True
            else:
                if e["at"] < t:
                    incomplete_tools = True
                tools.append((t, e["at"]))
    tools = clipped(tools)
    recorded_ids = {
        e["identity"] for e in events if e["event"] == "model.request.started"
    }
    known_ids = {m["request_id"] for m in models}
    complete = (
        scope == "sdk_entry"
        and bool(outer)
        and bool(models)
        and not (
            open_models
            or pending_tools
            or incomplete_tools
            or unclosed_execution
            or missing_resume
            or recorded_ids - known_ids
        )
    )
    model_time, tool_time = seconds(model_spans), seconds(tools)
    busy = seconds(model_spans + tools)
    main = sorted(
        (m for m in models if m["purpose"] == "agent" and m["started_at"]),
        key=lambda r: r["started_at"],
    )
    # TTFT is the first primary model request's provider latency, including reasoning.
    ttft = (
        main[0]["first_token_at"] - main[0]["started_at"]
        if main and main[0]["first_token_at"]
        else None
    )
    tokens = [m["first_token_at"] for m in main if m["first_token_at"]]
    purposes_by_id = {m["request_id"]: m["purpose"] for m in models}
    texts = [
        e["at"]
        for e in events
        if e["event"] == "model.first_text"
        and (e["purpose"] or purposes_by_id.get(e["identity"])) == "agent"
    ]
    purposes = defaultdict(lambda: {"calls": 0, "ms": 0.0})
    for m in models:
        purposes[m["purpose"]]["calls"] += 1
        if m["ended_at"] and m["started_at"]:
            purposes[m["purpose"]]["ms"] += (
                max(0, m["ended_at"] - m["started_at"]) * 1000
            )
    return dict(
        run_id=starts[0]["run_id"],
        session_id=starts[0]["session_id"],
        agent_id=next((e["agent_id"] for e in starts if e["agent_id"]), ""),
        started_at=datetime.fromtimestamp(start, timezone.utc).isoformat(),
        state=state,
        scope=scope,
        total_ms=total * 1000,
        model_ms=model_time * 1000,
        tool_ms=tool_time * 1000,
        overlap_ms=max(0, model_time + tool_time - busy) * 1000,
        framework_ms=max(0, total - busy) * 1000 if complete else None,
        first_token_ms=seconds(clipped([(start, min(tokens))])) * 1000
        if tokens
        else None,
        first_text_ms=seconds(clipped([(start, min(texts))])) * 1000 if texts else None,
        model_ttft_ms=ttft * 1000 if ttft is not None else None,
        waiting_ms=max(0, end - start - total) * 1000,
        coverage="complete" if complete else "incomplete",
        model_calls=len(models),
        tool_calls=tool_count,
        purposes=dict(purposes),
    )


def report(
    path,
    *,
    start,
    end,
    agent_id="",
    bucket="hour",
    timezone_name="Asia/Shanghai",
    max_runs=10000,
    max_timing_rows=100000,
):
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        candidates = list(
            db.execute(
                """SELECT run_id, MIN(CASE WHEN event='server.run.performance.accepted' THEN started_at ELSE at END) AS cohort FROM performance_events
            WHERE ((event='agent.run.started' AND at>=? AND at<?)
            OR (event='server.run.performance.accepted' AND started_at>=? AND started_at<?))
            AND (?='' OR agent_id=?)
            GROUP BY run_id ORDER BY cohort DESC LIMIT ?""",
                (start, end, start, end, agent_id, agent_id, max_runs + 1),
            )
        )
        truncated = len(candidates) > max_runs
        ids = [r["run_id"] for r in candidates[:max_runs]]
        events = defaultdict(list)
        models = defaultdict(list)
        timing_rows = 0
        for offset in range(0, len(ids), 400):
            batch = ids[offset : offset + 400]
            placeholders = ",".join("?" for _ in batch)
            batch_size = sum(
                db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE run_id IN ({placeholders})",
                    batch,
                ).fetchone()[0]
                for table in ("performance_events", "performance_models")
            )
            if timing_rows + batch_size > max_timing_rows:
                truncated = True
                break
            timing_rows += batch_size
            for r in db.execute(
                f"SELECT * FROM performance_events WHERE run_id IN ({placeholders})",
                batch,
            ):
                events[r["run_id"]].append(dict(r))
            for r in db.execute(
                f"SELECT * FROM performance_models WHERE run_id IN ({placeholders})",
                batch,
            ):
                models[r["run_id"]].append(dict(r))
    return timing_report(
        events, models, start=start, end=end, agent_id=agent_id,
        bucket=bucket, timezone_name=timezone_name, truncated=truncated,
    )


def timing_report(events, models, *, start, end, agent_id="", bucket="hour",
                  timezone_name="Asia/Shanghai", truncated=False):
    """Use the same timing and coverage rules for local and external records."""
    zone = ZoneInfo(timezone_name)
    rows = []
    for rid, values in events.items():
        row = build_run(values, models[rid])
        if (
            row
            and start <= timestamp(row["started_at"]) < end
            and (not agent_id or row["agent_id"] == agent_id)
        ):
            rows.append(row)
    rows.sort(key=lambda r: r["started_at"], reverse=True)
    buckets = defaultdict(list)
    cursor = datetime.fromtimestamp(start, zone).replace(
        minute=0, second=0, microsecond=0
    )
    if bucket == "day":
        cursor = cursor.replace(hour=0)
    while cursor.timestamp() < end:
        buckets[cursor.isoformat()]
        cursor += timedelta(days=1) if bucket == "day" else timedelta(hours=1)
    for row in rows:
        time = (
            datetime.fromisoformat(row["started_at"])
            .astimezone(zone)
            .replace(minute=0, second=0, microsecond=0)
        )
        if bucket == "day":
            time = time.replace(hour=0)
        buckets[time.isoformat()].append(row)
    return {
        "summary": summarize(rows),
        "buckets": [{"time": k, **summarize(v)} for k, v in sorted(buckets.items())],
        "runs": rows[:200],
        "total_runs": len(rows),
        "truncated": truncated,
        "run_list_truncated": len(rows) > 200,
        "timezone": timezone_name,
        "start": start,
        "end": end,
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Backfill content-free timing metadata from existing diagnostic records"
    )
    parser.add_argument(
        "--backfill", required=True, help="Existing evidence.sqlite3 path"
    )
    options = parser.parse_args()
    print(json.dumps(backfill(options.backfill)))
