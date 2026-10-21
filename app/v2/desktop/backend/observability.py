"""Select the process observation provider once, before Desktop startup logging."""

from __future__ import annotations

import os
from pathlib import Path
from jsonschema import validate, ValidationError
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.observability import create_observability_provider


def normalize_observation_config(
    plugin_id: str, config: dict, *, registry=None
) -> dict:
    """Use the same defaults and startup checks before persisting a selection."""
    descriptor = (registry or builtin_extension_registry()).get(plugin_id).descriptor
    if not descriptor.availability.available:
        raise ValueError(f"Observation provider {plugin_id} is unavailable")
    schema = descriptor.config_schema
    defaults = {
        key: field["default"]
        for key, field in schema["properties"].items()
        if "default" in field and key not in {"log_root", "diagnostics_root"}
    }
    normalized = {**defaults, **config}
    try:
        validate(normalized, schema)
    except ValidationError as exc:
        raise ValueError(f"invalid observation configuration: {exc.message}") from exc
    if plugin_id == "sage.observability.phoenix":
        from sagents.v2.runtime.observability.plugins.phoenix import PhoenixTraceSink

        PhoenixTraceSink.validate_configuration(
            normalized["endpoint"], normalized["project_name"]
        )
    elif plugin_id == "sage.observability.langfuse":
        from sagents.v2.runtime.observability.plugins.langfuse import LangfuseTraceSink

        LangfuseTraceSink.validate_configuration(
            normalized["base_url"],
            os.getenv(normalized["public_key_env"], ""),
            os.getenv(normalized["secret_key_env"], ""),
            normalized["ingestion_version"],
        )
    return normalized


def create_desktop_observability(runtime_root: Path):
    from .package import desktop_v2_manifest
    from .settings_store import read_desktop_settings

    settings = read_desktop_settings(runtime_root / "settings.json")
    selection = desktop_v2_manifest(
        session_root=runtime_root,
        component_selections=settings.component_selections,
        component_configs=settings.component_configs,
    ).runtime.selections("observability.provider")[0]
    config = normalize_observation_config(selection.plugin, selection.config)
    return create_observability_provider(selection.plugin, config)
