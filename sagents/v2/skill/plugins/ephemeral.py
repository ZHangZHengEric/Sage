"""SAgents V2 module for skill/plugins/ephemeral.py."""

from __future__ import annotations

import asyncio

from sagents.v2.skill.contracts import (
    LoadedSkill,
    SkillBundle,
    SkillDescriptor,
)
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)


class InMemorySkillProvider:
    """Deterministic catalog/source. ``fetches`` proves lazy Level-2 access."""

    def __init__(self, bundles: tuple[SkillBundle, ...]) -> None:
        self._bundles = {value.descriptor.name: value for value in bundles}
        self.fetches: list[tuple[str, str]] = []

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        return tuple(self._bundles[name].descriptor for name in sorted(self._bundles))

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
        try:
            return self._bundles[name].descriptor
        except KeyError as exc:
            raise _not_found(name) from exc

    async def fetch(self, name: str, *, run_id: str) -> SkillBundle:
        try:
            value = self._bundles[name]
        except KeyError as exc:
            raise _not_found(name) from exc
        self.fetches.append((run_id, name))
        return value


class InMemorySkillWorkspace:
    """Atomic, no-overwrite workspace used by tests and embedded runtimes."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.files: dict[str, dict[str, bytes]] = {}
        self.hashes: dict[str, str] = {}
        self.materializations: list[tuple[str, str, str]] = []

    async def materialize(
        self, bundle: SkillBundle, *, run_id: str, destination: str
    ) -> str:
        async with self._lock:
            current_hash = self.hashes.get(destination)
            if current_hash is not None:
                if current_hash != bundle.content_hash:
                    raise SageV2Error(
                        RuntimeErrorInfo(
                            code="skill.workspace_conflict",
                            category=ErrorCategory.CONFLICT,
                            message=(
                                f"workspace skill {destination!r} already exists with "
                                "different content; it was not overwritten"
                            ),
                            safe_to_resume=True,
                        )
                    )
                return destination
            self.files[destination] = dict(bundle.files)
            self.hashes[destination] = bundle.content_hash
            self.materializations.append((run_id, bundle.descriptor.name, destination))
            return destination


class InMemorySkillActivationRepository:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._values: dict[str, dict[str, LoadedSkill]] = {}

    async def list_loaded(self, *, run_id: str) -> tuple[LoadedSkill, ...]:
        async with self._lock:
            values = self._values.get(run_id, {})
            return tuple(values[name] for name in values)

    async def put_loaded(self, value: LoadedSkill) -> None:
        async with self._lock:
            self._values.setdefault(value.run_id, {})[value.descriptor.name] = value

    async def replace_loaded(
        self, *, run_id: str, values: tuple[LoadedSkill, ...]
    ) -> None:
        async with self._lock:
            self._values[run_id] = {value.descriptor.name: value for value in values}


def _not_found(name: str) -> SageV2Error:
    return SageV2Error(
        RuntimeErrorInfo(
            code="skill.not_found",
            category=ErrorCategory.VALIDATION,
            message=f"skill {name!r} is not registered",
            safe_to_resume=True,
        )
    )
