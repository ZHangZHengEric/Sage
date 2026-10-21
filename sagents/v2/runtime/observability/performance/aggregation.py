"""Pure timing aggregation shared by all observation adapters."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
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
    result: dict[str, int | float | dict[str, float | None] | None] = {
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
    if (
        end is None
        or pending is not None
        or any(e.get("_observation_incomplete") for e in events)
    ):
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


def timing_report(
    events,
    models,
    *,
    start,
    end,
    agent_id="",
    bucket="hour",
    timezone_name="Asia/Shanghai",
    truncated=False,
):
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
