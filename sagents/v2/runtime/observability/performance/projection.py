"""Project only the fields used by performance queries."""

import hashlib

from .aggregation import EVENTS, model_first_text_at, timestamp


def log_timings(row):
    event = row.get("event")
    if event not in EVENTS or not row.get("run_id") or not row.get("session_id"):
        return
    attrs = row.get("attributes") or {}
    at = timestamp(attrs.get("first_text_at") if event == "model.first_text"
                   and attrs.get("first_text_at") else row["timestamp"])
    identity = row.get("tool_call_id") if event.startswith("tool.") else row.get("request_id")
    yield {
        "id": hashlib.sha256(f"{row['run_id']}\0{event}\0{at}\0{identity}".encode()).hexdigest(),
        "session_id": row["session_id"],
        "run_id": row["run_id"],
        "event": event,
        "at": at,
        "agent_id": attrs.get("agent_id"),
        "identity": identity,
        "purpose": attrs.get("purpose"),
        "started_at": timestamp(attrs.get("started_at")),
        "turn_id": row.get("turn_id"),
        "state": attrs.get("run_state"),
    }
    if event == "model.request.completed" and (first := model_first_text_at(attrs, at)) is not None:
        yield from log_timings({**row, "event": "model.first_text", "timestamp": first})


def model_timing(row):
    return {
        "run_id": row["run_id"],
        "request_id": row["request_id"],
        "session_id": row["session_id"],
        "started_at": timestamp(row.get("started_at")),
        "ended_at": timestamp(row.get("completed_at")),
        "first_token_at": timestamp(row.get("first_token_at")),
        "purpose": row.get("purpose") or "agent",
        "turn_id": row.get("turn_id"),
    }
