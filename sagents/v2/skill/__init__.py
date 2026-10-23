"""Skill contracts and lazily loaded implementations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.tool.plugins.skill.operations import SkillLoadTool as SkillLoadTool
    from sagents.v2.skill.plugins.repository import SqliteSkillRepository as SqliteSkillRepository
    from sagents.v2.skill.plugins.repository import MemorySkillRepository as MemorySkillRepository
    from sagents.v2.skill.plugins.workspace import AutoSyncSkillWorkspace as AutoSyncSkillWorkspace
    from sagents.v2.skill.plugins.workspace import FixedCopySkillWorkspace as FixedCopySkillWorkspace
    from sagents.v2.skill.plugins.workspace import ReadonlyMountSkillWorkspace as ReadonlyMountSkillWorkspace
    from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider as FilesystemSkillProvider
    from sagents.v2.skill.plugins.ephemeral import InMemorySkillActivationRepository as InMemorySkillActivationRepository
    from sagents.v2.skill.plugins.ephemeral import InMemorySkillProvider as InMemorySkillProvider
    from sagents.v2.skill.plugins.ephemeral import InMemorySkillWorkspace as InMemorySkillWorkspace
    from sagents.v2.skill.plugins.session import SessionDerivedSkillActivationRepository as SessionDerivedSkillActivationRepository


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
    SkillProvider,
    CurrentSkillSource,
    SkillWorkspace,
    SkillManagement,
    EditableSkillWorkspace,
    RestorableSkillWorkspace,
    SkillReadonlyMountProvider,
)
from sagents.v2.skill.provider import (
    FilteredSkillCatalog,
    InvocationGrantSkillCatalog,
    SkillLoader,
)
from sagents.v2.contracts.runtime_skills import RuntimeSkillAttachment, RuntimeSkillAuthorization

_LAZY_EXPORTS = {
    "SkillLoadTool": ("sagents.v2.tool.plugins.skill.operations", "SkillLoadTool"),
    "SqliteSkillRepository": ("sagents.v2.skill.plugins.repository", "SqliteSkillRepository"),
    "MemorySkillRepository": ("sagents.v2.skill.plugins.repository", "MemorySkillRepository"),
    "AutoSyncSkillWorkspace": ("sagents.v2.skill.plugins.workspace", "AutoSyncSkillWorkspace"),
    "FixedCopySkillWorkspace": ("sagents.v2.skill.plugins.workspace", "FixedCopySkillWorkspace"),
    "ReadonlyMountSkillWorkspace": ("sagents.v2.skill.plugins.workspace", "ReadonlyMountSkillWorkspace"),
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
    "RuntimeSkillAttachment",
    "RuntimeSkillAuthorization",
    "SqliteSkillRepository",
    "MemorySkillRepository",
    "AutoSyncSkillWorkspace",
    "FixedCopySkillWorkspace",
    "ReadonlyMountSkillWorkspace",
    "SkillManagement",
    "EditableSkillWorkspace",
    "RestorableSkillWorkspace",
    "SkillReadonlyMountProvider",
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
    "SkillProvider",
    "CurrentSkillSource",
    "SkillWorkspace",
    "SessionDerivedSkillActivationRepository",
]


def __getattr__(name: str):
    return resolve_export(name, _LAZY_EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_LAZY_EXPORTS, globals())
