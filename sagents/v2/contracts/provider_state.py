"""Bounded, versioned envelopes for protocol-owned continuation state."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


PROVIDER_STATE_SCHEMA_VERSION = 1
MAX_PROVIDER_STATE_BYTES = 8 * 1024 * 1024
MAX_PROVIDER_STATE_NAMESPACES = 16
_NAMESPACE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def make_provider_state(namespace: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Create one current-version protocol namespace."""

    return {
        namespace: {
            "schema_version": PROVIDER_STATE_SCHEMA_VERSION,
            "payload": dict(payload),
        }
    }


def read_provider_state(
    state: Mapping[str, Any],
    namespace: str,
    *,
    supported_versions: frozenset[int] = frozenset({PROVIDER_STATE_SCHEMA_VERSION}),
) -> Mapping[str, Any] | None:
    """Read only the caller's namespace, with legacy-v0 replay compatibility."""

    value = state.get(namespace)
    if not isinstance(value, Mapping):
        return None
    if "schema_version" not in value and "payload" not in value:
        # Existing Session data predates the envelope. Adapters may replay it as
        # version 0, while every newly captured value uses the versioned form.
        return value
    version = value.get("schema_version")
    if version not in supported_versions:
        raise ValueError(
            f"unsupported provider_state version {version!r} for {namespace!r}"
        )
    payload = value.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError(f"provider_state payload for {namespace!r} must be an object")
    return payload


def validate_provider_state(value: dict[str, Any]) -> dict[str, Any]:
    """Reject unbounded/non-JSON opaque state before durable persistence."""

    if len(value) > MAX_PROVIDER_STATE_NAMESPACES:
        raise ValueError("provider_state contains too many protocol namespaces")
    for namespace, entry in value.items():
        if not _NAMESPACE.fullmatch(namespace):
            raise ValueError(f"invalid provider_state namespace {namespace!r}")
        if not isinstance(entry, dict):
            raise ValueError(f"provider_state namespace {namespace!r} must be an object")
        is_envelope = "schema_version" in entry or "payload" in entry
        if is_envelope:
            if set(entry) != {"schema_version", "payload"}:
                raise ValueError(
                    f"provider_state envelope for {namespace!r} has unknown fields"
                )
            version = entry.get("schema_version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise ValueError(
                    f"provider_state schema_version for {namespace!r} must be positive"
                )
            if not isinstance(entry.get("payload"), dict):
                raise ValueError(
                    f"provider_state payload for {namespace!r} must be an object"
                )
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("provider_state must be finite JSON data") from exc
    if len(encoded) > MAX_PROVIDER_STATE_BYTES:
        raise ValueError(
            f"provider_state exceeds {MAX_PROVIDER_STATE_BYTES} encoded bytes"
        )
    return value


__all__ = [
    "MAX_PROVIDER_STATE_BYTES",
    "MAX_PROVIDER_STATE_NAMESPACES",
    "PROVIDER_STATE_SCHEMA_VERSION",
    "make_provider_state",
    "read_provider_state",
    "validate_provider_state",
]
