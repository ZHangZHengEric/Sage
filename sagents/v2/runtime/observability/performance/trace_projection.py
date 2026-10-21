"""Decode normalized performance observations from vendor-neutral spans."""

import json
from .aggregation import normalize_timing_rows, timestamp

SPAN_NAME = "agent.run"
PAYLOAD = "sage.performance.data"


def _span_start(span) -> float:
    value = timestamp(span["start_time"])
    if value is None:
        raise ValueError("performance span is missing its start time")
    return value


def timing_rows(spans):
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
    return normalize_timing_rows(rows)
