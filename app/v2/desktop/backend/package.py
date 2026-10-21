"""Desktop process package: product defaults become manifest selections."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sagents.v2.composition.defaults import DEFAULT_COMPONENTS, default_runtime

from sagents.v2.package.manifest.agents import (
    AgentDefinition,
    ApplicationEntrypoint,
    Instructions,
)
from sagents.v2.package.manifest.root import ManifestMetadata, SageManifest
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig


DESKTOP_COMPONENTS = {
    "skill.loading": {
        "default": DEFAULT_COMPONENTS["skill.loading"],
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
    "agent.continuation-policy": {
        "default": DEFAULT_COMPONENTS["agent.continuation-policy"],
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "run",
    },
    "context.reducer": {
        "default": DEFAULT_COMPONENTS["context.reducer"],
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "tenant",
    },
    "context.summarizer": {
        "default": DEFAULT_COMPONENTS["context.summarizer"],
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
    "context.summary-store": {
        "default": DEFAULT_COMPONENTS["context.summary-store"],
        "selection_mode": "host",
        "apply_mode": "restart",
        "scope": "process",
    },
    "memory.provider": {
        "default": DEFAULT_COMPONENTS["memory.provider"],
        "selection_mode": "user",
        "apply_mode": "restart",
        "scope": "process",
    },
    "memory.recall-query": {
        "default": DEFAULT_COMPONENTS["memory.recall-query"],
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
    "tool.selection-policy": {
        "default": DEFAULT_COMPONENTS["tool.selection-policy"],
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
    "session-memory.provider": {
        "default": DEFAULT_COMPONENTS["session-memory.provider"],
        "selection_mode": "user",
        "apply_mode": "restart",
        "scope": "process",
    },
    "observability.provider": {
        "default": DEFAULT_COMPONENTS["observability.provider"],
        "selection_mode": "user",
        "apply_mode": "restart",
        "scope": "process",
    },
    "execution.sandbox": {
        "default": DEFAULT_COMPONENTS["execution.sandbox"],
        "selection_mode": "host",
        "apply_mode": "next_run",
        "scope": "run",
    },
    "session.store": {
        "default": DEFAULT_COMPONENTS["session.store"],
        "selection_mode": "host",
        "apply_mode": "restart",
        "scope": "process",
    },
    "workspace.initializer": {
        "default": DEFAULT_COMPONENTS["workspace.initializer"],
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
}
DESKTOP_COMPONENT_DEFAULTS = {
    capability: str(spec["default"]) for capability, spec in DESKTOP_COMPONENTS.items()
}

# The standard App consumes these at build and Agent revision loading.
# Sandbox stays a host binding.
_MANIFEST_CAPABILITIES = (
    "skill.loading",
    "session.store",
    "memory.provider",
    "session-memory.provider",
    "observability.provider",
    "context.reducer",
    "context.summarizer",
    "context.summary-store",
    "agent.continuation-policy",
    "workspace.initializer",
    "tool.selection-policy",
    "memory.recall-query",
)


def stable_component_id(capability: str, plugin_id: str) -> str:
    """Accept settings written before Desktop exposed stable extension IDs."""

    if capability == "agent.continuation-policy" and plugin_id in {
        "hybrid",
        "sage.agent.continuation.hybrid",
    }:
        return "sage.agent.continuation.llm-judge"
    if capability == "tool.selection-policy" and plugin_id in {
        "hybrid",
        "sage.tool-selection.hybrid",
    }:
        return "sage.tool-selection.llm"
    if "." in plugin_id:
        return plugin_id
    prefixes = {
        "skill.loading": "sage.skill.loading.",
        "agent.continuation-policy": "sage.agent.continuation.",
        "context.reducer": "sage.context.reducer.",
        "context.summarizer": "sage.context.summarizer.",
        "context.summary-store": "sage.context.summary-store.",
        "memory.provider": "sage.memory.",
        "memory.recall-query": "sage.memory.recall-query.",
        "session-memory.provider": "sage.session-memory.",

        "execution.sandbox": "sage.sandbox.",
        "session.store": "sage.session.",
        "workspace.initializer": "sage.workspace.initializer.",
        "tool.selection-policy": "sage.tool-selection.",
    }
    return prefixes[capability] + plugin_id


def desktop_v2_manifest(
    *,
    session_root: str | Path,
    component_selections: Mapping[str, str] | None = None,
    component_configs: Mapping[str, Mapping[str, Any]] | None = None,
    language: str = "en",
) -> SageManifest:
    """Encode Desktop product defaults as a Builder-consumable package.

    Catalog, session index, MCP records, and settings stay product-owned.
    """

    root = Path(session_root).expanduser().resolve()
    return SageManifest(
        kind="application",
        metadata=ManifestMetadata(
            id="com.sage.desktop-v2",
            version="0.1.0",
            name="Sage Desktop v2",
        ),
        runtime=RuntimeConfig(
            capabilities=_runtime_capabilities(
                root,
                selections=component_selections or {},
                configs=component_configs or {},
                language=language,
            )
        ),
        agents={
            "main": AgentDefinition(
                name="Desktop Assistant",
                instructions=Instructions(
                    inline="Be helpful, concise, and explicit about uncertainty."
                ),
            )
        },
        entrypoint=ApplicationEntrypoint(agent="main"),
    )


def _runtime_capabilities(
    session_root: Path,
    *,
    selections: Mapping[str, str],
    configs: Mapping[str, Mapping[str, Any]],
    language: str,
) -> dict[str, CapabilitySelection]:
    from sagents.v2.package.manifest.runtime import REMOVED_CAPABILITIES
    invalid = REMOVED_CAPABILITIES.intersection(selections) | REMOVED_CAPABILITIES.intersection(configs)
    if invalid:
        raise ValueError(f"removed capability configuration: {', '.join(sorted(invalid))}")
    paths = {
        key: selection.config
        for key, selection in default_runtime(session_root).capabilities.items()
    }
    capabilities: dict[str, CapabilitySelection] = {}
    for capability in _MANIFEST_CAPABILITIES:
        plugin_id = stable_component_id(
            capability,
            selections.get(capability, DESKTOP_COMPONENT_DEFAULTS[capability]),
        )
        host_config = dict(paths.get(capability, {}))
        if capability == "observability.provider":
            from sagents.v2.runtime.extensions.official import builtin_extension_registry
            properties = builtin_extension_registry().get(plugin_id).descriptor.config_schema["properties"]
            host_config = {key: value for key, value in host_config.items() if key in properties}

        if capability == "workspace.initializer":
            host_config.pop("language", None)
        if (
            capability == "workspace.initializer"
            and plugin_id == "sage.workspace.initializer.claw"
        ):
            host_config["language"] = language
        config = {
            **host_config,
            **dict(configs.get(capability, {})),
        }
        capabilities[capability] = CapabilitySelection(plugin=plugin_id, config=config)
    return capabilities


# Product-owned bindings are displayed when a real value exists, but not editable.
DESKTOP_COMPONENT_CONFIG_LOCKS = {
    "context.summarizer": {"model_binding": "primary"},
    "agent.continuation-policy": {"model_binding": "fast"},
}

_DESKTOP_HOST_CONFIG_FIELDS = {
    "memory.recall-query": {"language"},
    "workspace.initializer": {"language"},
    "memory.provider": {"root"},
    "session-memory.provider": {"root"},
    "session.store": {"root", "dsn"},
    "observability.provider": {"log_root", "diagnostics_root"},
    "execution.sandbox": {"verification_key"},
}


def desktop_component_config_schema(
    capability: str,
    schema: Mapping[str, Any] | None,
    *,
    language: str | None = None,
    plugin_id: str | None = None,
) -> dict:
    result = dict(schema or {})
    properties = {
        key: dict(value) for key, value in result.get("properties", {}).items()
    }
    for key in _DESKTOP_HOST_CONFIG_FIELDS.get(capability, set()):
        if key in properties:
            properties[key]["readOnly"] = True
            if key == "language" and language is not None:
                properties[key].update(default=language, const=language)
    for key, value in DESKTOP_COMPONENT_CONFIG_LOCKS.get(capability, {}).items():
        if key in properties:
            properties[key] = {
                **properties[key],
                "default": value,
                "const": value,
                "readOnly": True,
            }
    # Local selection policies never call a model; this shared legacy field is inert.
    if plugin_id in {"sage.tool-selection.lexical", "sage.tool-selection.recent"}:
        properties.pop("model_timeout_seconds", None)
    if plugin_id == "sage.agent.continuation.llm-judge":
        properties.pop("repeat_threshold", None)
    result["properties"] = properties
    return result
