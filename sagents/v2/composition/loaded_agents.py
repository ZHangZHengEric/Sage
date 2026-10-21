"""Reusable package revisions and explicit application run routing."""

from __future__ import annotations

import asyncio
from copy import copy
from dataclasses import dataclass, field
from time import monotonic
from functools import wraps
from contextlib import asynccontextmanager
from typing import Any
from weakref import WeakValueDictionary

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit, PublishSessionCommit, RejectSessionCommit, SessionCommitProposal,
)
from sagents.v2.sagent import SAgentRunStream

from sagents.v2.composition.inputs import package_input
from sagents.v2.composition.agent_graph import resolve_agent_graph
from sagents.v2.runtime.observability.logs import get_logger


_LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class StartupRecoveryIssue:
    """A Run left untouched because its admitted revision could not be restored."""

    run_id: str
    session_id: str
    resolved_spec_hash: str
    code: str
    message: str


@dataclass(frozen=True, eq=False)
class LoadedAgent:
    """An immutable loaded revision. Old handles keep their original behavior."""

    id: str
    version: str
    package_id: str
    composition_hash: str
    _application: Any = field(repr=False)
    _owner: LoadedAgents = field(repr=False)
    _resolved: object = field(repr=False)

    @property
    def resolved_plan(self):
        """Inspect this revision rather than the App's initial process plan."""
        return self._application.resolved_plan

    @property
    def resource_readiness(self):
        return self._application.resource_readiness


@dataclass(frozen=True)
class ReleasedRevision:
    """Keep handle inspection available without retaining closed providers."""

    resolved_plan: Any
    resource_readiness: Any
    _closed: bool = True


@dataclass
class RetiringRevision:
    """Quarantine closing resources until teardown has actually completed."""

    handle: LoadedAgent
    task: asyncio.Task | None = None


def revision_operation(method):
    """Pin a revision through admission/control; driver tasks pin execution."""
    @wraps(method)
    async def invoke(self, *args, agent, **kwargs):
        catalog = self._catalog
        async with catalog.pin(agent) as agent:
            return await method(self, *args, agent=agent, **kwargs)
    return invoke


class ApplicationEntrypoint:
    def __init__(self, catalog: LoadedAgents):
        self._catalog = catalog

    @property
    def runtime(self):
        return self._catalog.application.runtime

    @revision_operation
    async def run_stream(
        self, command: StartRun, context: RequestContext, *, agent: LoadedAgent
    ) -> SAgentRunStream:
        implementation = self._catalog.implementation(agent)
        if (
            command.agent_id != agent.id
            or command.resolved_spec_hash != agent.composition_hash
        ):
            raise ValueError("command Agent identity must match the loaded revision")
        return await implementation.run_stream(command, context)

    @revision_operation
    async def start_run(self, command, context, *, agent: LoadedAgent):
        implementation = self._catalog.implementation(agent)
        if (
            command.agent_id != agent.id
            or command.resolved_spec_hash != agent.composition_hash
        ):
            raise ValueError("command Agent identity must match the loaded revision")
        return await implementation.start_run(command, context)

    @revision_operation
    async def schedule_accepted_run(
        self, handle, context, *, agent: LoadedAgent, resume=False
    ):
        implementation = self._catalog.implementation(agent)
        await self._validate_run(handle.run_id, context, agent)
        if handle.resolved_spec_hash != agent.composition_hash:
            raise ValueError("accepted Run does not match the loaded revision")
        return await implementation.schedule_accepted_run(
            handle, context, resume=resume
        )

    @revision_operation
    async def continue_run(self, run_id, context, *, agent: LoadedAgent):
        implementation = self._catalog.implementation(agent)
        await self._validate_run(run_id, context, agent)
        return await implementation.continue_run(run_id, context)

    async def propose_session_commit(
        self, command: ProposeSessionCommit, context: RequestContext,
    ) -> SessionCommitProposal:
        """Propose publication using the source Run's admitted Agent revision."""
        agent = await self._catalog.application.agent_for_run(command.run_id, context)
        async with self._catalog.pin(agent) as agent:
            return await self._catalog.implementation(agent).propose_session_commit(command, context)

    async def publish_session_commit(
        self, command: PublishSessionCommit, context: RequestContext,
    ) -> SessionCommitProposal:
        """Publish through the original Agent, including derived memory ingestion."""
        access = self._catalog.application.service("session.access")
        proposal = await access.get_session_commit_proposal(command.proposal_id, context)
        agent = await self._catalog.application.agent_for_run(proposal.source_run_id, context)
        async with self._catalog.pin(agent) as agent:
            return await self._catalog.implementation(agent).publish_session_commit(command, context)

    async def reject_session_commit(
        self, command: RejectSessionCommit, context: RequestContext,
    ) -> SessionCommitProposal:
        """Reject an authorized proposal without publishing candidate history."""
        access = self._catalog.application.service("session.access")
        proposal = await access.get_session_commit_proposal(command.proposal_id, context)
        agent = await self._catalog.application.agent_for_run(proposal.source_run_id, context)
        async with self._catalog.pin(agent) as agent:
            return await self._catalog.implementation(agent).reject_session_commit(command, context)

    async def _validate_run(self, run_id, context, agent):
        access = self._catalog.application.service("session.access")
        run = await access.get_run(run_id, context)
        if run.resolved_spec_hash != agent.composition_hash:
            raise ValueError("Run must use its admitted Agent revision")

    @revision_operation
    async def drive_admitted_run(
        self, run_id, context, *, agent: LoadedAgent, resume=False
    ):
        return await self._catalog.implementation(agent).drive_admitted_run(
            run_id, context, resume=resume
        )


class LoadedAgents:
    """Build revisions independently and retain bounded idle revision resources.

    A failed update never replaces the current revision. Each revision owns its
    execution scopes, while subsequent revisions borrow durable process stores.
    """

    def __init__(self, application, builder, runtime, tenant_id, models):
        self.application = application
        self.builder = builder
        self.runtime = runtime
        from sagents.v2.package.manifest.resolver import CompositionResolver
        self.models = models
        self.model_resolver = CompositionResolver(models=models)
        self.sources = {}
        self.tenant_id = tenant_id
        self.root = None
        self.current = {}
        self.revisions = {}
        self.lock = asyncio.Lock()
        self._load_locks = {}
        self._last_used = {}
        self._users = {}
        self._prune_lock = asyncio.Lock()
        self._retiring = {}
        self._reaper = None
        self._exported_agents = WeakValueDictionary()
        self.max_idle_revisions = 64
        self.revision_idle_seconds = 300.0
        self.entrypoint = ApplicationEntrypoint(self)
        from sagents.v2.composition.revision_store import AgentRevisionStore

        selection = runtime.capabilities.get("session.store")
        root = (
            runtime.state_root or getattr(selection, "config", {}).get("root")
            or builder._state.session_root
            or ".runtime/sagents"
        )
        self.store = builder._revision_store or AgentRevisionStore(root)
        self.restore_lock = asyncio.Lock()
        self.recovery_issues: tuple[StartupRecoveryIssue, ...] = ()
        from sagents.v2.runtime.extensions.pool import ApplicationScopePool
        self.scope_pool = ApplicationScopePool()
        self.process_handles = ()
        self.process_dispatcher = None

    def exported(self, agent):
        from sagents.v2.composition.application_agent import ApplicationAgent
        facade = self._exported_agents.get(agent)
        if facade is None:
            facade = ApplicationAgent(self, agent)
            self._exported_agents[agent] = facade
        return facade

    def implementation(self, agent):
        self.application._ensure_open()
        if not isinstance(agent, LoadedAgent) or agent._owner is not self:
            raise ValueError("Agent belongs to a different application")
        agent = self.revisions.get((agent.package_id, agent.version), agent)
        if isinstance(agent._application, ReleasedRevision):
            raise RuntimeError("Agent resources are idle; use the async entrypoint or load_agent to restore them")
        return agent._application.agent(
            agent._application.resolved_plan.entrypoint_agent_id
        )

    def selected_runtime(self, runtime=None):
        from sagents.v2.composition.inputs import runtime_input
        from sagents.v2.composition.defaults import effective_runtime
        selected = self.runtime.model_copy(deep=True) if runtime is None else effective_runtime(runtime_input(runtime))
        self.builder._registry.validate_runtime(selected)
        if selected.state_root != self.runtime.state_root:
            raise ValueError("state_root is an App identity; create a new App to change it")
        for capability in ("session.store", "derived-state.store", "execution.scheduler", "execution.job-runtime"):
            if selected.selections(capability) != self.runtime.selections(capability):
                raise ValueError(f"{capability} is an App identity; create a new App to change it")
        if (selected.plugin_trust_policy != self.runtime.plugin_trust_policy
                or selected.deployment_profile != self.runtime.deployment_profile):
            raise ValueError("security profile is an App identity; create a new App to change it")
        return selected

    async def load(self, *args, **kwargs):
        async with self.application._assembly_operation():
            return await self._load(*args, **kwargs)

    async def _load(self, package=None, *, config_text=None, base_path=None,
                   previous=None, subagents=None, historical=False, expected_hash=None,
                   runtime=None, models=None):
        self.application._ensure_open()
        from sagents.v2.model.catalog import model_catalog_input
        selected_runtime = self.selected_runtime(runtime)
        selected_models = self.models.model_copy(deep=True) if models is None else model_catalog_input(models)
        source = None
        if historical:
            resolved = package.model_copy(deep=True)
            selected_models = model_catalog_input({"models": resolved.model_routes, "credentials": resolved.credentials})
            if (resolved.runtime.plugin_trust_policy != self.runtime.plugin_trust_policy
                    or resolved.runtime.deployment_profile != self.runtime.deployment_profile):
                raise ValueError("saved Agent security profile differs from this App")
        else:
            package = package_input(package, config_text=config_text, base_path=base_path)
            source = package.model_dump(mode="json")
            for child in (subagents or {}).values():
                if child._owner is not self:
                    raise ValueError("Agent belongs to a different application")
            resolved = resolve_agent_graph(package, selected_runtime,
                {name: child._resolved for name, child in (subagents or {}).items()},
                models=selected_models)
        key = (resolved.package_id, resolved.manifest_hash)
        if key in self._retiring:
            await self._finish_retirement(key)
        lock_state = self._load_locks.setdefault(key, [asyncio.Lock(), 0])
        lock_state[1] += 1
        try:
            async with lock_state[0]:
                handle = await self._load_resolved(resolved, source=source, previous=previous,
                    historical=historical, expected_hash=expected_hash)
                if expected_hash is not None and handle.composition_hash != expected_hash:
                    raise ValueError("saved Agent revision no longer matches the runtime composition")
                self._last_used[key] = monotonic()
                await self.prune_revisions(protected=handle, suppress_errors=True)
                return handle
        finally:
            lock_state[1] -= 1
            if not lock_state[1]:
                self._load_locks.pop(key, None)

    async def _load_resolved(self, resolved, *, source, previous, historical, expected_hash):
        agent_id = resolved.entrypoint_agent
        if agent_id not in resolved.agents:
            raise ValueError("Package entrypoint must be its single Agent")
        revision = resolved.manifest_hash
        key = (resolved.package_id, revision)
        async with self.application._assembly_operation():
            current = self.current.get(resolved.package_id)
            if previous is not None:
                if not isinstance(previous, LoadedAgent) or previous._owner is not self:
                    raise ValueError("Agent belongs to a different application")
                if (
                    previous.package_id != resolved.package_id
                    or previous._application.resolved_plan.entrypoint_agent_id
                    != agent_id
                ):
                    raise ValueError("update must preserve Package and Agent identity")
                if current is not previous:
                    raise ValueError("Agent was updated; use its current revision")
            elif key in self.revisions:
                if not historical and self.sources.get(resolved.package_id) == source:
                    self.current[resolved.package_id] = self.revisions[key]
                return self.revisions[key]
            elif (not historical and current is not None and current.version != revision
                  and self.sources.get(resolved.package_id) != source):
                raise ValueError("Package changed; use update_agent explicitly")
            existing = self.revisions.get(key)
            if existing is not None:
                self.current[resolved.package_id] = existing
                self.sources[resolved.package_id] = source
                return existing
            builder = copy(self.builder)
            builder._scope_pool = self.scope_pool
            builder._shared_process_handles = self.process_handles
            # The package graph already freezes its routes. Package registry
            # drafts, however, must resolve against subsequent App catalog edits.
            builder._model_resolver = self.model_resolver
            builder._state = copy(self.builder._state)
            builder._state.defer_dispatcher_start = True
            builder._state.revision_identity = True
            builder._state.dispatcher = self.process_dispatcher
            from sagents.v2.composition.revision_store import MigratedAgentRevision
            identity = resolved._recovery_identity if isinstance(resolved, MigratedAgentRevision) else None
            if identity is not None and (not historical or identity.admitted_hash != expected_hash):
                raise ValueError("migrated Agent revision must restore its admitted identity")
            builder._state.recovery_identity = identity
            assembled = await builder._build_package(resolved, tenant_id=self.tenant_id)
            handle = LoadedAgent(
                resolved.package_id,
                resolved.manifest_hash,
                resolved.package_id,
                assembled.composition_hash,
                assembled,
                self,
                resolved,
            )
            try:
                if (
                    expected_hash is not None
                    and assembled.composition_hash != expected_hash
                ):
                    raise ValueError(
                        "saved Agent revision no longer matches the runtime composition"
                    )
                await asyncio.to_thread(self.store.save, resolved, assembled.composition_hash)
            except BaseException:
                await assembled.close()
                raise
            # Different revisions may build concurrently; compare-and-swap
            # publication after construction so a stale update cannot win.
            if previous is not None and self.current.get(resolved.package_id) is not previous:
                await assembled.close()
                raise ValueError("Agent was updated; use its current revision")
            if (previous is None and not historical
                    and resolved.package_id in self.current
                    and self.sources.get(resolved.package_id) != source):
                await assembled.close()
                raise ValueError("Package changed; use update_agent explicitly")
            # No awaits between successful construction and ownership/publication.
            if self._reaper is None:
                self._reaper = RevisionReaper(self)
                self.application._owned_resources.append(self._reaper)
            self.application._owned_resources.append(assembled)
            if self.root is None:
                self.root = assembled
                self.application._services = {**self.application._services, **assembled.services}
                self.application.composition_hash = assembled.composition_hash
                self.application.resolved_plan = assembled.resolved_plan
                self.application.resource_readiness = assembled.resource_readiness
            if not historical:
                self.current[resolved.package_id] = handle
                self.sources[resolved.package_id] = source
            self.revisions[key] = handle
            dispatcher = assembled.service("execution.dispatcher")
            # Stop dispatch before any revision resources during App shutdown.
            if dispatcher in self.application._owned_resources:
                self.application._owned_resources.remove(dispatcher)
            self.application._owned_resources.append(dispatcher)
            dispatcher.attach_recovery_agent(RevisionRecovery(self), replace=True)
            dispatcher.recovery_filter = lambda run: (self.store.contains(run.resolved_spec_hash)
                and all(issue.resolved_spec_hash != run.resolved_spec_hash for issue in self.recovery_issues))
            if not self.builder._state.manual_dispatcher_start:
                await dispatcher.start()
                await dispatcher.refresh_recovery()
            return handle

    async def prune_revisions(self, *, protected=None, suppress_errors=False):
        """Release obsolete idle resources; immutable recovery files stay intact."""
        async with self._prune_lock:
            errors = await self._prune_revisions(protected=protected, retry_failed=not suppress_errors)
            if errors and not suppress_errors:
                raise errors[0]

    async def _prune_revisions(self, *, protected=None, retry_failed=True):
        errors = []

        async def finish(key):
            try:
                await self._finish_retirement(key)
            except Exception as exc:
                errors.append(exc)
                _LOGGER.exception("agent.revision_cache_cleanup_failed", "Idle revision remains quarantined", exc,
                                  package_id=key[0], revision=key[1])

        # A failed teardown stays isolated. Retry it on later maintenance, never
        # republish an Application whose close() has already started.
        if retry_failed:
            for key, retiring in tuple(self._retiring.items()):
                if retiring.task is None or retiring.task.done():
                    await finish(key)
        now = monotonic()
        candidates = sorted(tuple(self.revisions.items()), key=lambda item: self._last_used.get(item[0], now))
        idle = []
        for key, handle in candidates:
            if handle is protected or handle._application is self.root or self._users.get(handle, 0):
                continue
            agents = handle._application._agents.values()
            if any(any(not task.done() for task in agent._tasks.values()) or agent._observers for agent in agents):
                continue
            idle.append((key, handle))
        for key, handle in tuple(idle):
            if self.revisions.get(key) is not handle or self._users.get(handle, 0):
                continue
            agents = handle._application._agents.values()
            if any(any(not task.done() for task in agent._tasks.values()) or agent._observers for agent in agents):
                continue
            if len(idle) <= self.max_idle_revisions and now - self._last_used.get(key, now) < self.revision_idle_seconds:
                continue
            # Retire synchronously before awaiting teardown: entrypoint calls
            # can restore from the archive but cannot reuse closing resources.
            self._retiring[key] = RetiringRevision(handle)
            self.revisions.pop(key, None)
            await finish(key)
            idle.remove((key, handle))
        return errors

    async def _finish_retirement(self, key):
        retiring = self._retiring.get(key)
        if retiring is None:
            return
        if retiring.task is None or retiring.task.done():
            retiring.task = asyncio.create_task(
                self._close_revision(key, retiring), name="sagent-revision-retirement"
            )
            # The initiating request may disappear while teardown runs. Retrieve
            # its exception without losing the failed record needed for retry.
            retiring.task.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        await asyncio.shield(retiring.task)

    async def _close_revision(self, key, retiring):
        handle = retiring.handle
        application = handle._application
        await application.close()
        if application in self.application._owned_resources:
            self.application._owned_resources.remove(application)
        released = ReleasedRevision(handle.resolved_plan, handle.resource_readiness)
        object.__setattr__(handle, "_application", released)
        self._last_used.pop(key, None)
        self._retiring.pop(key, None)

    @asynccontextmanager
    async def pin(self, agent):
        agent = await self.restored(agent)
        self._users[agent] = self._users.get(agent, 0) + 1
        try:
            yield agent
        finally:
            count = self._users[agent] - 1
            if count:
                self._users[agent] = count
            else:
                self._users.pop(agent, None)
            self._last_used[(agent.package_id, agent.version)] = monotonic()

    async def restored(self, agent):
        if not isinstance(agent, LoadedAgent) or agent._owner is not self:
            raise ValueError("Agent belongs to a different application")
        key = (agent.package_id, agent.version)
        if key in self.revisions:
            self._last_used[key] = monotonic()
            return self.revisions[key]
        return await self.load(agent._resolved, historical=True, expected_hash=agent.composition_hash)

    async def for_run(self, run_id, context):
        run = await self.application.service("session.access").get_run(run_id, context)
        for handle in self.revisions.values():
            if handle.composition_hash == run.resolved_spec_hash:
                return handle
        package = self.store.read(run.resolved_spec_hash)
        if package is None:
            raise ValueError("the admitted Agent revision is unavailable")
        return await self.load(
            package, historical=True, expected_hash=run.resolved_spec_hash
        )

    async def restore_pending(self):
        async with self.restore_lock:
            if self.application._closing or self.application._closed:
                return
            store = self.process_runtime.session_store
            reader = getattr(store, "list_dispatchable_runs", None)
            if reader is None:
                return
            issues = []
            failures = {}
            for intent in await reader():
                spec_hash = intent.run.resolved_spec_hash
                if any(
                    handle.composition_hash == spec_hash
                    for handle in self.revisions.values()
                ):
                    continue
                if spec_hash not in failures:
                    try:
                        package = self.store.read(spec_hash)
                        if package is None:
                            raise FileNotFoundError("the admitted Agent revision is unavailable")
                        await self.load(package, historical=True, expected_hash=spec_hash)
                    except Exception as exc:
                        # Cancellation and process exits must still abort startup.
                        # Do not mutate the Run: a crossed tool barrier may carry
                        # an external outcome that only its original Agent can reconcile.
                        failures[spec_hash] = exc
                    else:
                        continue
                error = failures[spec_hash]
                issue = StartupRecoveryIssue(
                    run_id=intent.run.run_id,
                    session_id=intent.run.session_id,
                    resolved_spec_hash=spec_hash,
                    code="recovery.agent_revision_unavailable",
                    message=str(error),
                )
                issues.append(issue)
                _LOGGER.exception(
                    issue.code, "Run recovery blocked; continuing App startup", error,
                    run_id=issue.run_id, session_id=issue.session_id,
                    resolved_spec_hash=spec_hash,
                )
            self.recovery_issues = tuple(issues)


class RevisionReaper:
    def __init__(self, catalog):
        self.catalog = catalog
        self.task = asyncio.create_task(self._run(), name="sagent-revision-cache")

    async def _run(self):
        while True:
            await asyncio.sleep(30)
            if self.catalog.application._closing:
                return
            try:
                async with self.catalog.application._assembly_operation():
                    await self.catalog.prune_revisions()
            except Exception as exc:
                _LOGGER.exception("agent.revision_cache_cleanup_failed", "Idle revision cleanup failed", exc)

    async def close(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)
        for key in tuple(self.catalog._retiring):
            await self.catalog._finish_retirement(key)


class RevisionRecovery:
    """Resolve durable Runs by their admitted identity, never by latest Agent."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.runtime = catalog.process_runtime

    async def _agent(self, run_id):
        run = await self.runtime.get_run(run_id)
        for handle in self.catalog.revisions.values():
            if handle.composition_hash == run.resolved_spec_hash:
                return handle
        resolved = self.catalog.store.read(run.resolved_spec_hash)
        if resolved is None:
            raise RuntimeError("the admitted Agent revision is unavailable")
        handle = await self.catalog.load(resolved, historical=True, expected_hash=run.resolved_spec_hash)
        return handle

    def ensure_execution(self, run_id, context, *, resume):
        async def execute():
            async with self.catalog.pin(await self._agent(run_id)) as agent:
                return await self.catalog.implementation(agent).ensure_execution(run_id, context, resume=resume)

        return asyncio.create_task(execute())

    async def fail_driver_crash(self, run_id, exc, context):
        async with self.catalog.pin(await self._agent(run_id)) as agent:
            return await self.catalog.implementation(agent).fail_driver_crash(run_id, exc, context)

    async def recover_interrupted_run(self, run_id, context):
        async with self.catalog.pin(await self._agent(run_id)) as agent:
            return await self.catalog.implementation(agent).recover_interrupted_run(run_id, context)
