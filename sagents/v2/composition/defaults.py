"""Shared component choices for SDK and Desktop; no personal settings."""

from pathlib import Path
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig

DEFAULT_COMPONENTS = {
    "skill.loading": "sage.skill.loading.lazy",
    "agent.continuation-policy": "sage.agent.continuation.llm-judge",
    "context.unit-compactor": "sage.context.unit-compactor.reference",
    "context.reducer": "sage.context.reducer.persistent-summary",
    "context.summarizer": "sage.context.summarizer.model",
    "context.summary-store": "sage.context.summary-store.session-derived",
    "memory.provider": "sage.memory.filesystem-bm25",
    "memory.recall-query": "sage.memory.recall-query.llm",
    "tool.selection-policy": "sage.tool-selection.llm",
    "session-memory.provider": "sage.session-memory.sqlite-bm25",
    "observability.diagnostic-sink": "sage.observability.filesystem",
    "observability.log-sink": "sage.logging.filesystem",
    "execution.sandbox": "sage.sandbox.local-workspace",
    "session.store": "sage.session.filesystem",
    "workspace.initializer": "sage.workspace.initializer.claw",
}


def default_runtime(session_root: str | Path = ".runtime/sagents") -> RuntimeConfig:
    root = Path(session_root).expanduser().resolve()
    paths = {
        "session.store": {"root": str(root)},
        "memory.provider": {"root": str(root / "memory")},
        "session-memory.provider": {"root": str(root / "session-memory")},
        "observability.diagnostic-sink": {
            "root": str(root / "sessions"),
            "legacy_root": str(root / "diagnostics"),
        },
        "observability.log-sink": {"root": str(root / "logs")},
        "workspace.initializer": {"language": "en"},
    }
    # Sandbox acquisition requires the host's workspace and execution binding.
    return RuntimeConfig(
        capabilities={
            key: CapabilitySelection(plugin=plugin, config=paths.get(key, {}))
            for key, plugin in DEFAULT_COMPONENTS.items()
            if key != "execution.sandbox"
        }
    )


DEFAULT_SANDBOX_CONFIGS = {
    "sage.sandbox.local-workspace": {
        "workspace_root": "/workspace",
        "workspace_path_mode": "host",
        "workspace_mapping": "active_workspace",
        "filesystem_mode": "workspace",
    },
    "sage.sandbox.ephemeral": {
        "workspace_root": "/workspace",
        "workspace_path_mode": "virtual",
        "workspace_mapping": "isolated",
        "filesystem_mode": "workspace",
    },
}
