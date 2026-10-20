"""Project model evidence already present in spans; never synthesize raw capture."""
from __future__ import annotations

from datetime import datetime, timezone
import json


def _attribute(attrs, key):
    if key in attrs:
        return attrs[key]
    value = attrs
    for part in key.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _decode(value):
    if not isinstance(value, str):
        return value, False
    try:
        return json.loads(value), False
    except ValueError:
        # JSON attributes can be cut mid-string by a previous exporter limit.
        # Preserve exactly what the backend returned, and mark the gap.
        return value, True


def _truncated(value):
    if isinstance(value, dict):
        return value.get("truncated") is True or any(_truncated(v) for v in value.values())
    if isinstance(value, list):
        return any(_truncated(v) for v in value)
    return isinstance(value, str) and value.endswith("…")


def _date(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if isinstance(value, (int, float)) else value


def model_evidence(spans, captured=()):
    """Prefer dedicated diagnostics, fill missing fields from normalized spans."""
    rows = {(r["run_id"], r["request_id"]): dict(r) for r in captured}
    for row in rows.values():
        row["evidence_source"] = "diagnostic_events"
        row["field_sources"] = {field: "diagnostic_events" for field in ("request", "response", "stream", "error")
                                if row.get(field) is not None}
    for span in spans:
        if span.get("name") != "model.request":
            continue
        attrs = span.get("attributes", {})
        request_id = attrs.get("request_id") or "span:" + span.get("context", {}).get("span_id", "unknown")
        key = attrs["run_id"], request_id
        row = rows.setdefault(key, {"session_id":attrs["session_id"], "run_id":key[0],
                                   "request_id":request_id, "evidence_source":"trace_projection", "field_sources":{}})
        row.setdefault("started_at", _date(span.get("start_time")))
        if span.get("end_time"):
            row.setdefault("completed_at", _date(span["end_time"]))
        row.setdefault("status", "failed" if span.get("status_code") == "ERROR"
                       else "completed" if span.get("end_time") else "started")
        for field in ("purpose", "turn_id", "step_id", "model", "provider", "model_binding"):
            if attrs.get(field) is not None:
                row.setdefault(field, attrs[field])
        if row.get("request") is None:
            value, invalid = _decode(_attribute(attrs, "input.value"))
            row["request"] = {"model":attrs.get("model"), "model_parameters":_decode(attrs.get("model_parameters"))[0],
                              **(value if isinstance(value, dict) else {"input":value})}
            row["request_format"] = "normalized_trace"
            row["request_content_available"] = value is not None and not (isinstance(value, dict) and "diagnostic_request_id" in value)
            row["request_truncated"] = invalid or _truncated(value)
            row["field_sources"]["request"] = "trace_projection"
        if row.get("response") is None:
            value, invalid = _decode(_attribute(attrs, "output.value"))
            if value is not None:
                row["response"] = value if isinstance(value, dict) else {"output":value}
                row["field_sources"]["response"] = "trace_projection"
            row["response_content_available"] = value is not None and not (isinstance(value, dict) and "diagnostic_request_id" in value)
            row["response_truncated"] = invalid or _truncated(value)
        row.setdefault("usage", _decode(attrs.get("usage"))[0])
        row.setdefault("content_mode", attrs.get("sage.content.mode", "unknown"))
        row["truncated"] = bool(row.get("truncated") or row.get("request_truncated") or row.get("response_truncated")
                                or attrs.get("sage.content.incomplete"))
        if row.get("error") is None and span.get("status_code") == "ERROR":
            row["error"] = {"message":span.get("status_message")}
            row["field_sources"]["error"] = "trace_projection"
        if set(row["field_sources"].values()) == {"diagnostic_events", "trace_projection"}:
            row["evidence_source"] = "mixed"
    return list(rows.values())
