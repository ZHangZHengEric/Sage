"""Lazy Skill loading with bounded restoration from Session history."""

from __future__ import annotations

import asyncio
import hashlib
from inspect import signature
from weakref import WeakValueDictionary
from xml.sax.saxutils import escape
from collections.abc import Awaitable, Callable, Iterable

from sagents.v2.skill.contracts import (
    LoadedSkill,
    SkillBundle,
    SkillActivationRepository,
    SkillCatalog,
    SkillDescriptor,
    SkillReference,
    RunSkillProvider,
    SkillSource,
    SkillRunState,
    SkillWorkspace,
)
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.skill_payload import files_digest
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
    errors_before_side_effect,
)


def _check_skill_name(requested: str, returned: str) -> None:
    if returned != requested:
        raise SageV2Error(RuntimeErrorInfo(
            code="skill.identity_mismatch",
            category=ErrorCategory.PROVIDER_PERMANENT,
            message=f"Skill provider returned a different identity for {requested!r}",
            safe_to_resume=True,
        ))


async def visible_skill_descriptors(
    catalog: SkillCatalog, names: Iterable[str], *, run_id: str
) -> tuple[SkillDescriptor, ...]:
    descriptors = []
    for name in names:
        try:
            descriptor = await catalog.get_skill(name, run_id=run_id)
            _check_skill_name(name, descriptor.name)
            descriptors.append(descriptor)
        except SageV2Error as exc:
            if exc.info.code not in {"skill.not_enabled", "skill.not_found"}:
                raise
    return tuple(descriptors)


class FilteredSkillCatalog:
    """Run-scoped allowlist. Metadata access does not fetch or materialize files."""

    def __init__(self, inner: SkillCatalog, allowed: Iterable[str]) -> None:
        self.inner = inner
        self.allowed = frozenset(allowed)

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        values = await self.inner.list_skills(run_id=run_id)
        return tuple(value for value in values if value.name in self.allowed)

    async def search_skills(self, query, *, run_id, limit, allowed_names=None, excluded_names=frozenset()):
        allowed = self.allowed if allowed_names is None else self.allowed & allowed_names
        allowed = allowed - excluded_names
        if not allowed:
            return ()
        values = await self.inner.search_skills(
            query, run_id=run_id, allowed_names=allowed, limit=limit
        )
        return tuple(item for item in values if item.name in allowed)[:limit]

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
        descriptor = await self.inner.get_skill(name, run_id=run_id)
        _check_skill_name(name, descriptor.name)
        return descriptor


class InvocationGrantSkillCatalog:
    """Intersect the Agent ceiling with the durable per-Run Skill grant."""

    def __init__(
        self,
        inner: SkillCatalog,
        command_reader: Callable[[str], Awaitable[object]],
    ) -> None:
        self.inner = inner
        self.command_reader = command_reader

    async def allowed_names(self, run_id: str) -> frozenset[str] | None:
        command = await self.command_reader(run_id)
        configured = getattr(getattr(command, "config", None), "enabled_skills", None)
        return None if configured is None else frozenset(configured)

    async def list_skills(self, *, run_id: str) -> tuple[SkillDescriptor, ...]:
        values = await self.inner.list_skills(run_id=run_id)
        allowed = await self.allowed_names(run_id)
        if allowed is None:
            return values
        return tuple(value for value in values if value.name in allowed)

    async def search_skills(self, query, *, run_id, limit, excluded_names=frozenset()):
        return await self.inner.search_skills(
            query, run_id=run_id, limit=limit, allowed_names=await self.allowed_names(run_id),
            excluded_names=excluded_names,
        )

    async def get_skill(self, name: str, *, run_id: str) -> SkillDescriptor:
        allowed = await self.allowed_names(run_id)
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
        run_provider: RunSkillProvider | None = None,
        run_skill_names: Callable[[str], Awaitable[frozenset[str] | None]] | None = None,
    ) -> None:
        if max_active_characters < 1:
            raise ValueError("max_active_characters must be positive")
        self.inherited_skills = inherited_skills
        self._initialized_runs: set[str] = set()
        self._requested_names: dict[str, set[str]] = {}
        self._preload_states: dict[str, SkillRunState] = {}
        self.catalog = catalog
        self.source = source
        self.run_provider = run_provider
        self.run_skill_names = run_skill_names
        self.workspace = workspace
        self.activations = activations
        self.workspace_root = workspace_root.rstrip("/") or "/"
        self.max_active_characters = max_active_characters
        self._locks_guard = asyncio.Lock()
        self._load_locks: WeakValueDictionary = WeakValueDictionary()

    async def search_skills(self, query: str, *, run_id: str, limit: int) -> tuple[SkillDescriptor, ...]:
        if self.run_provider is None:
            from sagents.v2.skill.search import has_search_terms

            if not has_search_terms(query):
                return ()
            return await self.catalog.search_skills(query, run_id=run_id, limit=limit)
        allowed = await self.run_skill_names(run_id) if self.run_skill_names is not None else None
        if not query.strip() or allowed == frozenset():
            return ()
        search = self.run_provider.search_skills
        if allowed is None:
            matches = await search(query, run_id=run_id, limit=limit)
        else:
            try:
                signature(search).bind(query, run_id=run_id, limit=limit, allowed_names=allowed)
            except (TypeError, ValueError):
                # Legacy providers accept only top-k. Expand the search within
                # a bounded window before applying the Run's name grant.
                matches = await search(query, run_id=run_id, limit=max(limit, 100))
            else:
                matches = await search(query, run_id=run_id, limit=limit, allowed_names=allowed)
        matches = tuple(item for item in matches if allowed is None or item.name in allowed)[:limit]
        references = tuple(item.reference for item in matches if item.reference is not None)
        if len(references) != len(matches):
            raise self._error("skill.reference_missing", "Run Skill search results require exact references")
        lock = await self._load_lock(run_id, "")
        async with lock:
            state = self._preload_states.get(run_id, SkillRunState())
            self._preload_states[run_id] = state.model_copy(update={
                "discovered_references": tuple(dict.fromkeys((*state.discovered_references, *references))),
            })
        return matches

    async def _fetch_reference(self, reference: SkillReference, run_id: str) -> SkillBundle:
        if self.run_provider is None:
            raise self._error("skill.reference_unsupported", "The selected Skill provider cannot resolve references")
        allowed = await self.run_skill_names(run_id) if self.run_skill_names is not None else None
        if allowed == frozenset():
            raise self._error("skill.not_enabled", "Skills are disabled for this Run")
        bundle = await self.run_provider.fetch_reference(reference, run_id=run_id)
        if allowed is not None and bundle.descriptor.name not in allowed:
            raise self._error("skill.not_enabled", "The Skill is outside this Run's authorized names")
        if bundle.descriptor.reference != reference or files_digest(bundle.files) != bundle.content_hash:
            raise self._error("skill.identity_mismatch", "The fetched Skill does not match its reference or content hash")
        return bundle

    def _destination(self, descriptor: SkillDescriptor, *, run_id: str) -> str:
        root = self.workspace_root.rstrip("/")
        namespace = descriptor.metadata.get("workspace_namespace")
        reference = descriptor.reference
        if reference is not None:
            namespace = f"{run_id}\0{reference.skill_id}\0{reference.version_id}"
        if isinstance(namespace, str) and namespace:
            scope = hashlib.sha256(namespace.encode("utf-8")).hexdigest()
            root = f"{root}/.sage-skill-scopes/{scope}"
        return f"{root}/skills/{descriptor.name}"

    async def _fetch_bundle(self, name: str, run_id: str) -> SkillBundle:
        fetch = self.source.fetch
        if getattr(self.workspace, "manager_authoritative", False):
            fetch = getattr(self.source, "fetch_latest", fetch)
        bundle = await fetch(name, run_id=run_id)
        _check_skill_name(name, bundle.descriptor.name)
        return bundle

    async def _fetch_restore_bundle(self, value: LoadedSkill, run_id: str) -> SkillBundle:
        name = value.descriptor.name
        fetch_version = getattr(self.source, "fetch_for_restore", None)
        if (getattr(self.workspace, "manager_authoritative", False)
                and value.descriptor.version is not None and callable(fetch_version)):
            bundle = await fetch_version(name, run_id=run_id, version=value.descriptor.version)
            if bundle.descriptor.version != value.descriptor.version:
                raise self._error("skill.restore_version_changed", "Skill source returned a different checkpoint version")
        else:
            bundle = await self.source.fetch(name, run_id=run_id)
            if (getattr(self.workspace, "manager_authoritative", False)
                    and bundle.content_hash != value.content_hash):
                # Older sources may expose the accepted content only as their current version.
                bundle = await self._fetch_bundle(name, run_id)
        _check_skill_name(name, bundle.descriptor.name)
        return bundle

    async def snapshot_run(self, run_id: str) -> dict:
        lock = await self._load_lock(run_id, "")
        async with lock:
            state = self._preload_states.get(run_id, SkillRunState())
            values = await self.activations.list_loaded(run_id=run_id)
            active = tuple(value.model_copy(update={"instructions": ""})
                           if value.descriptor.reference is not None else value for value in values)
            return state.model_copy(update={
                "active": active,
                "history_initialized": run_id in self._initialized_runs,
                "requested_names": tuple(sorted(self._requested_names.get(run_id, ()))),
            }).model_dump(mode="json", exclude={
                key for key in ("discovered_references", "selected_references") if not getattr(state, key)
            })

    async def restore_run(self, run_id: str, snapshot: dict) -> None:
        lock = await self._load_lock(run_id, "")
        async with lock:
            # Restore the exact activation list, including an intentionally empty one.
            # Never infer initialization from which skill bodies happen to remain.
            state = SkillRunState.model_validate(snapshot)
            if any(value.run_id != run_id for value in state.active):
                raise self._error("skill.state_invalid", "skill state belongs to another Run")
            reattach = getattr(self.workspace, "reattach", None)
            restored = []
            for value in state.active:
                reference = value.descriptor.reference
                if reference is not None:
                    if reference not in state.selected_references:
                        raise self._error("skill.state_invalid", "Active Skill reference was not selected in this Run")
                    bundle = await self._fetch_reference(reference, run_id)
                    _check_skill_name(value.descriptor.name, bundle.descriptor.name)
                    if bundle.content_hash != value.content_hash:
                        raise self._error("skill.restore_version_changed", "The selected Skill contents changed")
                    value = value.model_copy(update={"instructions": self._instructions(bundle)})
                    destination = self._destination(value.descriptor, run_id=run_id)
                    if reattach is None:
                        path = await self.workspace.materialize(bundle, run_id=run_id, destination=destination)
                        value = value.model_copy(update={"workspace_path": path})
                    else:
                        value = await reattach(value, bundle, run_id=run_id, destination=destination)
                elif reattach is not None:
                    descriptor = await self.catalog.get_skill(value.descriptor.name, run_id=run_id)
                    _check_skill_name(value.descriptor.name, descriptor.name)
                    bundle = await self._fetch_restore_bundle(value, run_id)
                    value = await reattach(
                        value, bundle, run_id=run_id,
                        destination=self._destination(descriptor, run_id=run_id),
                    )
                    _check_skill_name(descriptor.name, value.descriptor.name)
                restored.append(value)
            await self.activations.replace_loaded(run_id=run_id, values=tuple(restored))
            self._preload_states[run_id] = state.model_copy(update={"active": ()})
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

    async def load_reference(self, reference: SkillReference, *, run_id: str) -> LoadedSkill:
        lock = await self._load_lock(run_id, "")
        async with lock:
            state = self._preload_states.get(run_id, SkillRunState())
            if reference not in state.discovered_references:
                raise self._error("skill.reference_not_found", "Select a Skill reference from this Run's search results")
            if any(item.skill_id == reference.skill_id and item != reference for item in state.selected_references):
                raise self._error("skill.version_conflict", "A different version of this Skill is already selected")
            with errors_before_side_effect("skill.load_preflight_failed"):
                bundle = await self._fetch_reference(reference, run_id)
                name = bundle.descriptor.name
                values = await self.activations.list_loaded(run_id=run_id)
                existing = next((value for value in values if value.descriptor.name == name), None)
                if existing is not None:
                    if existing.descriptor.reference != reference or existing.content_hash != bundle.content_hash:
                        raise self._error("skill.identity_conflict", f"Another Skill is already active as {name!r}")
                    await self.activations.replace_loaded(run_id=run_id, values=(
                        *(value for value in values if value is not existing), existing,
                    ))
                    return existing
                prepared = self._prepare_loaded(bundle, run_id=run_id,
                    destination=self._destination(bundle.descriptor, run_id=run_id),
                    limit=self.max_active_characters)
            loaded = await self._materialize(bundle, prepared, limit=self.max_active_characters)
            self._preload_states[run_id] = state.model_copy(update={
                "selected_references": tuple(dict.fromkeys((*state.selected_references, reference))),
            })
            return loaded

    async def begin_edit(self, name: str, *, run_id: str) -> LoadedSkill:
        """Prepare the visible editing directory without changing the source.

        Hosts expose this method through an explicitly authorized editing tool.
        The selected workspace policy determines how the next load treats edits.
        """
        lock = await self._load_lock(run_id, name)
        async with lock:
            edit = getattr(self.workspace, "begin_edit", None)
            if edit is None:
                raise self._error("skill.edit_unsupported", "Selected workspace does not support editing copies")
            loaded = await self._load_once(name, run_id=run_id)
            bundle = await self._fetch_bundle(name, run_id)
            destination = self._destination(loaded.descriptor, run_id=run_id)
            await edit(bundle, run_id=run_id, destination=destination)
            values = await self.activations.list_loaded(run_id=run_id)
            await self.activations.replace_loaded(run_id=run_id, values=tuple(
                value for value in values if value.descriptor.name != name
            ))
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
            _check_skill_name(name, descriptor.name)
        existing = {
            value.descriptor.name: value
            for value in await self.activations.list_loaded(run_id=run_id)
        }.get(name)
        # A resumed run with a durable activation record does not fetch or copy
        # the bundle again. The workspace provider owns durability/reattachment.
        if existing is not None and not getattr(self.workspace, "refresh_on_load", False):
            values = await self.activations.list_loaded(run_id=run_id)
            await self.activations.replace_loaded(
                run_id=run_id,
                values=(*(v for v in values if v.descriptor.name != name), existing),
            )
            return existing

        with errors_before_side_effect("skill.load_preflight_failed"):
            # This is the first operation that is allowed to read the Level-2 bundle.
            bundle = await self._fetch_bundle(name, run_id)
            if bundle.descriptor.reference is not None:
                raise self._error("skill.reference_required", "Load this Skill by its exact reference")
            destination = self._destination(descriptor, run_id=run_id)
            resolve_bundle = getattr(self.workspace, "resolve_bundle", None)
            if resolve_bundle is not None:
                bundle = await resolve_bundle(bundle, run_id=run_id, destination=destination)
                _check_skill_name(name, bundle.descriptor.name)
            loaded = self._prepare_loaded(bundle, run_id=run_id, destination=destination, limit=limit)
        return await self._materialize(bundle, loaded, limit=limit)

    def _instructions(self, bundle: SkillBundle) -> str:
        try:
            return bundle.files["SKILL.md"].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise self._error("skill.invalid_utf8", "SKILL.md must be UTF-8") from exc

    def _prepare_loaded(self, bundle: SkillBundle, *, run_id: str, destination: str, limit: int) -> LoadedSkill:
        loaded = LoadedSkill(
            run_id=run_id,
            descriptor=bundle.descriptor,
            workspace_path=destination,
            content_hash=bundle.content_hash,
            instructions=self._instructions(bundle),
            file_list=tuple(sorted(bundle.files)),
            loaded_at=utc_now(),
        )
        characters = len(self._context_content(loaded))
        if characters > limit:
            raise self._error(
                "skill.active_budget_exceeded",
                f"skill {bundle.descriptor.name!r} instructions exceed the active context budget "
                f"({characters} characters; limit {limit})",
            )
        return loaded

    async def _materialize(self, bundle: SkillBundle, loaded: LoadedSkill, *, limit: int) -> LoadedSkill:
        workspace_path = await self.workspace.materialize(
            bundle, run_id=loaded.run_id, destination=loaded.workspace_path
        )
        loaded = loaded.model_copy(update={"workspace_path": workspace_path})
        if len(self._context_content(loaded)) > limit:
            raise self._error(
                "skill.active_budget_exceeded",
                "materialized skill context exceeds the active budget",
            )
        await self.activations.put_loaded(loaded)
        await self._enforce_active_budget(loaded.run_id)
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
                    current_names = {value.descriptor.name for value in values}
                    inherited = []
                    for name in dict.fromkeys(await self.inherited_skills(run_id)):
                        if remaining <= 0:
                            break
                        if name in current_names:
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
            visible = await visible_skill_descriptors(
                self.catalog,
                (value.descriptor.name for value in values if value.descriptor.reference is None),
                run_id=run_id,
            )
            allowed = {descriptor.name for descriptor in visible}
            return tuple(value for value in values
                         if value.descriptor.reference is not None or value.descriptor.name in allowed)

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
