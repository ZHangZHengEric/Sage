"""SAgents V2 module for skill/contracts.py."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator

from sagents.v2.contracts.common import Identifier, SkillName, StrictModel


class SkillDescriptor(StrictModel):
    """Level-1 metadata; discovering this object must never copy skill files."""

    name: SkillName
    description: str
    source_id: Identifier
    version: str | None = None
    metadata: dict = Field(default_factory=dict)


class SkillBundle(StrictModel):
    """Immutable Level-2 payload fetched only by an explicit load operation."""

    descriptor: SkillDescriptor
    files: dict[str, bytes]
    content_hash: str

    @field_validator("files")
    @classmethod
    def validate_paths(cls, files: dict[str, bytes]) -> dict[str, bytes]:
        if "SKILL.md" not in files:
            raise ValueError("skill bundle requires SKILL.md")
        for path in files:
            normalized = path.replace("\\", "/")
            if (
                not normalized
                or normalized.startswith("/")
                or normalized != path
                or any(part in {"", ".", ".."} for part in normalized.split("/"))
            ):
                raise ValueError(f"unsafe skill bundle path: {path!r}")
        return files


class LoadedSkill(StrictModel):
    run_id: Identifier
    descriptor: SkillDescriptor
    workspace_path: str
    content_hash: str
    instructions: str
    file_list: tuple[str, ...]
    loaded_at: datetime


class SkillRunState(StrictModel):
    """Run control state, independent from the rebuildable activation cache."""

    version: Literal[1] = 1
    preloads: tuple[str, ...] = ()
    processed_preloads: tuple[str, ...] = ()
    preloads_complete: bool = False
    history_initialized: bool = False
    requested_names: tuple[str, ...] = ()
    active: tuple[LoadedSkill, ...] = ()


class SkillCatalog(Protocol):
    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]: ...
    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor: ...


class SkillSource(Protocol):
    async def fetch(self, name: str, *, run_id: str) -> SkillBundle: ...


class CurrentSkillSource(SkillSource, Protocol):
    """Current manager contents for an already admitted Skill name."""

    async def fetch_latest(self, name: str, *, run_id: str) -> SkillBundle: ...


class SkillManagement(SkillCatalog, SkillSource, Protocol):
    """Host-owned publishing port. Never implicitly granted as an Agent tool."""

    async def publish(
        self, bundle: SkillBundle, *, expected_version: str | None = None
    ) -> SkillDescriptor: ...

    async def list_versions(self, name: str) -> tuple[SkillDescriptor, ...]: ...


class SkillWorkspace(Protocol):
    async def materialize(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> str: ...


class EditableSkillWorkspace(SkillWorkspace, Protocol):
    """Explicit editing preparation; synchronization policy owns edit retention."""

    async def begin_edit(self, bundle: SkillBundle, *, run_id: str, destination: str) -> str: ...

    async def resolve_bundle(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> SkillBundle: ...


class RestorableSkillWorkspace(SkillWorkspace, Protocol):
    async def reattach(
        self, loaded: LoadedSkill, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> LoadedSkill: ...


class SkillReadonlyMountProvider(Protocol):
    """Optional sandbox.skill_mounts port for real backend-enforced mounts.

    The backend verifies the signed intent and both hashes against the supplied
    bundle, enforces read-only access for files AND processes, and manages mount
    lifetimes with the Run sandbox. A normal directory or symlink is insufficient.
    """

    async def mount_readonly(
        self, bundle: SkillBundle, *, destination: str, run_id: str, intent: Any, grant: Any
    ) -> str: ...


class SkillActivationRepository(Protocol):
    async def list_loaded(self, *, run_id: str) -> tuple[LoadedSkill, ...]: ...
    async def put_loaded(self, value: LoadedSkill) -> None: ...
    async def replace_loaded(
        self, *, run_id: str, values: tuple[LoadedSkill, ...]
    ) -> None: ...
