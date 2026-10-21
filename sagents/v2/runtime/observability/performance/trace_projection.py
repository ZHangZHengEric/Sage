"""Decode normalized performance observations from vendor-neutral spans."""

from collections import defaultdict
import json
from .aggregation import timestamp

SPAN_NAME = "agent.run"
PAYLOAD = "sage.performance.data"


def _span_start(span) -> float:
    value = timestamp(span["start_time"])
    if value is None:
        raise ValueError("performance span is missing its start time")
    return value


def timing_rows(spans):
    events, models = defaultdict(list), defaultdict(dict)
    seen = set()
    rows = []
    for span in sorted(spans, key=_span_start):
        attrs = span["attributes"]
        if (
            span["name"] != SPAN_NAME
            or attrs.get("sage.performance.format") != "events/v3"
        ):
            continue
        identity = (span["context"]["trace_id"], span["context"]["span_id"])
        if identity in seen:
            continue
        seen.add(identity)
        payload = attrs[PAYLOAD]
        rows.extend(
            {
                **row,
                "_observation_incomplete": bool(
                    attrs.get("sage.performance.incomplete")
                ),
            }
            for row in json.loads(
                "".join(payload) if isinstance(payload, (list, tuple)) else payload
            )
        )
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
            at=timestamp(row["timestamp"]),
            agent_id=values.get("agent_id"),
            identity=row.get("tool_call_id")
            if row["event"].startswith("tool.")
            else row.get("request_id"),
            purpose=values.get("purpose"),
            turn_id=row.get("turn_id"),
            started_at=timestamp(values.get("started_at")),
            state=values.get("run_state"),
            _observation_incomplete=observation.get("_observation_incomplete", False),
        )
        events[rid].append(event)
        if (
            row["event"] == "model.request.completed"
            and values.get("first_text_ms") is not None
            and values.get("duration_ms") is not None
        ):
            events[rid].append(
                {
                    **event,
                    "event": "model.first_text",
                    "at": event["at"]
                    - (values["duration_ms"] - values["first_text_ms"]) / 1000,
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
