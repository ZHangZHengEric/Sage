"""Project tool diagnostics from observation records without reading Run events."""

from __future__ import annotations

import json


def _value(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def tool_evidence(spans, logs):
    tools, failures, observed = [], [], set()
    exceptions = {}
    for log in logs:
        error = log.get("error") or {}
        if log.get("event") in {
            "tool.execution.exception",
            "tool.call.failed",
        } and error.get("stack_trace"):
            errors = exceptions.setdefault(
                (log.get("run_id"), log.get("tool_call_id")), []
            )
            if error not in errors:
                errors.append(error)
    for span in spans:
        if span.get("name") != "tool.call":
            continue
        attrs = span.get("attributes", {})
        key = attrs.get("run_id"), attrs.get("tool_call_id")
        observed.add(key)
        errors = exceptions.setdefault(key, [])
        for event in span.get("events", span.get("otlp", {}).get("events", [])):
            fields = event.get("attributes", {})
            if isinstance(fields, dict) and fields.get("exception.stacktrace"):
                exception = dict(
                    type=fields.get("exception.type"),
                    message=fields.get("exception.message"),
                    stack_trace=fields["exception.stacktrace"],
                )
                if exception not in errors:
                    errors.append(exception)
        result = _value(attrs.get("execution_result"))
        error = (
            _value(attrs.get("error"))
            or (result.get("error") if isinstance(result, dict) else None)
            or (errors[0] if errors else None)
        )
        status = span.get("status_code") or (
            span.get("otlp", {}).get("status") or {}
        ).get("code")
        outcome = attrs.get("outcome") or (
            "failed"
            if error or status in {"ERROR", 2}
            else "completed"
            if status in {"OK", 1}
            else "unknown"
        )
        tool = dict(
            run_id=key[0],
            tool_call_id=key[1],
            tool_name=attrs.get("tool_name"),
            operation_id=attrs.get("operation_id"),
            arguments=_value(attrs.get("arguments")),
            result=result,
            error=error,
            outcome=outcome,
            occurred_at=span.get("start_time"),
            trace_id=span.get("context", {}).get("trace_id"),
            span_id=span.get("context", {}).get("span_id"),
            result_available=isinstance(result, dict) and "tool_call_id" in result,
        )
        tools.append(tool)
    # Local diagnostics and historical exports can only show captured log metadata.
    for log in logs:
        key = log.get("run_id"), log.get("tool_call_id")
        event = log.get("event", "")
        if (
            key in observed
            or not key[1]
            or event
            not in {"tool.call.completed", "tool.call.failed", "tool.call.interrupted"}
        ):
            continue
        observed.add(key)
        attrs = log.get("attributes", {})
        tools.append(
            dict(
                run_id=key[0],
                tool_call_id=key[1],
                tool_name=attrs.get("tool_name"),
                operation_id=attrs.get("operation_id"),
                error=log.get("error"),
                outcome=event.rsplit(".", 1)[-1],
                occurred_at=log.get("timestamp"),
                result_available=False,
            )
        )
    for tool in tools:
        if tool["outcome"] not in {"failed", "unknown", "interrupted"}:
            continue
        errors = exceptions.get((tool["run_id"], tool["tool_call_id"]), [])
        failures.append(
            {**tool, "exceptions": errors, "stack_trace_available": bool(errors)}
        )
    return {
        "tools": tools,
        "failures": failures,
        "tool_results_available": bool(tools)
        and all(t["result_available"] for t in tools),
    }
