"""Translate desktop settings into one reproducible Agent component plan.

This value owns configuration precedence and cache identities only. It does not
read mutable settings, create models, acquire sandboxes or own plugin resources.
The caller supplies its persisted settings snapshot on recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from pydantic import SecretStr

from app.v2.desktop.backend.catalog import (
    DesktopAgentRecord,
    DesktopModelProviderRecord,
)
from app.v2.desktop.backend.schemas import DesktopV2Settings
from app.v2.desktop.backend.package import (
    DESKTOP_COMPONENT_DEFAULTS as _DESKTOP_COMPONENT_DEFAULTS,
    DESKTOP_COMPONENT_CONFIG_LOCKS,
    stable_component_id as _stable_component_id,
    desktop_v2_manifest,
)
from app.v2.desktop.backend.runtime_config import _tool_selection_component_config
from sagents.v2.model import ModelProvider
from sagents.v2.package.manifest.root import SageManifest


@dataclass(frozen=True)
class DesktopComponentPlan:
    manifest: SageManifest
    cache_identities: dict[str, Any]
    continuation_plugin_id: str
    memory_query_plugin_id: str
    tool_selection_config: dict[str, Any]
    language: str

    @classmethod
    def resolve(
        cls,
        *,
        settings: DesktopV2Settings,
        agent: DesktopAgentRecord,
        provider: DesktopModelProviderRecord,
        judge_provider: DesktopModelProviderRecord,
        runtime_root: Path,
        summary_store_plugin_id: str,
    ) -> DesktopComponentPlan:
        estimator_id = settings.component_selections.get(
            "context.token-estimator",
            _DESKTOP_COMPONENT_DEFAULTS["context.token-estimator"],
        )
        reducer_id = settings.component_selections.get(
            "context.reducer", _DESKTOP_COMPONENT_DEFAULTS["context.reducer"]
        )
        estimator_id = _stable_component_id("context.token-estimator", estimator_id)
        reducer_id = _stable_component_id("context.reducer", reducer_id)
        memory_query_plugin_id = _stable_component_id(
            "memory.recall-query",
            settings.component_selections.get(
                "memory.recall-query",
                _DESKTOP_COMPONENT_DEFAULTS["memory.recall-query"],
            ),
        )
        summarizer_plugin_id = _stable_component_id(
            "context.summarizer",
            settings.component_selections.get(
                "context.summarizer",
                _DESKTOP_COMPONENT_DEFAULTS["context.summarizer"],
            ),
        )
        continuation_plugin_id = _stable_component_id(
            "agent.continuation-policy",
            settings.component_selections.get(
                "agent.continuation-policy",
                _DESKTOP_COMPONENT_DEFAULTS["agent.continuation-policy"],
            ),
        )
        raw_tool_selection = agent.config.get("toolSelection")
        legacy_tool_selection_config = (
            dict(raw_tool_selection) if isinstance(raw_tool_selection, dict) else {}
        )
        legacy_plugin_id = str(
            legacy_tool_selection_config.pop(
                "plugin", _DESKTOP_COMPONENT_DEFAULTS["tool.selection-policy"]
            )
        )
        tool_selection_plugin_id = _stable_component_id(
            "tool.selection-policy",
            settings.component_selections.get(
                "tool.selection-policy", legacy_plugin_id
            ),
        )
        configured_tool_selection = settings.component_configs.get(
            "tool.selection-policy"
        )
        tool_selection_config = _tool_selection_component_config(
            tool_selection_plugin_id,
            configured_tool_selection
            if configured_tool_selection is not None
            else legacy_tool_selection_config,
        )
        run_manifest = desktop_v2_manifest(
            session_root=runtime_root,
            component_selections={
                **settings.component_selections,
                "context.token-estimator": estimator_id,
                "context.reducer": reducer_id,
                "context.summarizer": summarizer_plugin_id,
                "agent.continuation-policy": continuation_plugin_id,
                "tool.selection-policy": tool_selection_plugin_id,
                "memory.recall-query": memory_query_plugin_id,
            },
            component_configs=settings.component_configs,
            language=settings.language,
        )
        run_cache_identities = {
            "context.summarizer": {
                "plugin": summarizer_plugin_id,
                "provider": provider.id,
                "model": provider.model,
                "base_url": provider.base_url,
                "credential": SecretStr(provider.api_key or ""),
                "model_binding": "primary",
            },
            "memory.recall-query": {
                "plugin": memory_query_plugin_id,
                "language": settings.language,
                "provider": judge_provider.id,
                "model": judge_provider.model,
                "base_url": judge_provider.base_url,
                "credential": SecretStr(judge_provider.api_key or ""),
            },
            "context.reducer": {
                "plugin": reducer_id,
                "estimator": estimator_id,
                "summarizer": summarizer_plugin_id,
                "summary_store": summary_store_plugin_id,
                "provider": provider.id,
                "model": provider.model,
            },
            "tool.selection-policy": {
                "plugin": tool_selection_plugin_id,
                **tool_selection_config,
            },
        }
        return cls(
            manifest=run_manifest,
            cache_identities=run_cache_identities,
            continuation_plugin_id=continuation_plugin_id,
            memory_query_plugin_id=memory_query_plugin_id,
            tool_selection_config=tool_selection_config,
            language=settings.language,
        )

    def continuation_config(self, model: ModelProvider) -> dict[str, Any]:
        return {
            "agent.continuation-policy": {
                "model": model,
                **DESKTOP_COMPONENT_CONFIG_LOCKS["agent.continuation-policy"],
            }
        }

    def locked_configs(
        self,
        *,
        primary: ModelProvider,
        judge: ModelProvider,
        memory_query: ModelProvider,
    ) -> dict[str, Any]:
        return {
            "context.summarizer": {
                "model": primary,
                **DESKTOP_COMPONENT_CONFIG_LOCKS["context.summarizer"],
            },
            "memory.recall-query": (
                {"model": memory_query, "language": self.language}
                if self.memory_query_plugin_id == "sage.memory.recall-query.llm"
                else {}
            ),
            "tool.selection-policy": self.tool_selection_config,
            **self.continuation_config(judge),
            "workspace.initializer": {"language": self.language},
        }
