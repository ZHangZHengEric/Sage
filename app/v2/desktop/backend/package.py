"""Desktop process package: product defaults become manifest selections."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sagents.v2.package.manifest.agents import (
    AgentDefinition,
    ApplicationEntrypoint,
    Instructions,
)
from sagents.v2.package.manifest.root import ManifestMetadata, SageManifest
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig


DESKTOP_COMPONENTS = {
    "skill.loading": {
        "default": "sage.skill.loading.lazy",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
    "agent.continuation-policy": {
        "default": "sage.agent.continuation.deterministic",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "run",
    },
    "context.token-estimator": {
        "default": "sage.context.token-estimator.json-heuristic",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "tenant",
    },
    "context.reducer": {
        "default": "sage.context.reducer.persistent-summary",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "tenant",
    },
    "context.summarizer": {
        "default": "sage.context.summarizer.model",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
    "context.summary-store": {
        "default": "sage.context.summary-store.session-derived",
        "selection_mode": "host",
        "apply_mode": "restart",
        "scope": "process",
    },
    "memory.provider": {
        "default": "sage.memory.filesystem-bm25",
        "selection_mode": "user",
        "apply_mode": "restart",
        "scope": "process",
    },
    "memory.recall-query": {
        "default": "sage.memory.recall-query.direct",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
    "tool.selection-policy": {
        "default": "sage.tool-selection.llm",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
    "session-memory.provider": {
        "default": "sage.session-memory.sqlite-bm25",
        "selection_mode": "user",
        "apply_mode": "restart",
        "scope": "process",
    },
    "observability.diagnostic-sink": {
        "default": "sage.observability.filesystem",
        "selection_mode": "host",
        "apply_mode": "restart",
        "scope": "process",
    },
    "observability.log-sink": {
        "default": "sage.logging.filesystem",
        "selection_mode": "user",
        "apply_mode": "restart",
        "scope": "process",
    },
    "execution.sandbox": {
        "default": "sage.sandbox.local-workspace",
        "selection_mode": "host",
        "apply_mode": "next_run",
        "scope": "run",
    },
    "session.store": {
        "default": "sage.session.filesystem",
        "selection_mode": "host",
        "apply_mode": "restart",
        "scope": "process",
    },
    "workspace.initializer": {
        "default": "sage.workspace.initializer.claw",
        "selection_mode": "user",
        "apply_mode": "next_run",
        "scope": "agent",
    },
}
DESKTOP_COMPONENT_DEFAULTS = {
    capability: str(spec["default"]) for capability, spec in DESKTOP_COMPONENTS.items()
}

# Builder consumes these at process build or via materialize_agent.
# Sandbox stays a host binding.
_MANIFEST_CAPABILITIES = (
    "skill.loading",
    "session.store",
    "memory.provider",
    "session-memory.provider",
    "observability.diagnostic-sink",
    "observability.log-sink",
    "context.token-estimator",
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
    if plugin_id.startswith("sage."):
        return plugin_id
    prefixes = {
        "skill.loading": "sage.skill.loading.",
        "agent.continuation-policy": "sage.agent.continuation.",
        "context.token-estimator": "sage.context.token-estimator.",
        "context.reducer": "sage.context.reducer.",
        "context.summarizer": "sage.context.summarizer.",
        "context.summary-store": "sage.context.summary-store.",
        "memory.provider": "sage.memory.",
        "memory.recall-query": "sage.memory.recall-query.",
        "session-memory.provider": "sage.session-memory.",
        "observability.diagnostic-sink": "sage.observability.",
        "observability.log-sink": "sage.logging.",
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
    paths = {
        "session.store": {"root": str(session_root)},
        "memory.provider": {"root": str(session_root / "memory")},
        "session-memory.provider": {"root": str(session_root / "session-memory")},
        "observability.diagnostic-sink": {
            "root": str(session_root / "sessions"),
            "legacy_root": str(session_root / "diagnostics"),
        },
        "observability.log-sink": {"root": str(session_root / "logs")},
    }
    capabilities: dict[str, CapabilitySelection] = {}
    for capability in _MANIFEST_CAPABILITIES:
        plugin_id = stable_component_id(
            capability,
            selections.get(capability, DESKTOP_COMPONENT_DEFAULTS[capability]),
        )
        host_config = dict(paths.get(capability, {}))
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
    "context.summarizer": {"model_binding": "summary"},
    "agent.continuation-policy": {"model_binding": "fast"},
}

_DESKTOP_INJECTED_FIELDS = {
    "context.summarizer": {"model"},
    "context.reducer": {"store", "summarizer", "estimator", "unit_compactor"},
    "context.summary-store": {"derived_state"},
    "memory.recall-query": {"model", "language"},
    "workspace.initializer": {"language"},
    "agent.continuation-policy": {"model"},
    "memory.provider": {"root"},
    "session-memory.provider": {"root"},
    "session.store": {"root", "dsn"},
    "observability.log-sink": {"root"},
    "observability.diagnostic-sink": {"root", "legacy_root"},
    "execution.sandbox": {"verification_key", "process_handlers", "network_handlers"},
}


def desktop_component_config_schema(
    capability: str, schema: Mapping[str, Any] | None, *, language: str | None = None,
    plugin_id: str | None = None,
) -> dict:
    result = dict(schema or {})
    properties = {key: dict(value) for key, value in result.get("properties", {}).items()}
    for key in _DESKTOP_INJECTED_FIELDS.get(capability, set()):
        if key in properties:
            properties[key]["readOnly"] = True
            if key == "language" and language is not None:
                properties[key].update(default=language, const=language)
    for key, value in DESKTOP_COMPONENT_CONFIG_LOCKS.get(capability, {}).items():
        if key in properties:
            properties[key] = {**properties[key], "default": value, "const": value, "readOnly": True}
    # Local selection policies never call a model; this shared legacy field is inert.
    if plugin_id in {"sage.tool-selection.lexical", "sage.tool-selection.recent"}:
        properties.pop("model_timeout_seconds", None)
    if plugin_id == "sage.agent.continuation.llm-judge":
        properties.pop("repeat_threshold", None)
    result["properties"] = properties
    return result
