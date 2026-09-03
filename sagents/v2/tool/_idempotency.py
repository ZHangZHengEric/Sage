"""Shared Tool-call idempotency helpers."""

from __future__ import annotations

import hashlib
import json

from sagents.v2.tool.contracts import ToolCall


def call_fingerprint(call: ToolCall) -> str:
    """Bind an idempotency key to the exact wire request it represents."""

    payload = call.model_dump(mode="json", exclude={"idempotency_key"})
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
