"""Stable identities for host-selected service implementations."""
from __future__ import annotations

from typing import Any


def _service_composition_identity(provider: Any) -> dict[str, Any]:
    identity = getattr(provider, "composition_identity", None)
    if callable(identity):
        identity = identity()
    if identity is None:
        root = getattr(provider, "root", None)
        identity = str(root) if root is not None else None
    import sys
    module_name = type(provider).__module__
    source_hash = getattr(sys.modules.get(module_name), "__sage_source_sha256__", None)
    provider_type = f"source:{source_hash}:{type(provider).__qualname__}" if source_hash else f"{module_name}.{type(provider).__qualname__}"
    return {
        "type": provider_type,
        "identity": identity,
    }
