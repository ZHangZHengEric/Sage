"""Shared component choices for SDK and Desktop; no personal settings."""

from pathlib import Path
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig

DEFAULT_COMPONENTS = {
    "skill.management": "sage.skill.filesystem",
    "skill.provider": "sage.skill.filesystem",
    "skill.loading": "sage.skill.loading.lazy",
    "agent.continuation-policy": "sage.agent.continuation.llm-judge",
    "context.reducer": "sage.context.reducer.persistent-summary",
    "context.summarizer": "sage.context.summarizer.model",
    "context.summary-store": "sage.context.summary-store.session-derived",
    "memory.provider": "sage.memory.filesystem-bm25",
    "memory.recall-query": "sage.memory.recall-query.llm",
    "tool.selection-policy": "sage.tool-selection.llm",
    "tool.result-processor": "sage.tool.result-processor.file",
    "session-memory.provider": "sage.session-memory.sqlite-bm25",
    "observability.provider": "sage.observability.local",
    "execution.sandbox": "sage.sandbox.local-workspace",
    "session.store": "sage.session.filesystem",
    "workspace.initializer": "sage.workspace.initializer.claw",
}


def default_runtime(session_root: str | Path = ".runtime/sagents") -> RuntimeConfig:
    root = Path(session_root).expanduser().resolve()
    paths = {
        "skill.management": {"roots": [str(root / "skills")]},
        "skill.provider": {"roots": [str(root / "skills")]},
        "session.store": {"root": str(root)},
        "memory.provider": {"root": str(root / "memory")},
        "session-memory.provider": {"root": str(root / "session-memory")},
        "observability.provider": {
            "log_stdout": False,
            "diagnostics_root": str(root / "sessions"),
            "log_root": str(root / "logs"),
        },
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


def effective_runtime(runtime: RuntimeConfig) -> RuntimeConfig:
    """Freeze implicit Agent choices without changing the selected preset."""
    implicit = {
        "context.summary-store": "sage.context.summary-store.session-derived",
        "context.summarizer": "sage.context.summarizer.model",
        "context.reducer": "sage.context.reducer.persistent-summary",
        "skill.loading": "sage.skill.loading.lazy",
        "agent.continuation-policy": "sage.agent.continuation.deterministic",
        "memory.recall-query": "sage.memory.recall-query.direct",
        "tool.selection-policy": "sage.tool-selection.llm",
        "tool.result-processor": "sage.tool.result-processor.file",
        "agent.tool-policy": "sage.agent.tool-policy.default",
    }
    choices = {**{key: CapabilitySelection(plugin=plugin) for key, plugin in implicit.items()}, **runtime.capabilities}
    from sagents.v2.runtime.extensions.contracts import ExtensionScope
    run_plugins = {"sage.context.summarizer.model", "sage.context.reducer.persistent-summary",
                   "sage.agent.continuation.llm-judge", "sage.memory.recall-query.llm"}
    for capability, choice in tuple(choices.items()):
        if isinstance(choice, CapabilitySelection) and choice.scope is None and choice.plugin in run_plugins:
            choices[capability] = choice.model_copy(update={"scope": ExtensionScope.RUN})
    return RuntimeConfig.model_validate(runtime.model_copy(update={"capabilities": choices}).model_dump(mode="python"))
