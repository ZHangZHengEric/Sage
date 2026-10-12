"""Bounded model-facing training evidence; original report/journal stays lossless."""

from __future__ import annotations

import json


def training_feedback(result):
    data = result.model_dump(mode="json")

    def observation(value):
        evidence = value["evidence"]
        summary = {
            key: evidence[key]
            for key in ("session_id", "run_id", "outcome")
            if key in evidence
        }
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
            value["output"] = value["output"][:4096]
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
