"""Configurable lazy Skill loading, independent of catalog and tool providers."""

from pydantic import Field

from sagents.v2.contracts.common import StrictModel
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionScope,
)
from sagents.v2.skill.provider import SkillLoader


class SkillLoadingConfig(StrictModel):
    max_active_characters: int = Field(default=24_000, ge=1, strict=True)


class SkillLoadingPlugin:
    """Load Skill material on demand, bounded by an active-character storage limit."""

    plugin_id = "sage.skill.loading.lazy"
    name = "Lazy Skill loading"
    description = "Loads Skill material only when it is asked for, within a character storage limit."
    descriptor = ExtensionDescriptor(
        plugin_id=plugin_id,
        version="2.0.0",
        name=name,
        description=description,
        provides=(CapabilityOffer(capability="skill.loading", api_version="2"),),
        supported_scopes=frozenset({ExtensionScope.AGENT, ExtensionScope.RUN}),
        config_schema=SkillLoadingConfig.model_json_schema(),
        built_in=True,
    )

    def __init__(self, *, max_active_characters: int = 24_000) -> None:
        self.config = SkillLoadingConfig(max_active_characters=max_active_characters)

    def create_loader(self, **ports) -> SkillLoader:
        return SkillLoader(
            **ports, max_active_characters=self.config.max_active_characters
        )
