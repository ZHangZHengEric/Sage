"""Pure timing aggregation shared by all observation adapters."""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo

from sagents.v2.runtime.session.reporting import BusinessReplay, TOKEN_FIELDS

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


def model_first_text_at(attributes, completed_at):
    observed = timestamp(attributes.get("first_text_at"))
    if observed is not None:
        return observed
    elapsed, first = attributes.get("duration_ms"), attributes.get("first_text_ms")
    if elapsed is not None and first is not None:
        return completed_at - (elapsed - first) / 1000
    return None


def normalize_timing_rows(rows, *, incomplete=False):
    """Normalize captured timing rows without encoding them as Trace payloads."""
    events, models = defaultdict(list), defaultdict(dict)
    for observation in sorted(rows, key=lambda r: r["at"]):
        row = observation["data"]
        rid = row["run_id"]
        if observation["kind"] == "model":
            models[rid].setdefault(row["request_id"], {}).update(row)
            continue
        values = row.get("attributes", {})
        event = dict(
            session_id=row["session_id"],
            run_id=rid,
            event=row["event"],
            at=timestamp(values.get("first_text_at") if row["event"] == "model.first_text"
                         and values.get("first_text_at") else row["timestamp"]),
            agent_id=values.get("agent_id"),
            identity=row.get("tool_call_id")
            if row["event"].startswith("tool.")
            else row.get("request_id"),
            purpose=values.get("purpose"),
            turn_id=row.get("turn_id"),
            started_at=timestamp(values.get("started_at")),
            state=values.get("run_state"),
            _observation_incomplete=incomplete
            or observation.get("_observation_incomplete", False),
        )
        events[rid].append(event)
        if row["event"] == "model.request.completed" and (
            first := model_first_text_at(values, event["at"])
        ) is not None:
            events[rid].append(
                {
                    **event,
                    "event": "model.first_text",
                    "at": first,
                }
            )
    normalized = defaultdict(list)
    for rid, requests in models.items():
        for row in requests.values():
            normalized[rid].append(
                {
                    **row,
                    "started_at": timestamp(row.get("started_at")),
                    "ended_at": timestamp(row.get("completed_at")),
                    "first_token_at": timestamp(row.get("first_token_at")),
                    "purpose": row.get("purpose", "agent"),
                }
            )
    return events, normalized


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


def summarize(rows, *, business=None, coverage_exact=True):
    finished = [r for r in rows if r["state"] == "completed"]
    complete = [r for r in finished if r["scope"] == "sdk_entry"]
    measured = [r for r in complete if r["coverage"] == "complete"]
    result = {
        "requests": len(rows),
        "completed": len(finished),
        "measured": len(measured),
        "incomplete": len(finished) - len(measured),
    }
    samples = {}
    for field in (
        "total_ms", "first_token_ms", "first_text_ms", "model_ttft_ms", "framework_ms",
    ):
        values = [r[field] for r in measured if r[field] is not None]
        samples[field] = len(values)
        result[field] = {q: percentile(values, p) for q, p in (("p50", 0.5), ("p95", 0.95))}
    result["timing_samples"] = samples
    result["coverage_rate"] = len(measured) / len(finished) if finished and coverage_exact else None
    if business is not None:
        states = Counter(facts.metadata.state.value for facts in business)
        tools = Counter(state for facts in business if facts.events_complete for state in facts.tools.values())
        available = [facts for facts in business if facts.events_complete]
        result["run_states"] = dict(states)
        result["tool_outcomes"] = dict(tools)
        result["usage"] = {
            "records": sum(facts.usage_records for facts in available),
            "reported_records": sum(facts.reported_usage_records for facts in available),
            "runs_with_event_data": len(available),
            **{field: sum(facts.tokens[field] for facts in available) for field in TOKEN_FIELDS},
        }
    elapsed = sum(r["total_ms"] for r in measured)
    result["framework_ratio"] = (
        sum(r["framework_ms"] for r in measured) / elapsed if elapsed else None
    )
    return result


def interval_difference(windows, occupied):
    """Subtract sorted, disjoint occupied ranges from sorted, disjoint windows."""
    index = 0
    for start, end in windows:
        while index < len(occupied) and occupied[index][1] <= start:
            index += 1
        cursor = start
        while index < len(occupied) and occupied[index][0] < end:
            left, right = occupied[index]
            if left > cursor:
                yield cursor, left
            cursor = max(cursor, right)
            if right >= end:
                break
            index += 1
        if cursor < end:
            yield cursor, end


def run_timeline(start, end, active, model_ranges, tools, framework, waiting, first_token):
    entries = []

    def add(kind, left, right, **details):
        entries.append({
            "kind": kind,
            "start_ms": round((left - start) * 1000, 3),
            "end_ms": round((right - start) * 1000, 3),
            **details,
        })

    for left, right, purpose in model_ranges:
        add("model", left, right, purpose=purpose)
    for left, right, call_id in tools:
        add("tool", left, right, tool_call_id=call_id)
    if framework is not None:
        preparation, cleanup, busy = framework
        prepare_gaps = list(interval_difference(preparation, busy))
        cleanup_gaps = list(interval_difference(cleanup, busy))
        other = interval_difference(active, intervals([*busy, *prepare_gaps, *cleanup_gaps]))
        for kind, ranges in (("preparation", prepare_gaps), ("framework", other), ("cleanup", cleanup_gaps)):
            for left, right in ranges:
                add(kind, left, right)
    if waiting:
        for left, right in interval_difference([(start, end)], active):
            add("waiting", left, right)
    if first_token is not None and start <= first_token <= end:
        add("first_token", first_token, first_token)
    entries.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
    return {
        "wall_ms": round((end - start) * 1000, 3),
        "entries": entries[:300],
        "truncated": len(entries) > 300,
    }


def build_run(events, models, *, include_timeline=False):
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

    def clipped(left, right):
        if right <= left:
            return
        index = bisect_right(active, left, key=lambda window: window[1])
        while index < len(active) and active[index][0] < right:
            start, end = active[index]
            yield max(left, start), min(right, end)
            index += 1

    model_ranges = [
        (left, right, m["purpose"])
        for m in models
        if m["started_at"] and m["ended_at"]
        for left, right in clipped(m["started_at"], m["ended_at"])
    ]
    model_spans = [(left, right) for left, right, _ in model_ranges]
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
                tools.append((t, e["at"], e["identity"]))
    tool_ranges = [
        (left, right, call_id)
        for start_at, end_at, call_id in tools
        for left, right in clipped(start_at, end_at)
    ]
    tool_spans = [(left, right) for left, right, _ in tool_ranges]
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
    model_time, tool_time = seconds(model_spans), seconds(tool_spans)
    busy_ranges = intervals(model_spans + tool_spans)
    busy = sum(right - left for left, right in busy_ranges)
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
        e
        for e in events
        if e["event"] == "model.first_text"
        and (e["purpose"] or purposes_by_id.get(e["identity"])) == "agent"
    ]
    first_token = min(tokens, default=None)
    first_text_event = min(texts, key=lambda e: e["at"], default=None)
    first_text = first_text_event["at"] if first_text_event else None
    purposes = defaultdict(lambda: {"calls": 0, "ms": 0.0})
    for m in models:
        purposes[m["purpose"]]["calls"] += 1
        if m["ended_at"] and m["started_at"]:
            purposes[m["purpose"]]["ms"] += (
                max(0, m["ended_at"] - m["started_at"]) * 1000
            )
    result = dict(
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
        first_token_ms=sum(right - left for left, right in clipped(start, first_token)) * 1000
        if first_token is not None
        else None,
        first_text_ms=sum(right - left for left, right in clipped(start, first_text)) * 1000
        if first_text is not None
        else None,
        model_ttft_ms=ttft * 1000 if ttft is not None else None,
        waiting_ms=max(0, end - start - total) * 1000,
        coverage="complete" if complete else "incomplete",
        model_calls=len(models),
        tool_calls=tool_count,
        purposes=dict(purposes),
    )
    if include_timeline and end >= start:
        if first_text_event is not None:
            request = next((m for m in main if m["request_id"] == first_text_event["identity"]), None)
            if request is not None and first_text >= request["started_at"]:
                result["first_text_request_ms"] = round((first_text - request["started_at"]) * 1000, 3)
        framework = None
        if complete:
            preparation = intervals([
                (start, starts[0]["at"]),
                *((entry, body) for (entry, _), (body, _) in zip(active_segments, spans) if entry < body),
            ])
            cleanup = [(spans[-1][1], end)]
            framework = preparation, cleanup, busy_ranges
        result["timeline"] = run_timeline(
            start, end, active, model_ranges, tool_ranges, framework,
            not (missing_resume or unclosed_execution),
            first_token,
        )
    return result


def _business_timing_rows(events, models, business):
    for key, facts in business.runs.items():
        metadata = facts.metadata
        scoped_events = events.get(key)
        if scoped_events is None:
            scoped_events = [row for row in events.get(metadata.run_id, ()) if row["session_id"] == metadata.session_id]
        scoped_models = models.get(key)
        if scoped_models is None:
            scoped_models = [row for row in models.get(metadata.run_id, ()) if row["session_id"] == metadata.session_id]
        row = build_run(scoped_events, scoped_models) if scoped_events else None
        state = metadata.state.value
        cohort_at = metadata.created_at.timestamp()
        if row is None or row["state"] != state:
            row = {
                "run_id": metadata.run_id, "session_id": metadata.session_id,
                "started_at": metadata.created_at.isoformat(), "state": state,
                "scope": "unavailable", "coverage": "incomplete",
                "model_calls": len(scoped_models), "tool_calls": len(facts.tools), "purposes": {},
                **dict.fromkeys(("total_ms", "first_token_ms", "first_text_ms", "model_ttft_ms",
                                 "framework_ms", "model_ms", "tool_ms", "overlap_ms", "waiting_ms")),
            }
        if row["coverage"] == "complete":
            observed_tools = Counter(event["identity"] for event in scoped_events if event["event"] == "tool.call.started")
            if not facts.events_complete or not Counter(facts.started_tools.values()) <= observed_tools:
                row["coverage"] = "incomplete"
                row["framework_ms"] = None
        row["agent_id"] = metadata.agent_id
        yield row, cohort_at, facts


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
    business: BusinessReplay | None = None,
):
    """Use the same timing and coverage rules for local and external records."""
    zone = ZoneInfo(timezone_name)
    if business is None:
        entries = []
        for rid, values in events.items():
            row = build_run(values, models[rid])
            if row and start <= (at := timestamp(row["started_at"])) < end and (
                not agent_id or row["agent_id"] == agent_id
            ):
                entries.append((row, at, None))
    else:
        entries = list(_business_timing_rows(events, models, business))
    entries.sort(key=lambda entry: (entry[1], entry[0]["run_id"]), reverse=True)
    coverage_exact = not truncated and not (
        business and (business.cohort_truncated or business.events_truncated or business.archive_pending)
    )
    buckets = defaultdict(list)
    cursor = datetime.fromtimestamp(start, zone).replace(
        minute=0, second=0, microsecond=0
    )
    if bucket == "day":
        cursor = cursor.replace(hour=0)
    while cursor.timestamp() < end:
        buckets[cursor.isoformat()]
        cursor += timedelta(days=1) if bucket == "day" else timedelta(hours=1)
    for entry in entries:
        time = datetime.fromtimestamp(entry[1], zone).replace(minute=0, second=0, microsecond=0)
        if bucket == "day":
            time = time.replace(hour=0)
        buckets[time.isoformat()].append(entry)

    def summarize_entries(group):
        return summarize(
            [row for row, _, _ in group],
            business=[facts for _, _, facts in group] if business is not None else None,
            coverage_exact=coverage_exact,
        )

    return {
        "summary": summarize_entries(entries),
        "buckets": [{"time": k, **summarize_entries(v)} for k, v in sorted(buckets.items())],
        "runs": [row for row, _, _ in entries[:200]],
        "total_runs": len(entries),
        "truncated": truncated or bool(business and (business.cohort_truncated or business.events_truncated)),
        "run_list_truncated": len(entries) > 200,
        **({"business": {
            "cohort_truncated": business.cohort_truncated,
            "events_truncated": business.events_truncated,
            "archive_pending": business.archive_pending,
        }} if business is not None else {}),
        "timezone": timezone_name,
        "start": start,
        "end": end,
    }
