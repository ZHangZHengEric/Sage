"""Tool plugin that exposes decorator-backed Skill domain operations."""

from __future__ import annotations

from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionDependency,
    ExtensionScope,
)
from sagents.v2.skill.provider import SkillLoader
from sagents.v2.tool.plugins.skill.operations import SkillEditTool, SkillLoadTool
from sagents.v2.tool.decorated import DecoratedToolProvider


class SkillToolPlugin:
    """Load Skill Tool methods without duplicating their schemas or behavior."""

    plugin_id = "sage.tool.skill"
    name = "Skill Tool provider"
    description = "Decorator-backed Tool operations owned by the Skill module."
    descriptor = ExtensionDescriptor(
        plugin_id=plugin_id,
        version="2.0.0",
        name=name,
        description=description,
        provides=(
            CapabilityOffer(capability="tool.catalog", api_version="2", name="skill"),
            CapabilityOffer(capability="tool.executor", api_version="2", name="skill"),
        ),
        supported_scopes=frozenset({ExtensionScope.AGENT, ExtensionScope.RUN}),
        dependencies=(ExtensionDependency(capability="skill.loader"),),
        config_schema={
            "type": "object",
            "properties": {"language": {"type": "string"}, "allow_editing": {"type": "boolean"}},
            "additionalProperties": False,
        },
        capabilities={"decorated_tools": True},
        built_in=True,
    )

    def __init__(self, loader: SkillLoader, *, language: str | None = None, allow_editing: bool = False) -> None:
        owners = [SkillLoadTool(loader, language=language)]
        if allow_editing:
            if not callable(getattr(loader.workspace, "begin_edit", None)):
                raise ValueError("Selected Skill workspace does not support editing")
            owners.append(SkillEditTool(loader))
        provider = DecoratedToolProvider(*owners)
        self.catalog = provider
        self.executor = provider
        self.definitions = provider.definitions
