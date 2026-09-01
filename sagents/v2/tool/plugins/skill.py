"""Tool plugin that exposes decorator-backed Skill domain operations."""

from __future__ import annotations

from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionScope,
)
from sagents.v2.skill.provider import SkillLoader
from sagents.v2.skill.tool import SkillLoadTool
from sagents.v2.tool.decorated import DecoratedToolProvider


class SkillToolPlugin:
    """Load Skill Tool methods without duplicating their schemas or behavior."""

    plugin_id = "sage.tool.skill"
    descriptor = ExtensionDescriptor(
        plugin_id=plugin_id,
        version="2.0.0",
        name="Skill Tool provider",
        description="Decorator-backed Tool operations owned by the Skill module.",
        provides=(
            CapabilityOffer(capability="tool.catalog", api_version="2", name="skill"),
            CapabilityOffer(capability="tool.executor", api_version="2", name="skill"),
        ),
        supported_scopes=frozenset({ExtensionScope.AGENT, ExtensionScope.RUN}),
        config_schema={
            "type": "object",
            "properties": {"loader": {}, "language": {"type": "string"}},
            "required": ["loader"],
        },
        capabilities={"decorated_tools": True},
        built_in=True,
    )

    def __init__(self, loader: SkillLoader, *, language: str | None = None) -> None:
        provider = DecoratedToolProvider(SkillLoadTool(loader, language=language))
        self.catalog = provider
        self.executor = provider
        self.definitions = provider.definitions
