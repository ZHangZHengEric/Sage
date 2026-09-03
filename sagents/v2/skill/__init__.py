"""Skill contracts and lazily loaded implementations."""

from sagents.v2._lazy import exported_names, resolve_export

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
from sagents.v2.skill.provider import (
    FilteredSkillCatalog,
    InvocationGrantSkillCatalog,
    SkillLoader,
)
from sagents.v2.skill.tool import SkillLoadTool

_LAZY_EXPORTS = {
    "FilesystemSkillProvider": (
        "sagents.v2.skill.plugins.filesystem",
        "FilesystemSkillProvider",
    ),
    "InMemorySkillActivationRepository": (
        "sagents.v2.skill.plugins.ephemeral",
        "InMemorySkillActivationRepository",
    ),
    "InMemorySkillProvider": (
        "sagents.v2.skill.plugins.ephemeral",
        "InMemorySkillProvider",
    ),
    "InMemorySkillWorkspace": (
        "sagents.v2.skill.plugins.ephemeral",
        "InMemorySkillWorkspace",
    ),
    "SessionDerivedSkillActivationRepository": (
        "sagents.v2.skill.plugins.session",
        "SessionDerivedSkillActivationRepository",
    ),
}

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


def __getattr__(name: str):
    return resolve_export(name, _LAZY_EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_LAZY_EXPORTS, globals())
