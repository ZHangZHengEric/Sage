"""Restore and assemble captured observations independently of backend transport."""

from datetime import datetime, timezone
import json
from .models import model_evidence
from .tools import tool_evidence


def _timestamp(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.timestamp()


def _captured_records(spans, restored, *, session_id, run_ids):
    """Read dedicated request, response and log records inside the authorized scope."""
    models, logs = {}, []
    records = [(_timestamp(at), attrs) for at, attrs in restored]
    stream_parts = {}
    for span in spans:
        for event in span.get("events", []):
            attrs = event.get("attributes", {})
            if "sage.diagnostic.data" in attrs:
                # Scope is validated on both the containing span and event.
                if (
                    attrs.get("session_id") != session_id
                    or attrs.get("run_id") not in run_ids
                ):
                    continue
                records.append((_timestamp(event["timestamp"]), attrs))
    for observed, attrs in sorted(records, key=lambda r: r[0]):
        payload = json.loads(attrs["sage.diagnostic.data"])
        if attrs["sage.diagnostic.kind"] == "log":
            logs.append(
                dict(
                    payload,
                    session_id=attrs["session_id"],
                    run_id=attrs["run_id"],
                )
            )
        else:
            identity = (attrs["run_id"], payload["request_id"])
            row = models.setdefault(
                identity,
                dict(
                    session_id=session_id,
                    run_id=attrs["run_id"],
                    request_id=payload["request_id"],
                ),
            )
            kind = attrs["sage.diagnostic.kind"]
            if kind in {"stream_wire", "stream_normalized"}:
                stream_parts.setdefault(identity, {}).setdefault(kind, {})[
                    payload["sequence"]
                ] = payload["event"]
                continue
            row.update(payload)
            observed_at = datetime.fromtimestamp(observed, timezone.utc).isoformat()
            if kind == "request":
                row.update(status="started", started_at=observed_at)
            elif kind in {"response", "failure"}:
                row.update(
                    status="completed" if kind == "response" else "failed",
                    completed_at=observed_at,
                )
    return models, logs, stream_parts


def _restore_streams(spans, models, stream_parts, gaps, *, session_id):
    """Merge stream manifests, ordered chunks and explicit loss markers."""
    for span in spans:
        attrs = span.get("attributes", {})
        if span.get("name") != "model.request" or not attrs.get(
            "sage.diagnostic.stream_finalized"
        ):
            continue
        identity = attrs["run_id"], attrs["request_id"]
        row = models.setdefault(
            identity,
            dict(session_id=session_id, run_id=identity[0], request_id=identity[1]),
        )
        stream = row.setdefault("stream", {})
        stream.setdefault("chunk_format", "chunks/v1")
        for field in (
            "wire_event_count",
            "normalized_event_count",
            "dropped_wire_events",
            "dropped_normalized_events",
        ):
            stream.setdefault(field, attrs.get("sage.diagnostic." + field, 0))
    for identity, row in models.items():
        if "stream" in row or identity in stream_parts:
            stream = row.setdefault("stream", {})
            parts = stream_parts.get(identity, {})
            if "chunk_format" in stream or parts:
                for kind, field, count, dropped in (
                    (
                        "stream_wire",
                        "wire_events",
                        "wire_event_count",
                        "dropped_wire_events",
                    ),
                    (
                        "stream_normalized",
                        "normalized_events",
                        "normalized_event_count",
                        "dropped_normalized_events",
                    ),
                ):
                    values = parts.get(kind, {})
                    stream[field] = [values[seq] for seq in sorted(values)]
                    missing = max(0, stream.get(count, len(values)) - len(values))
                    stream[dropped] = max(stream.get(dropped, 0), missing)
                stream["complete"] = (
                    "chunk_format" in stream
                    and not stream.get("dropped_wire_events")
                    and not stream.get("dropped_normalized_events")
                )
                stream["wire_capture_available"] = bool(stream.get("wire_events"))
                row["truncated"] = not stream["complete"]
    for gap in gaps:
        if gap["kind"] == "log":
            continue
        identity = gap["run_id"], gap["request_id"]
        row = models.setdefault(
            identity,
            dict(
                session_id=session_id,
                run_id=gap["run_id"],
                request_id=gap["request_id"],
            ),
        )
        row["truncated"] = True
        row.setdefault("evidence_gaps", []).append(gap)
        row.setdefault("stream", {})["complete"] = False


def assemble_evidence(spans, restored, gaps, *, session_id, run_ids, raw_capture):
    """Assemble normalized evidence without querying a backend or owning capture state."""
    models, logs, stream_parts = _captured_records(
        spans,
        restored,
        session_id=session_id,
        run_ids=run_ids,
    )
    _restore_streams(spans, models, stream_parts, gaps, session_id=session_id)
    projected_models = model_evidence(spans, models.values())
    if raw_capture or any(
        s["attributes"].get("sage.diagnostic.format") == "chunks/v1" for s in spans
    ):
        for row in projected_models:
            fields = row.get("field_sources", {})
            complete = bool(
                fields.get("request") == "diagnostic_events"
                and (
                    fields.get("response") == "diagnostic_events"
                    or fields.get("error") == "diagnostic_events"
                )
                and row.get("stream", {}).get("complete")
                and not row.get("evidence_gaps")
            )
            row["raw_capture_complete"] = complete
            row["truncated"] = bool(row.get("truncated") or not complete)
    log_counts = [
        s["attributes"]["sage.diagnostic.log_count"]
        for s in spans
        if s.get("name") == "agent.run"
        and "sage.diagnostic.log_count" in s["attributes"]
    ]
    expected_logs = sum(log_counts)
    dropped_logs = max(
        sum(gap["kind"] == "log" for gap in gaps), expected_logs - len(logs), 0
    )
    logs_complete = bool(log_counts and expected_logs == len(logs) and not dropped_logs)
    return {
        **tool_evidence(spans, logs),
        "models": projected_models,
        "model_request_ids": sorted({r["request_id"] for r in projected_models}),
        "capture_modes": sorted(
            {s["attributes"].get("sage.content.mode", "unknown") for s in spans}
        ),
        "logs": logs,
        "traces": spans,
        "evidence_gaps": gaps,
        "dropped_logs": dropped_logs,
        "logs_complete": logs_complete if raw_capture or log_counts else None,
        "expected_log_records": expected_logs if log_counts else None,
        "raw_model_streams_available": any(
            row.get("stream", {}).get("wire_capture_available", False)
            for row in projected_models
        ),
    }
