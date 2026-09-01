"""SAgents V2 module for skill/__init__.py."""

from sagents.v2.skill.context import (
    ActiveSkillsContextProvider,
    AvailableSkillsContextProvider,
)
from sagents.v2.skill.contracts import (
    LoadedSkill,
    SkillActivationRepository,
    SkillBundle,
    SkillCatalog,
    SkillDescriptor,
    SkillSource,
    SkillWorkspace,
)
from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider
from sagents.v2.skill.plugins.ephemeral import (
    InMemorySkillActivationRepository,
    InMemorySkillProvider,
    InMemorySkillWorkspace,
)
from sagents.v2.skill.plugins.session import SessionDerivedSkillActivationRepository
from sagents.v2.skill.provider import (
    FilteredSkillCatalog,
    InvocationGrantSkillCatalog,
    SkillLoader,
)
from sagents.v2.skill.tool import SkillLoadTool

__all__ = [
    "ActiveSkillsContextProvider",
    "AvailableSkillsContextProvider",
    "FilteredSkillCatalog",
    "InMemorySkillActivationRepository",
    "InMemorySkillProvider",
    "InMemorySkillWorkspace",
    "InvocationGrantSkillCatalog",
    "FilesystemSkillProvider",
    "LoadedSkill",
    "SkillActivationRepository",
    "SkillBundle",
    "SkillCatalog",
    "SkillDescriptor",
    "SkillLoadTool",
    "SkillLoader",
    "SkillSource",
    "SkillWorkspace",
    "SessionDerivedSkillActivationRepository",
]
