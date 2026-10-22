"""Host-owned checks on recorded deterministic generated-tool executions."""

from __future__ import annotations


def generated_tool_audit(evidence):
    events = evidence.get("runtime_events")
    complete = (
        isinstance(events, list) and evidence.get("runtime_events_truncated") is False
    )
    events = events if isinstance(events, list) else []
    names = {}
    for event in events:
        data = event.get("data", {})
        item = (data.get("item") or {}).get("data", {})
        for source in (data, item):
            if source.get("tool_call_id") and source.get("tool_name"):
                names[source["tool_call_id"]] = source["tool_name"]
    failures = {}
    for event in events:
        data = event.get("data", {})
        item = (data.get("item") or {}).get("data", {})
        source = item if item.get("kind") == "tool_result" else data
        call_id = source.get("tool_call_id")
        name = source.get("tool_name") or names.get(call_id, "")
        if not name.startswith("rsi_"):
            continue
        error = source.get("error")
        if not error and not (
            source.get("kind") == "tool" and source.get("state") == "failed"
        ):
            continue
        error = error if isinstance(error, dict) else {}
        failures[call_id or str(len(failures))] = {
            "tool_name": name,
            "code": error.get("code", "tool.failed"),
            "diagnostic": str(
                (error.get("metadata") or {}).get("diagnostic_message")
                or error.get("message", "Recorded tool failure")
            )[:512],
        }
    return {
        "required": True,
        "complete": complete,
        "passed": complete and not failures,
        "failure_count": len(failures),
        "failures": list(failures.values())[:16],
    }
