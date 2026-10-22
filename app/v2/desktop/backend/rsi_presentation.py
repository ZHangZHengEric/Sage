"""Small Desktop polling views; durable execution evidence remains untouched."""
from __future__ import annotations


def compact_rsi_payload(value):
    if isinstance(value, list):
        return [compact_rsi_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    if (value.get("state") in ("completed", "failed", "cancelled", "suspended")
            and isinstance(value.get("output"), str) and isinstance(value.get("evidence"), dict)):
        heavy = {"runtime_events", "final_items", "training_trace"}
        evidence = {key: item for key, item in value["evidence"].items() if key not in heavy}
        if heavy.intersection(value["evidence"]):
            evidence["execution_details_omitted"] = True
        return {**value, "evidence": evidence}
    if value.get("event") == "agent_call_started" and isinstance(value.get("data"), dict):
        return {key: compact_rsi_payload({k: v for k, v in item.items() if k != "request"}
                                        if key == "data" else item)
                for key, item in value.items()}
    is_agent_call = isinstance(value.get("role"), str) and isinstance(value.get("observation"), dict)
    # These are user/package data, not report envelopes. Never rewrite their
    # contents even when a literal happens to resemble an execution record.
    literal_keys = {"manifest", "files", "tool_definitions", "skill_definitions", "input_schema",
                    "expression", "case", "user_context", "reference_answer"}
    return {key: item if key in literal_keys else compact_rsi_payload(item) for key, item in value.items()
            if not (is_agent_call and key == "request")}
