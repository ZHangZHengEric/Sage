"""Phoenix SpanQuery requests and multipart table decoding."""

from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
import json

from sagents.v2.runtime.observability.plugins._shared.query import request


def attribute(key):
    return "attributes" + "".join(
        "[" + json.dumps(part) + "]" for part in key.split(".")
    )


def table_rows(content, content_type):
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode()
        + content
    )
    if not message.is_multipart():
        raise ValueError("Phoenix SpanQuery did not return a multipart table")
    parts = list(message.iter_parts())
    if len(parts) != 1 or parts[0].get_content_type() != "application/json":
        raise ValueError("Invalid Phoenix SpanQuery response")
    payload = parts[0].get_payload(decode=True)
    if not isinstance(payload, (str, bytes, bytearray)):
        raise ValueError("Invalid Phoenix SpanQuery payload")
    table = json.loads(payload)
    # Phoenix prefixes table-schema column/index labels to preserve their names.
    return [
        {key.split("_", 1)[1]: value for key, value in row.items()}
        for row in table["data"]
    ]


async def performance_spans(source, client, *, start, end, agent_id=""):
    fields = ["name", "start_time", "context.trace_id", "context.span_id"]
    attributes = [
        "session_id",
        "run_id",
        "agent_id",
        "sage.performance.format",
        "sage.performance.data",
        "sage.performance.incomplete",
    ]
    projection = {key: {"key": key} for key in fields}
    projection.update({key: {"key": attribute(key)} for key in attributes})
    base = [
        'name == "agent.run"',
        f"{attribute('sage.performance.service')} == {json.dumps(source.service)}",
        f"{attribute('sage.performance.environment')} == {json.dumps(source.environment)}",
        f'{attribute("sage.performance.format")} == "events/v3"',
    ]
    if agent_id:
        base.append(f"{attribute('agent_id')} == {json.dumps(agent_id)}")

    async def query(extra, limit):
        body = {
            "queries": [
                {
                    "select": projection,
                    "filter": {"condition": " and ".join([*base, *extra])},
                    "index": {"key": "context.span_id"},
                }
            ],
            "limit": limit,
        }
        content, content_type = await request(
            source,
            client,
            "/v1/spans",
            {"project_name": source.project},
            method="POST",
            body=body,
            headers={"Accept": "application/json"},
        )
        import asyncio

        rows = await asyncio.to_thread(table_rows, content, content_type)
        return [
            {
                "name": row["name"],
                "start_time": row["start_time"],
                "context": {
                    "span_id": row["context.span_id"],
                    "trace_id": row["context.trace_id"],
                },
                "attributes": {key: row.get(key) for key in attributes},
            }
            for row in rows
        ]

    # Filter SDK entry time directly, not execution span start_time. In particular
    # never expand a historical cohort through the current wall clock.
    dates = [
        datetime.fromtimestamp(value, timezone.utc).isoformat()
        for value in (start, end)
    ]
    entry = attribute("sage.performance.started_at")
    found = await query(
        [f"{entry} >= {json.dumps(dates[0])}", f"{entry} < {json.dumps(dates[1])}"],
        source.max_spans + 1,
    )
    truncated = len(found) > source.max_spans
    ids = sorted({row["attributes"]["run_id"] for row in found[: source.max_spans]})
    spans = []
    for offset in range(0, len(ids), 100):
        # Membership is an OR over Run ids. Repeated REST attributes are AND,
        # and therefore cannot express this batch without the SpanQuery DSL.
        batch = await query(
            [f"{attribute('run_id')} in {json.dumps(ids[offset : offset + 100])}"],
            source.max_spans - len(spans) + 1,
        )
        spans.extend(batch)
        if len(spans) > source.max_spans:
            return spans[: source.max_spans], True
    return spans, truncated
