"""Extension lifecycle wrapper for real V2 official Tool implementations."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionScope,
    ExtensionScopeContext,
)
from sagents.v2.tool.decorated import DecoratedToolProvider
from sagents.v2.tool.decorators import decorated_tool_definition
from sagents.v2.tool.contracts import ToolDefinition
from sagents.v2.tool.official.filesystem import CodeSearchTools, FileSystemTools
from sagents.v2.tool.official.interaction import InteractionTools
from sagents.v2.tool.official.media import MediaTools
from sagents.v2.tool.official.memory import MemoryTools
from sagents.v2.tool.official.planning import PlanningTools
from sagents.v2.tool.official.quality import QualityTools
from sagents.v2.tool.official.runtime import OfficialToolRuntime
from sagents.v2.tool.official.shell import ShellTools
from sagents.v2.tool.official.web import WebTools


_OFFICIAL_TOOL_CLASSES = (
    FileSystemTools,
    CodeSearchTools,
    ShellTools,
    PlanningTools,
    MemoryTools,
    WebTools,
    MediaTools,
    QualityTools,
    InteractionTools,
)

_OFFICIAL_TOOL_CATEGORIES = {
    FileSystemTools: "files",
    CodeSearchTools: "code_search",
    ShellTools: "shell",
    PlanningTools: "planning",
    MemoryTools: "memory",
    WebTools: "web",
    MediaTools: "image",
    QualityTools: "code_quality",
    InteractionTools: "interaction",
}


def official_tool_definitions() -> tuple[ToolDefinition, ...]:
    """Return decorator metadata without constructing an execution runtime."""

    values: dict[str, ToolDefinition] = {}
    for owner in _OFFICIAL_TOOL_CLASSES:
        for _, method in inspect.getmembers(owner, callable):
            definition = decorated_tool_definition(method)
            if definition is not None:
                if definition.name in values:
                    raise ValueError(f"duplicate official Tool {definition.name!r}")
                values[definition.name] = definition
    return tuple(values[name] for name in sorted(values))


def official_tool_categories() -> dict[str, str]:
    """Return stable display categories for the official Tool catalog."""

    values: dict[str, str] = {}
    for owner in _OFFICIAL_TOOL_CLASSES:
        category = _OFFICIAL_TOOL_CATEGORIES[owner]
        for _, method in inspect.getmembers(owner, callable):
            definition = decorated_tool_definition(method)
            if definition is not None:
                values[definition.name] = category
    return values


class OfficialToolPlugin:
    plugin_id = "sage.tool.official"
    name = "Official SAgents Tool provider"
    description = "V2-native decorator-backed workspace and runtime tools."
    descriptor = ExtensionDescriptor(
        plugin_id=plugin_id,
        version="2.0.0",
        name=name,
        description=description,
        provides=(
            CapabilityOffer(
                capability="tool.catalog", api_version="2", name="official"
            ),
            CapabilityOffer(
                capability="tool.executor", api_version="2", name="official"
            ),
        ),
        supported_scopes=frozenset(
            {ExtensionScope.PROCESS, ExtensionScope.AGENT, ExtensionScope.RUN}
        ),
        config_schema={
            "type": "object",
            "properties": {
                "runtime": {},
            },
            "required": ["runtime"],
            "additionalProperties": False,
        },
        capabilities={"decorated_tools": True, "v2_native": True},
        built_in=True,
    )

    def __init__(self, context: ExtensionScopeContext) -> None:
        configured = context.config.get("runtime")
        if not isinstance(configured, OfficialToolRuntime):
            raise TypeError("sage.tool.official requires an OfficialToolRuntime")
        self.runtime = configured
        provider = DecoratedToolProvider(
            *(owner(self.runtime) for owner in _OFFICIAL_TOOL_CLASSES)
        )
        self.catalog = provider
        self.executor = provider
        self.definitions = provider.definitions

    async def start(
        self, context: ExtensionScopeContext, dependencies: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return {
            "tool.catalog:official": self.catalog,
            "tool.executor:official": self.executor,
        }

    async def stop(self, reason: Any) -> None:
        del reason
        await self.runtime.close()


__all__ = [
    "OfficialToolPlugin",
    "official_tool_categories",
    "official_tool_definitions",
]
