"""Lazy Skill loading with bounded restoration from Session history."""

from __future__ import annotations

import asyncio
from weakref import WeakValueDictionary
from xml.sax.saxutils import escape
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
        configured = getattr(getattr(command, "config", None), "enabled_skills", None)
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
        max_active_tokens: int = 6_000,
        token_estimator: Callable[[str], int] | None = None,
        inherited_skills: Callable[[str], Awaitable[tuple[str, ...]]] | None = None,
    ) -> None:
        if max_active_tokens < 1:
            raise ValueError("max_active_tokens must be positive")
        self.inherited_skills = inherited_skills
        self._initialized_runs: set[str] = set()
        self.catalog = catalog
        self.source = source
        self.workspace = workspace
        self.activations = activations
        self.workspace_root = workspace_root.rstrip("/") or "/"
        self.max_active_tokens = max_active_tokens
        self.token_estimator = token_estimator or self._default_token_estimate
        self._locks_guard = asyncio.Lock()
        self._load_locks: WeakValueDictionary = WeakValueDictionary()

    async def load(self, name: str, *, run_id: str) -> LoadedSkill:
        lock = await self._load_lock(run_id, name)
        async with lock:
            return await self._load_once(name, run_id=run_id)

    async def _load_once(
        self, name: str, *, run_id: str, budget_tokens: int | None = None
    ) -> LoadedSkill:
        limit = self.max_active_tokens if budget_tokens is None else budget_tokens
        descriptor = await self.catalog.get_skill(name, run_id=run_id)
        existing = {
            value.descriptor.name: value
            for value in await self.activations.list_loaded(run_id=run_id)
        }.get(name)
        # A resumed run with a durable activation record does not fetch or copy
        # the bundle again. The workspace provider owns durability/reattachment.
        if existing is not None:
            values = await self.activations.list_loaded(run_id=run_id)
            await self.activations.replace_loaded(
                run_id=run_id,
                values=(*(v for v in values if v.descriptor.name != name), existing),
            )
            return existing

        # This is the first operation that is allowed to read the Level-2 bundle.
        bundle = await self.source.fetch(name, run_id=run_id)
        if bundle.descriptor.name != descriptor.name:
            raise self._error(
                "skill.identity_mismatch", "skill source identity changed"
            )
        destination = f"{self.workspace_root}/skills/{name}"
        try:
            instructions = bundle.files["SKILL.md"].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise self._error("skill.invalid_utf8", "SKILL.md must be UTF-8") from exc
        loaded = LoadedSkill(
            run_id=run_id,
            descriptor=descriptor,
            workspace_path=destination,
            content_hash=bundle.content_hash,
            instructions=instructions,
            file_list=tuple(sorted(bundle.files)),
            loaded_at=utc_now(),
        )
        if self.token_estimator(self._context_content(loaded)) > limit:
            raise self._error(
                "skill.active_budget_exceeded",
                "skill instructions exceed the active context budget",
            )
        workspace_path = await self.workspace.materialize(
            bundle, run_id=run_id, destination=destination
        )
        loaded = loaded.model_copy(update={"workspace_path": workspace_path})
        if self.token_estimator(self._context_content(loaded)) > limit:
            raise self._error(
                "skill.active_budget_exceeded",
                "materialized skill context exceeds the active budget",
            )
        await self.activations.put_loaded(loaded)
        await self._enforce_active_budget(run_id)
        return loaded

    async def loaded(self, *, run_id: str) -> tuple[LoadedSkill, ...]:
        lock = await self._load_lock(run_id, "")
        async with lock:
            values = await self.activations.list_loaded(run_id=run_id)
            if (
                run_id not in self._initialized_runs
                and self.inherited_skills is not None
            ):
                if not values:
                    allowed = {
                        v.name for v in await self.catalog.list_skills(run_id=run_id)
                    }
                    remaining = self.max_active_tokens
                    inherited = []
                    for name in dict.fromkeys(await self.inherited_skills(run_id)):
                        if name not in allowed:
                            continue
                        try:
                            value = await self._load_once(
                                name, run_id=run_id, budget_tokens=remaining
                            )
                        except SageV2Error as exc:
                            if exc.info.code == "skill.active_budget_exceeded":
                                break
                            raise
                        inherited.append(value)
                        remaining -= self.token_estimator(self._context_content(value))
                    # Repositories retain chronological order for later eviction.
                    await self.activations.replace_loaded(
                        run_id=run_id, values=tuple(reversed(inherited))
                    )
                self._initialized_runs.add(run_id)
                values = await self.activations.list_loaded(run_id=run_id)
            # Recheck the current grant even for durable activations on resume.
            allowed = {v.name for v in await self.catalog.list_skills(run_id=run_id)}
            return tuple(v for v in values if v.descriptor.name in allowed)

    async def _load_lock(self, run_id: str, name: str) -> asyncio.Lock:
        # Loading is concurrent across Runs but serialized inside one Agent
        # Workspace so activation order and token-budget eviction are stable.
        key = (run_id, "__skill_activation__")
        async with self._locks_guard:
            return self._load_locks.setdefault(key, asyncio.Lock())

    async def _enforce_active_budget(self, run_id: str) -> None:
        values = list(await self.activations.list_loaded(run_id=run_id))
        costs = [self.token_estimator(self._context_content(value)) for value in values]
        total = sum(costs)
        start = 0
        while total > self.max_active_tokens and start < len(values):
            total -= costs[start]
            start += 1
        await self.activations.replace_loaded(
            run_id=run_id, values=tuple(values[start:])
        )

    @staticmethod
    def _context_content(value: LoadedSkill) -> str:
        # Budget exactly the XML-escaped text that ActiveSkillsContextProvider sends.
        return (
            "<active_skill>\n"
            f"<skill_name>{escape(value.descriptor.name)}</skill_name>\n"
            f"<workspace>{escape(value.workspace_path)}</workspace>\n"
            f"<skill_content>{escape(value.instructions)}</skill_content>\n"
            "</active_skill>"
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
