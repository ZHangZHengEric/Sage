"""Bounded model-facing training evidence; original report/journal stays lossless."""

from __future__ import annotations

import json


def training_feedback(result):
    data = result.model_dump(mode="json")

    def observation(value):
        evidence = value["evidence"]
        summary = {
            key: evidence[key]
            for key in ("session_id", "run_id", "outcome", "generated_tool_audit")
            if key in evidence
        }
        # Host-provided compact execution trace retains tool arguments and the
        # end of long multi-turn episodes. It is still untrusted task evidence.
        trace = evidence.get("training_trace")
        if isinstance(trace, str):
            summary["training_trace"] = trace[:8192]
            summary["training_trace_truncated"] = len(trace) > 8192
        error = evidence.get("error")
        if isinstance(error, dict):
            summary["error"] = {
                key: error[key]
                for key in ("code", "category", "message")
                if key in error
            }
            diagnostic = (error.get("metadata") or {}).get("diagnostic_message")
            if diagnostic:
                summary["error"]["diagnostic_message"] = str(diagnostic)[:512]
        events = evidence.get("runtime_events") or []
        remaining = 2048
        tool_errors = []
        seen_errors = set()
        for event in reversed(events):
            data = event.get("data", {})
            item = (data.get("item") or {}).get("data", {})
            source = item if item.get("kind") == "tool_result" else data
            failure = source.get("error")
            if not isinstance(failure, dict):
                continue
            diagnostic = (failure.get("metadata") or {}).get("diagnostic_message")
            detail = {
                "tool_name": str(
                    data.get("tool_name") or source.get("tool_name") or ""
                )[:64],
                "code": str(failure.get("code", ""))[:64],
                "diagnostic": str(diagnostic or failure.get("message", ""))[:256],
            }
            identity = tuple(detail.values())
            if identity in seen_errors:
                continue
            seen_errors.add(identity)
            tool_errors.append(detail)
            remaining -= len(json.dumps(detail, ensure_ascii=False))
            if len(tool_errors) == 2:
                break
        summary["tool_errors"] = list(reversed(tool_errors))
        selected = []
        for event in reversed(events):
            if not remaining:
                break
            text = json.dumps(event.get("data", event), ensure_ascii=False)
            limit = min(512, remaining)
            selected.append(
                {
                    "type": event.get("type"),
                    "data_excerpt": text[:limit],
                    "truncated": len(text) > limit,
                }
            )
            remaining -= min(len(text), limit)
        summary["tool_events"] = list(reversed(selected))
        summary["evidence_summarized"] = True
        summary["recorded_event_count"] = len(events)
        value["evidence"] = summary
        if len(value["output"]) > 4096:
            value["output"] = value["output"][:2048] + "\n[... middle omitted ...]\n" + value["output"][-2048:]
            value["output_truncated"] = True
        return value

    def trial(value):
        value["observation"] = observation(value["observation"])
        for turn in value.get("dialogue", []):
            turn["observation"] = observation(turn["observation"])
        return value

    trial(data)
    for item in data["trials"]:
        trial(item)
    return data
