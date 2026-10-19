"""Reusable package revisions and explicit application run routing."""

from __future__ import annotations

import asyncio
from copy import copy
from dataclasses import dataclass, field
from typing import Any

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit, PublishSessionCommit, RejectSessionCommit, SessionCommitProposal,
)
from sagents.v2.sagent import SAgentRunStream

from sagents.v2.composition.inputs import package_input
from sagents.v2.composition.agent_graph import resolve_agent_graph


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


class ApplicationEntrypoint:
    def __init__(self, catalog: LoadedAgents):
        self._catalog = catalog

    @property
    def runtime(self):
        return self._catalog.application.runtime

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

    async def start_run(self, command, context, *, agent: LoadedAgent):
        implementation = self._catalog.implementation(agent)
        if (
            command.agent_id != agent.id
            or command.resolved_spec_hash != agent.composition_hash
        ):
            raise ValueError("command Agent identity must match the loaded revision")
        return await implementation.start_run(command, context)

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

    async def continue_run(self, run_id, context, *, agent: LoadedAgent):
        implementation = self._catalog.implementation(agent)
        await self._validate_run(run_id, context, agent)
        return await implementation.continue_run(run_id, context)

    async def propose_session_commit(
        self, command: ProposeSessionCommit, context: RequestContext,
    ) -> SessionCommitProposal:
        """Propose publication using the source Run's admitted Agent revision."""
        agent = await self._catalog.application.agent_for_run(command.run_id, context)
        return await self._catalog.implementation(agent).propose_session_commit(command, context)

    async def publish_session_commit(
        self, command: PublishSessionCommit, context: RequestContext,
    ) -> SessionCommitProposal:
        """Publish through the original Agent, including derived memory ingestion."""
        access = self._catalog.application.service("session.access")
        proposal = await access.get_session_commit_proposal(command.proposal_id, context)
        agent = await self._catalog.application.agent_for_run(proposal.source_run_id, context)
        return await self._catalog.implementation(agent).publish_session_commit(command, context)

    async def reject_session_commit(
        self, command: RejectSessionCommit, context: RequestContext,
    ) -> SessionCommitProposal:
        """Reject an authorized proposal without publishing candidate history."""
        access = self._catalog.application.service("session.access")
        proposal = await access.get_session_commit_proposal(command.proposal_id, context)
        agent = await self._catalog.application.agent_for_run(proposal.source_run_id, context)
        return await self._catalog.implementation(agent).reject_session_commit(command, context)

    async def _validate_run(self, run_id, context, agent):
        access = self._catalog.application.service("session.access")
        run = await access.get_run(run_id, context)
        if run.resolved_spec_hash != agent.composition_hash:
            raise ValueError("Run must use its admitted Agent revision")

    async def drive_admitted_run(
        self, run_id, context, *, agent: LoadedAgent, resume=False
    ):
        return await self._catalog.implementation(agent).drive_admitted_run(
            run_id, context, resume=resume
        )


class LoadedAgents:
    """Serialize publication; retain revisions until App shutdown.

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
        self.entrypoint = ApplicationEntrypoint(self)
        from sagents.v2.composition.revision_store import AgentRevisionStore

        selection = runtime.capabilities.get("session.store")
        root = (
            runtime.state_root or getattr(selection, "config", {}).get("root")
            or builder._state.session_root
            or ".runtime/sagents"
        )
        self.store = AgentRevisionStore(root)
        self.restore_lock = asyncio.Lock()
        from sagents.v2.runtime.extensions.pool import ApplicationScopePool
        self.scope_pool = ApplicationScopePool()
        self.process_handles = ()
        self.process_dispatcher = None

    def implementation(self, agent):
        self.application._ensure_open()
        if not isinstance(agent, LoadedAgent) or agent._owner is not self:
            raise ValueError("Agent belongs to a different application")
        return agent._application.agent(
            agent._application.resolved_plan.entrypoint_agent_id
        )

    async def load(self, *args, **kwargs):
        self.application._ensure_open()
        async with self.lock:
            self.application._ensure_open()
            return await self._load(*args, **kwargs)

    async def _load(
        self,
        package=None,
        *,
        config_text=None,
        base_path=None,
        previous=None,
        subagents=None,
        historical=False,
        expected_hash=None,
    ):
        source = None
        if historical:
            # Private archive restoration: this is a compiled graph, not a Package input.
            resolved = package.model_copy(deep=True)
            if (resolved.runtime.plugin_trust_policy != self.runtime.plugin_trust_policy
                    or resolved.runtime.deployment_profile != self.runtime.deployment_profile):
                raise ValueError("saved Agent security profile differs from this App")
        else:
            package = package_input(package, config_text=config_text, base_path=base_path)
            source = package.model_dump(mode="json")
            for child in (subagents or {}).values():
                self.implementation(child)
            resolved = resolve_agent_graph(
                package,
                self.runtime,
                {
                    name: child._resolved
                    for name, child in (subagents or {}).items()
                },
                models=self.models,
            )
        agent_id = resolved.entrypoint_agent
        if agent_id not in resolved.agents:
            raise ValueError("Package entrypoint must be its single Agent")
        revision = resolved.manifest_hash
        key = (resolved.package_id, revision)
        async with self.application._assembly_operation():
            current = self.current.get(resolved.package_id)
            if previous is not None:
                self.implementation(previous)
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
            builder._model_resolver = self.model_resolver
            builder._state = copy(self.builder._state)
            builder._state.defer_dispatcher_start = True
            builder._state.revision_identity = True
            builder._state.dispatcher = self.process_dispatcher
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
                self.store.save(resolved, assembled.composition_hash)
            except BaseException:
                await assembled.close()
                raise
            # No awaits between successful construction and ownership/publication.
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
            dispatcher.recovery_filter = lambda run: any(
                value.composition_hash == run.resolved_spec_hash
                for value in self.revisions.values()
            )
            if not self.builder._state.manual_dispatcher_start:
                await dispatcher.start()
                await dispatcher.refresh_recovery()
            return handle

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
            for intent in await reader():
                spec_hash = intent.run.resolved_spec_hash
                if any(
                    handle.composition_hash == spec_hash
                    for handle in self.revisions.values()
                ):
                    continue
                package = self.store.read(spec_hash)
                if package is not None:
                    await self.load(package, historical=True, expected_hash=spec_hash)


class RevisionRecovery:
    """Resolve durable Runs by their admitted identity, never by latest Agent."""

    def __init__(self, catalog):
        self.catalog = catalog
        self.runtime = catalog.process_runtime

    async def _agent(self, run_id):
        run = await self.runtime.get_run(run_id)
        for handle in self.catalog.revisions.values():
            if handle.composition_hash == run.resolved_spec_hash:
                return handle._application.agent(
                    handle._application.resolved_plan.entrypoint_agent_id
                )
        raise RuntimeError("the admitted Agent revision must be loaded before recovery")

    def ensure_execution(self, run_id, context, *, resume):
        async def execute():
            agent = await self._agent(run_id)
            return await agent.ensure_execution(run_id, context, resume=resume)

        return asyncio.create_task(execute())

    async def fail_driver_crash(self, run_id, exc, context):
        return await (await self._agent(run_id)).fail_driver_crash(run_id, exc, context)

    async def recover_interrupted_run(self, run_id, context):
        return await (await self._agent(run_id)).recover_interrupted_run(
            run_id, context
        )
