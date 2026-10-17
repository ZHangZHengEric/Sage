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
    SkillRunState,
    SkillWorkspace,
)
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
    errors_before_side_effect,
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
        max_active_characters: int = 24_000,
        inherited_skills: Callable[[str], Awaitable[tuple[str, ...]]] | None = None,
    ) -> None:
        if max_active_characters < 1:
            raise ValueError("max_active_characters must be positive")
        self.inherited_skills = inherited_skills
        self._initialized_runs: set[str] = set()
        self._requested_names: dict[str, set[str]] = {}
        self._preload_states: dict[str, SkillRunState] = {}
        self.catalog = catalog
        self.source = source
        self.workspace = workspace
        self.activations = activations
        self.workspace_root = workspace_root.rstrip("/") or "/"
        self.max_active_characters = max_active_characters
        self._locks_guard = asyncio.Lock()
        self._load_locks: WeakValueDictionary = WeakValueDictionary()

    async def snapshot_run(self, run_id: str) -> dict:
        lock = await self._load_lock(run_id, "")
        async with lock:
            state = self._preload_states.get(run_id, SkillRunState())
            return state.model_copy(update={
                "active": await self.activations.list_loaded(run_id=run_id),
                "history_initialized": run_id in self._initialized_runs,
                "requested_names": tuple(sorted(self._requested_names.get(run_id, ()))),
            }).model_dump(mode="json")

    async def restore_run(self, run_id: str, snapshot: dict) -> None:
        lock = await self._load_lock(run_id, "")
        async with lock:
            # Restore the exact activation list, including an intentionally empty one.
            # Never infer initialization from which skill bodies happen to remain.
            state = SkillRunState.model_validate(snapshot)
            if any(value.run_id != run_id for value in state.active):
                raise self._error("skill.state_invalid", "skill state belongs to another Run")
            await self.activations.replace_loaded(run_id=run_id, values=state.active)
            self._preload_states[run_id] = state
            if state.history_initialized:
                self._initialized_runs.add(run_id)
            else:
                self._initialized_runs.discard(run_id)
            self._requested_names[run_id] = set(state.requested_names)

    async def initialize_preloads(
        self, names: tuple[str, ...], *, run_id: str, on_progress=None
    ) -> None:
        async with self._locks_guard:
            key = (run_id, "__preload_initialization__")
            lock = self._load_locks.setdefault(key, asyncio.Lock())
        async with lock:
            await self._initialize_preloads_once(names, run_id=run_id, on_progress=on_progress)

    async def _initialize_preloads_once(self, names, *, run_id, on_progress):
        state = self._preload_states.get(run_id, SkillRunState(preloads=names))
        if state.preloads_complete:
            return
        if not state.preloads:
            state = state.model_copy(update={"preloads": names})
        self._preload_states[run_id] = state
        # History is older than defaults and must not restore them after eviction.
        await self.loaded(run_id=run_id)
        self._initialized_runs.add(run_id)
        for name in dict.fromkeys(state.preloads):
            if name in state.processed_preloads:
                continue
            await self.load(name, run_id=run_id)
            state = state.model_copy(update={
                "processed_preloads": (*state.processed_preloads, name),
            })
            self._preload_states[run_id] = state
            if on_progress is not None:
                await on_progress()
        self._preload_states[run_id] = state.model_copy(update={"preloads_complete": True})
        if on_progress is not None:
            await on_progress()

    async def load(self, name: str, *, run_id: str) -> LoadedSkill:
        lock = await self._load_lock(run_id, name)
        async with lock:
            return await self._load_once(name, run_id=run_id)

    async def activate_requested(self, names: tuple[str, ...], *, run_id: str) -> None:
        """Load user selectors once per Run, through the existing grant and budget.

        Do not reload budget-evicted selectors on every model step. Unknown or
        disabled historical selectors cannot grant access or fail a new Run.
        """
        if not names:
            return
        await self.loaded(run_id=run_id)
        lock = await self._load_lock(run_id, "")
        async with lock:
            processed = self._requested_names.setdefault(run_id, set())
            for name in names:
                if name in processed:
                    continue
                try:
                    await self._load_once(name, run_id=run_id)
                except SageV2Error as exc:
                    if exc.info.code not in {"skill.not_found", "skill.not_enabled"}:
                        raise
                processed.add(name)

    async def _load_once(
        self, name: str, *, run_id: str, budget_characters: int | None = None
    ) -> LoadedSkill:
        limit = (
            self.max_active_characters
            if budget_characters is None
            else budget_characters
        )
        with errors_before_side_effect("skill.lookup_failed"):
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

        with errors_before_side_effect("skill.load_preflight_failed"):
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
                raise self._error(
                    "skill.invalid_utf8", "SKILL.md must be UTF-8"
                ) from exc
            loaded = LoadedSkill(
                run_id=run_id,
                descriptor=descriptor,
                workspace_path=destination,
                content_hash=bundle.content_hash,
                instructions=instructions,
                file_list=tuple(sorted(bundle.files)),
                loaded_at=utc_now(),
            )
            characters = len(self._context_content(loaded))
            if characters > limit:
                raise self._error(
                    "skill.active_budget_exceeded",
                    f"skill {name!r} instructions exceed the active context budget "
                    f"({characters} characters; "
                    f"limit {limit})",
                )
        workspace_path = await self.workspace.materialize(
            bundle, run_id=run_id, destination=destination
        )
        loaded = loaded.model_copy(update={"workspace_path": workspace_path})
        if len(self._context_content(loaded)) > limit:
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
                remaining = self.max_active_characters - sum(
                    len(self._context_content(value)) for value in values
                )
                if remaining > 0:
                    allowed = {
                        v.name for v in await self.catalog.list_skills(run_id=run_id)
                    }
                    current_names = {value.descriptor.name for value in values}
                    inherited = []
                    for name in dict.fromkeys(await self.inherited_skills(run_id)):
                        if remaining <= 0:
                            break
                        if name in current_names or name not in allowed:
                            continue
                        try:
                            value = await self._load_once(
                                name, run_id=run_id, budget_characters=remaining
                            )
                        except SageV2Error as exc:
                            if exc.info.code in {
                                "skill.active_budget_exceeded",
                                "skill.not_found",
                                "skill.not_enabled",
                            }:
                                continue
                            raise
                        inherited.append(value)
                        remaining -= len(self._context_content(value))
                    # History is older than this Run's explicit/default loads.
                    # Keep current activations newest for later budget eviction.
                    await self.activations.replace_loaded(
                        run_id=run_id, values=(*reversed(inherited), *values)
                    )
                self._initialized_runs.add(run_id)
                values = await self.activations.list_loaded(run_id=run_id)
            # Recheck the current grant even for durable activations on resume.
            allowed = {v.name for v in await self.catalog.list_skills(run_id=run_id)}
            return tuple(v for v in values if v.descriptor.name in allowed)

    async def _load_lock(self, run_id: str, name: str) -> asyncio.Lock:
        # Loading is concurrent across Runs but serialized inside one Agent
        # Workspace so activation order and activation eviction are stable.
        key = (run_id, "__skill_activation__")
        async with self._locks_guard:
            return self._load_locks.setdefault(key, asyncio.Lock())

    async def _enforce_active_budget(self, run_id: str) -> None:
        values = list(await self.activations.list_loaded(run_id=run_id))
        costs = [len(self._context_content(value)) for value in values]
        total = sum(costs)
        start = 0
        while total > self.max_active_characters and start < len(values):
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
    def _error(code: str, message: str) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message=message,
                safe_to_resume=True,
            )
        )
