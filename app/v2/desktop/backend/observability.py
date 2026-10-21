"""Select the process observation provider once, before Desktop startup logging."""

from __future__ import annotations

import json
from pathlib import Path
from jsonschema import validate
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.observability import create_observability_provider


def create_desktop_observability(runtime_root: Path):
    from .package import desktop_v2_manifest

    settings_path = runtime_root / "settings.json"
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    selection = desktop_v2_manifest(
        session_root=runtime_root,
        component_selections=settings.get("component_selections", {}),
        component_configs=settings.get("component_configs", {}),
    ).runtime.capabilities["observability.provider"]
    registry = builtin_extension_registry()
    descriptor = registry.get(selection.plugin).descriptor
    if not descriptor.availability.available:
        raise ValueError(f"Observation provider {selection.plugin} is unavailable")
    validate(selection.config, descriptor.config_schema)
    return create_observability_provider(selection.plugin, selection.config)
