"""SAgents V2 module for skill/contracts.py."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.skill_payload import (
    SkillBundle as SkillBundle,
    SkillDescriptor as SkillDescriptor,
    SkillReference as SkillReference,
)


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
    discovered_references: tuple[SkillReference, ...] = ()
    selected_references: tuple[SkillReference, ...] = ()


class SkillCatalog(Protocol):
    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]: ...
    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor: ...


class SkillSource(Protocol):
    async def fetch(self, name: str, *, run_id: str) -> SkillBundle: ...


class SkillProvider(SkillCatalog, SkillSource, Protocol):
    """One selected source owns discovery and bundle retrieval."""


class SkillSearchProvider(Protocol):
    """Optional, metadata-only search within the caller's authorized names."""

    async def search_skills(
        self, query: str, *, run_id: str, allowed_names: frozenset[str], limit: int
    ) -> tuple[SkillDescriptor, ...]: ...


@runtime_checkable
class RunSkillProvider(SkillProvider, Protocol):
    """A trusted provider that derives discovery and read access from the Run.

    Return metadata with references from search and authorize every exact-version
    fetch, including recovery. The SDK checks that a new selection came from the
    same Run's search and that the returned bundle matches the reference.
    Apply a supplied name grant before ranking and limiting the results.
    """

    async def search_skills(
        self, query: str, *, run_id: str, limit: int, allowed_names: frozenset[str] | None = None
    ) -> tuple[SkillDescriptor, ...]: ...

    async def fetch_reference(self, reference: SkillReference, *, run_id: str) -> SkillBundle: ...


class CurrentSkillSource(SkillSource, Protocol):
    """Current manager contents for an already admitted Skill name."""

    async def fetch_latest(self, name: str, *, run_id: str) -> SkillBundle: ...


class VersionedSkillSource(SkillSource, Protocol):
    """Retrieve an admitted name at the exact version recorded in a checkpoint."""

    async def fetch_for_restore(self, name: str, *, run_id: str, version: str) -> SkillBundle: ...


class SkillManagement(SkillProvider, Protocol):
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

    async def begin_edit(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> str: ...

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
        self,
        bundle: SkillBundle,
        *,
        destination: str,
        run_id: str,
        intent: Any,
        grant: Any,
    ) -> str: ...


class SkillActivationRepository(Protocol):
    async def list_loaded(self, *, run_id: str) -> tuple[LoadedSkill, ...]: ...
    async def put_loaded(self, value: LoadedSkill) -> None: ...
    async def replace_loaded(
        self, *, run_id: str, values: tuple[LoadedSkill, ...]
    ) -> None: ...
