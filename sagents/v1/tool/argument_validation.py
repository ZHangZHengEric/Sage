"""Side-effect-free argument diagnostics using the tool's discovered contract.

Do not coerce, drop or replay arguments. Return field names and schema structure,
never argument values (which may contain credentials or personal content).
"""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any


def argument_contract_error(tool: Any, arguments: dict[str, Any]) -> dict[str, Any] | None:
    properties = getattr(tool, "parameters", {}) or {}
    schema = getattr(tool, "input_schema", None) or {}
    required = schema.get("required", getattr(tool, "required", []) or [])
    # Trusted identities are injected again by the execution transport.
    injected = {"session_id", "user_id", "sandbox_approval_mode", "command_policy"}
    missing = sorted(name for name in required if name not in arguments and name not in injected)
    # MCP schemas follow JSON Schema: absent additionalProperties means open.
    # Built-in Python tools instead have a callable signature to check.
    accepts_extra = bool(schema) and schema.get("additionalProperties", True) is not False
    func = getattr(tool, "func", None)
    if callable(func):
        try:
            accepts_extra |= any(p.kind == p.VAR_KEYWORD for p in inspect.signature(func).parameters.values())
        except (TypeError, ValueError):
            pass
    # Complex schemas may define names through branches; leave them to the server.
    accepts_extra |= any(k in schema for k in ("oneOf", "anyOf", "allOf", "patternProperties"))
    unknown = [] if accepts_extra else sorted(set(arguments) - set(properties) - injected)
    if not missing and not unknown:
        return None
    containers = {
        name: {"fields": sorted(prop["properties"]), "required": prop.get("required", [])}
        for name, prop in properties.items()
        if isinstance(prop, dict) and isinstance(prop.get("properties"), dict)
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            schema or {"properties": properties, "required": required},
            sort_keys=True,
            default=str,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()[:16]
    return {
        "success": False,
        "status": "error",
        "error_code": "INVALID_ARGUMENT",
        "tool_name": tool.name,
        "schema_hash": fingerprint,
        "message": "Correct the missing or unknown fields using the current tool schema, then retry only this failed call. No tool was executed.",
        "missing_fields": missing,
        "unknown_fields": unknown,
        "allowed_fields": sorted(set(properties) - injected),
        "object_fields": containers,
    }
