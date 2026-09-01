"""Lazy Skill discovery, materialization, and Run-scoped activation."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable

from sagents.v2.skill.contracts import (
    LoadedSkill,
    SkillActivationRepository,
    SkillCatalog,
    SkillDescriptor,
    SkillSource,
    SkillWorkspace,
)
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)


class FilteredSkillCatalog:
    """Run-scoped allowlist. Metadata access does not fetch or materialize files."""

    def __init__(self, inner: SkillCatalog, allowed: Iterable[str]) -> None:
        self.inner = inner
        self.allowed = frozenset(allowed)

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        values = await self.inner.list_skills(run_id=run_id)
        return tuple(value for value in values if value.name in self.allowed)

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
        if name not in self.allowed:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="skill.not_enabled",
                    category=ErrorCategory.POLICY_DENIED,
                    message=f"skill {name!r} is outside the run policy ceiling",
                    safe_to_resume=True,
                )
            )
        return await self.inner.get_skill(name, run_id=run_id)


class InvocationGrantSkillCatalog:
    """Intersect the Agent ceiling with the durable per-Run Skill grant."""

    def __init__(
        self,
        inner: SkillCatalog,
        command_reader: Callable[[str], Awaitable[object]],
    ) -> None:
        self.inner = inner
        self.command_reader = command_reader

    async def _allowed(self, run_id: str) -> frozenset[str] | None:
        command = await self.command_reader(run_id)
        configured = getattr(
            getattr(command, "config", None), "enabled_skills", None
        )
        return None if configured is None else frozenset(configured)

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        values = await self.inner.list_skills(run_id=run_id)
        allowed = await self._allowed(run_id)
        if allowed is None:
            return values
        return tuple(value for value in values if value.name in allowed)

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
        allowed = await self._allowed(run_id)
        if allowed is not None and name not in allowed:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="skill.not_enabled",
                    category=ErrorCategory.POLICY_DENIED,
                    message=f"skill {name!r} is outside this run's resolved grant",
                    safe_to_resume=True,
                )
            )
        return await self.inner.get_skill(name, run_id=run_id)


class SkillLoader:
    """Load exactly one selected Skill into a workspace and activation ledger.

    Listing metadata never copies Skill files. Repeated loads are idempotent by
    descriptor/content hash, and conflicting user workspace content is not
    overwritten.
    """

    def __init__(
        self,
        *,
        catalog: SkillCatalog,
        source: SkillSource,
        workspace: SkillWorkspace,
        activations: SkillActivationRepository,
        workspace_root: str = "/workspace",
        max_active_tokens: int = 18_000,
        token_estimator: Callable[[str], int] | None = None,
    ) -> None:
        self.catalog = catalog
        self.source = source
        self.workspace = workspace
        self.activations = activations
        self.workspace_root = workspace_root.rstrip("/") or "/"
        self.max_active_tokens = max_active_tokens
        self.token_estimator = token_estimator or self._default_token_estimate
        self._locks_guard = asyncio.Lock()
        self._load_locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def load(self, name: str, *, run_id: str) -> LoadedSkill:
        lock = await self._load_lock(run_id, name)
        async with lock:
            return await self._load_once(name, run_id=run_id)

    async def _load_once(self, name: str, *, run_id: str) -> LoadedSkill:
        descriptor = await self.catalog.get_skill(name, run_id=run_id)
        existing = {
            value.descriptor.name: value
            for value in await self.activations.list_loaded(run_id=run_id)
        }.get(name)
        # A resumed run with a durable activation record does not fetch or copy
        # the bundle again. The workspace provider owns durability/reattachment.
        if existing is not None:
            return existing

        # This is the first operation that is allowed to read the Level-2 bundle.
        bundle = await self.source.fetch(name, run_id=run_id)
        if bundle.descriptor.name != descriptor.name:
            raise self._error(
                "skill.identity_mismatch", "skill source identity changed"
            )
        destination = f"{self.workspace_root}/skills/{name}"
        workspace_path = await self.workspace.materialize(
            bundle, run_id=run_id, destination=destination
        )
        try:
            instructions = bundle.files["SKILL.md"].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise self._error("skill.invalid_utf8", "SKILL.md must be UTF-8") from exc
        loaded = LoadedSkill(
            run_id=run_id,
            descriptor=descriptor,
            workspace_path=workspace_path,
            content_hash=bundle.content_hash,
            instructions=instructions,
            file_list=tuple(sorted(bundle.files)),
            loaded_at=utc_now(),
        )
        await self.activations.put_loaded(loaded)
        await self._enforce_active_budget(run_id)
        return loaded

    async def loaded(self, *, run_id: str) -> tuple[LoadedSkill, ...]:
        return await self.activations.list_loaded(run_id=run_id)

    async def _load_lock(self, run_id: str, name: str) -> asyncio.Lock:
        # Loading is concurrent across Runs but serialized inside one Agent
        # Workspace so activation order and token-budget eviction are stable.
        key = (run_id, "__skill_activation__")
        async with self._locks_guard:
            return self._load_locks.setdefault(key, asyncio.Lock())

    async def _enforce_active_budget(self, run_id: str) -> None:
        values = list(await self.activations.list_loaded(run_id=run_id))
        total = sum(
            self.token_estimator(self._context_content(value)) for value in values
        )
        while total > self.max_active_tokens and len(values) > 1:
            removed = values.pop(0)
            total -= self.token_estimator(self._context_content(removed))
        await self.activations.replace_loaded(run_id=run_id, values=tuple(values))

    @staticmethod
    def _context_content(value: LoadedSkill) -> str:
        return (
            f"## Skill: {value.descriptor.name}\n"
            f"Workspace: {value.workspace_path}\n"
            f"Files:\n" + "\n".join(value.file_list) + "\n\n" + value.instructions
        )

    @staticmethod
    def _default_token_estimate(value: str) -> int:
        return max(1, (len(value.encode("utf-8")) + 3) // 4)

    @staticmethod
    def _error(code: str, message: str) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message=message,
                safe_to_resume=True,
            )
        )
