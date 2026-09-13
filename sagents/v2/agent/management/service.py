"""Host-authorized full-package authoring and native execution, without training."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import time
from builtins import BaseExceptionGroup
from functools import wraps
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from sagents.v2.agent.management.contracts import AgentPackageBundle
from sagents.v2.agent.management.store import AgentPackageStore
from sagents.v2.contracts.commands import (
    CancelRun,
    InputItem,
    ReplyInteraction,
    StartRun,
)
from sagents.v2.contracts.interactions import InteractionType
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES, RunState
from sagents.v2.package.manifest import CompositionResolver

# Factories are host-owned. Bundles never contain Python import callbacks.
BuilderFactory = Callable[[AgentPackageBundle, Path, RequestContext], Any]
PackageAuthorizer = Callable[[str, AgentPackageBundle, RequestContext], Awaitable[None]]


def owner_key(context: RequestContext) -> str:
    return hashlib.sha256(
        json.dumps(
            [context.actor.tenant_id, context.actor.principal_id], separators=(",", ":")
        ).encode()
    ).hexdigest()


def managed_operation(method):
    @wraps(method)
    async def guarded(self, *args, **kwargs):
        async with self._idle:
            if self._closed or self._closing or self._draining:
                raise RuntimeError("agent management service is closing or closed")
            self._inflight += 1
        keys = set()
        token = self._operation_keys.set((asyncio.current_task(), keys))
        try:
            return await method(self, *args, **kwargs)
        finally:
            self._operation_keys.reset(token)
            async with self._lock:
                for key in keys:
                    users = self._application_users[key] - 1
                    if users:
                        self._application_users[key] = users
                    else:
                        self._application_users.pop(key)
                    if key in self._applications:
                        self._last_used[key] = time.monotonic()
            async with self._idle:
                self._inflight -= 1
                self._idle.notify_all()

    return guarded


class AgentManagementService:
    """Manage immutable packages for each tenant/principal.

    The authorizer must enforce the host's model, credential, plugin, tool and
    budget grants. It runs before building/importing anything and again before
    execution. The factory supplies fresh Builders and explicit sandbox bindings.
    Caller-selected package settings cannot replace these host-owned callbacks.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        builder_factory: BuilderFactory,
        authorize: PackageAuthorizer,
        inventory: tuple[dict, ...] = (),
        max_applications: int = 32,
        max_concurrent_builds: int = 4,
        model_budget=None,
        job_runtime=None,
        allow_source_plugins: bool = False,
        require_readiness: bool = False,
        auto_release_idle_seconds: float | None = 300,
    ):
        if max_applications < 1:
            raise ValueError("max_applications must be positive")
        if max_concurrent_builds < 1:
            raise ValueError("max_concurrent_builds must be positive")
        if auto_release_idle_seconds is not None and (
            not 0 <= auto_release_idle_seconds < float("inf")
        ):
            raise ValueError("automatic idle age must be finite and nonnegative")
        self.auto_release_idle_seconds = auto_release_idle_seconds
        self._operation_keys = ContextVar("managed_application_keys", default=None)
        self._application_users = {}
        self.root = Path(root).resolve()
        self.store = AgentPackageStore(self.root / "inventory.sqlite3")
        self.builder_factory = builder_factory
        self.authorize = authorize
        self.inventory = inventory
        self.max_applications = max_applications
        self.model_budget = model_budget
        self.job_runtime = job_runtime
        self.allow_source_plugins = allow_source_plugins
        self.require_readiness = require_readiness
        self._last_used = {}
        self._applications: dict[tuple[str, str, str], Any] = {}
        self._application_builds: dict[tuple[str, str, str], asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._build_slots = asyncio.Semaphore(max_concurrent_builds)
        self._save_locks: dict[tuple[str, str, str], tuple[asyncio.Lock, int]] = {}
        self._closed = False
        self._draining = False
        self._validation_cleanup = []
        self._closing = False
        self._idle = asyncio.Condition()
        self._inflight = 0

    def schema(self):
        from sagents.v2.runtime.extensions import ExtensionDescriptor
        from sagents.v2.flow import FlowNodeContext, FlowNodeResult

        return {
            "bundle_schema": AgentPackageBundle.model_json_schema(),
            "extension_schema": ExtensionDescriptor.model_json_schema(),
            "flow_node_input_schema": FlowNodeContext.model_json_schema(),
            "flow_node_output_schema": FlowNodeResult.model_json_schema(),
            "extensions": self.inventory,
            "versioning": "Immutable package id/version; edits and forks save new versions.",
            "activation": "Availability only; not a quality certification.",
            "resources": "Instruction paths resolve from files. Other resources require host bindings. validate(readiness=true) discovers declared tools and skills without executing them.",
            "requires_resource_readiness": self.require_readiness,
            "source_plugins_enabled": self.allow_source_plugins,
            "source_plugin_contract": "extensions/<plugin_id>.py exports registration: ExtensionRegistration; requires explicit host load_source_plugin authorization",
        }

    @managed_operation
    async def validate(
        self,
        bundle: AgentPackageBundle,
        context: RequestContext,
        *,
        readiness: bool = False,
    ):
        bundle = AgentPackageBundle.model_validate(bundle.model_dump(mode="json"))
        return await self._validate(bundle, context, readiness=readiness)

    async def _validate(self, bundle, context, *, readiness=False):
        readiness = readiness or self.require_readiness
        await self.authorize("validate", bundle, context)
        resolved = CompositionResolver().resolve(bundle.resolved_manifest())
        reports = {}
        # Build all agents: validating one entrypoint must not hide a broken member.
        for agent_id in resolved.agents:
            async with self._build_slots:
                task = asyncio.create_task(
                    self._validate_agent(bundle, agent_id, context, readiness=readiness)
                )
                try:
                    reports[agent_id] = await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
        if self.require_readiness and not all(
            report and report["ready"] for report in reports.values()
        ):
            raise ValueError(f"package resources are not ready: {json.dumps(reports)}")
        return {
            "readiness": (
                {
                    "ready": all(
                        report and report["ready"] for report in reports.values()
                    ),
                    "agents": reports,
                }
                if readiness
                else None
            ),
            "valid": True,
            "ref": bundle.content_hash,
            "agents": list(resolved.agents),
            "flows": list(bundle.manifest.flows),
            "validation": "schema, composition and provider initialization; no quality evaluation",
        }

    async def _validate_agent(self, bundle, agent_id, context, *, readiness=False):
        directory = tempfile.TemporaryDirectory(prefix="validate-", dir=self.root)
        try:
            app = await self._build_unbounded(
                bundle,
                agent_id,
                context,
                root=Path(directory.name),
                readiness=readiness,
            )
        except BaseException:
            directory.cleanup()
            raise
        try:
            await app.close()
            directory.cleanup()
        except BaseException:
            # Keep both the instance and its files until cleanup really succeeds.
            self._validation_cleanup.append((app, directory))
            self._draining = True
            raise

        return getattr(app, "resource_readiness", None)

    @staticmethod
    async def _close_validation(app, directory):
        await app.close()
        directory.cleanup()

    @managed_operation
    async def save(self, bundle: AgentPackageBundle, context: RequestContext):
        # Frozen Pydantic models can still contain caller-mutable dicts.
        bundle = AgentPackageBundle.model_validate(bundle.model_dump(mode="json"))
        await self.authorize("save", bundle, context)
        owner = owner_key(context)
        metadata = bundle.manifest.metadata
        async with self._serialize_save((owner, metadata.id, metadata.version)):
            existing = await self.store.version_ref(
                owner, metadata.id, metadata.version
            )
            if existing is not None:
                if existing != bundle.content_hash:
                    raise ValueError(
                        "package version is immutable; choose a new version"
                    )
                await self.authorize("validate", bundle, context)
                if self.require_readiness:
                    report = await self._validate(bundle, context, readiness=True)
                    return {**report, "reused": True}
                return {
                    "valid": True,
                    "ref": existing,
                    "agents": list(bundle.manifest.agents),
                    "flows": list(bundle.manifest.flows),
                    "validation": "previously saved immutable version; provider initialization not repeated",
                    "reused": True,
                }
            report = await self._validate(bundle, context)
            await self.store.save(owner, bundle)
            return {**report, "reused": False}

    @asynccontextmanager
    async def _serialize_save(self, key):
        async with self._lock:
            lock, users = self._save_locks.get(key, (asyncio.Lock(), 0))
            self._save_locks[key] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            async with self._lock:
                _, users = self._save_locks[key]
                if users == 1:
                    del self._save_locks[key]
                else:
                    self._save_locks[key] = (lock, users - 1)

    async def get(self, ref: str, context: RequestContext):
        return await self.store.get(owner_key(context), ref)

    async def list(self, context: RequestContext, *, limit=50, offset=0):
        return await self.store.list(owner_key(context), limit=limit, offset=offset)

    async def fork(
        self,
        ref: str,
        package_id: str,
        version: str,
        context: RequestContext,
        *,
        replacement: dict | None = None,
    ):
        original = await self.get(ref, context)
        data = original.model_dump(mode="json") if replacement is None else replacement
        data = json.loads(json.dumps(data))
        data["manifest"]["metadata"].update(id=package_id, version=version)
        return await self.save(AgentPackageBundle.model_validate(data), context)

    @managed_operation
    async def activate(
        self, ref: str, expected_ref: str | None, context: RequestContext
    ):
        bundle = await self.get(ref, context)
        await self.authorize("activate", bundle, context)
        return await self.store.activate(owner_key(context), ref, expected_ref)

    async def _build(self, bundle, agent_id, context, *, root=None):
        async with self._build_slots:
            return await self._build_unbounded(bundle, agent_id, context, root=root)

    async def _build_unbounded(
        self, bundle, agent_id, context, *, root=None, readiness=False
    ):
        if self._closed:
            raise RuntimeError("agent management service is closed")
        # Agent identifiers need not be filesystem-safe; never use them as paths.
        identity = hashlib.sha256(agent_id.encode()).hexdigest()
        root = (
            root
            or self.root / "runs" / owner_key(context) / bundle.content_hash / identity
        )
        builder = self.builder_factory(bundle.model_copy(deep=True), root, context)
        if hasattr(builder, "__await__"):
            builder = await builder
        if self.model_budget is not None:
            builder.with_model_budget(self.model_budget)
        if self.job_runtime is not None:
            builder.with_job_runtime(self.job_runtime)
        if readiness:
            builder.with_readiness_check()
        sources = [(declaration, bundle.files[f"extensions/{declaration.id}.py"])
                   for declaration in bundle.manifest.plugins
                   if f"extensions/{declaration.id}.py" in bundle.files]
        scope = None
        if sources:
            if not self.allow_source_plugins:
                raise ValueError("source plugins require explicit host opt-in")
            if bundle.manifest.runtime.plugin_trust_policy == "built_in_only":
                raise ValueError("built_in_only policy does not allow source plugins")
            for declaration, _ in sources:
                if builder.extensions.contains(declaration.id):
                    raise ValueError("source plugins cannot replace an already registered extension")
            await self.authorize("load_source_plugin", bundle, context)
            from sagents.v2.agent.management.source_plugins import SourcePluginScope
            scope = SourcePluginScope()
        try:
            if scope is not None:
                # Keep imports off the event loop, and settle an owned load even
                # if the caller leaves before it completes.
                for declaration, source in sources:
                    task = asyncio.create_task(asyncio.to_thread(scope.load, declaration, source))
                    try:
                        registration = await asyncio.shield(task)
                    except asyncio.CancelledError:
                        await task
                        raise
                    builder.register(registration)
            app = await builder.build(
                bundle.resolved_manifest(),
                tenant_id=context.actor.tenant_id,
                agent_id=agent_id,
            )
            if scope is not None:
                await app.adopt_resource(scope, close_after_existing=True)
            return app
        except BaseException:
            if scope is not None:
                await scope.close()
            raise

    def _lease_application(self, key):
        # Called under _lock. Context propagated into child tasks must not let
        # those tasks extend an unrelated caller's lease.
        operation = self._operation_keys.get()
        if operation is not None and operation[0] is asyncio.current_task():
            keys = operation[1]
            if key not in keys:
                keys.add(key)
                self._application_users[key] = self._application_users.get(key, 0) + 1

    async def _application(self, bundle, agent_id, context):
        if agent_id not in bundle.manifest.agents:
            raise ValueError("agent does not exist in this package version")
        key = (owner_key(context), bundle.content_hash, agent_id)
        async with self._lock:
            if self._closed or (self._draining and not self._closing):
                raise RuntimeError("agent management service is closing or closed")
            if key in self._applications:
                self._lease_application(key)
                self._last_used[key] = time.monotonic()
                return self._applications[key]
            task = self._application_builds.get(key)
            if task is None:
                if (
                    len(self._applications) + len(self._application_builds)
                    >= self.max_applications
                ):
                    if self.auto_release_idle_seconds is not None:
                        await self._release_idle_locked(
                            self.auto_release_idle_seconds, 1
                        )
                    if (
                        len(self._applications) + len(self._application_builds)
                        >= self.max_applications
                    ):
                        raise ValueError(
                            "managed application capacity reached; instances are active, leased or too recent"
                        )
                task = asyncio.create_task(
                    self._build_application(key, bundle, agent_id, context)
                )
                task.add_done_callback(
                    lambda done: None if done.cancelled() else done.exception()
                )
                self._application_builds[key] = task
            self._lease_application(key)
        return await asyncio.shield(task)

    async def _build_application(self, key, bundle, agent_id, context):
        try:
            app = await self._build(bundle, agent_id, context)
            # Save the actual host-selected storage path before admitting Runs.
            entrypoint = getattr(app, "entrypoint", None)
            if entrypoint is not None:
                storage = entrypoint().runtime.session_store
                if getattr(storage, "plugin_id", None) == "sage.session.filesystem":
                    try:
                        await self.store.history_location(*key, root=storage.root)
                    except BaseException:
                        async with self._lock:
                            self._applications[key] = app
                            self._last_used[key] = time.monotonic()
                            self._draining = True
                        raise
            async with self._lock:
                self._applications[key] = app
                self._last_used[key] = time.monotonic()
                # Transfer capacity atomically; never count one instance both
                # as building and as ready while another caller checks limits.
                self._application_builds.pop(key, None)
            return app
        finally:
            async with self._lock:
                self._application_builds.pop(key, None)

    @managed_operation
    async def run(
        self,
        ref: str,
        agent_id: str,
        content: str,
        operation: str,
        context: RequestContext,
        *,
        session_id: str | None = None,
    ):
        if not content.strip() or not operation or len(operation) > 200:
            raise ValueError(
                "content and operation key are required (key <= 200 characters)"
            )
        bundle = await self.get(ref, context)
        await self.authorize("run", bundle, context)
        if agent_id not in bundle.manifest.agents:
            raise ValueError("agent does not exist in this package version")
        owner = owner_key(context)
        if session_id and not await self.store.owns_session(
            owner, ref, agent_id, session_id
        ):
            raise ValueError(
                "session does not belong to this caller, agent and version"
            )
        request = json.dumps(
            {"content": content, "session_id": session_id}, sort_keys=True
        )
        record = await self.store.invocation(owner, operation, ref, agent_id, request)
        if self.require_readiness:
            # Recheck current host resources, even for a cached Application.
            await self._validate(bundle, context, readiness=True)
        app = await self._application(bundle, agent_id, context)
        native = app.entrypoint()
        # Native idempotency survives a crash between admission and handle indexing.
        key = hashlib.sha256(f"{owner}:{operation}".encode()).hexdigest()
        handle = await native.start_run(
            StartRun(
                agent_id=agent_id,
                session_id=session_id,
                input=(InputItem(role="user", content=(TextBlock(text=content),)),),
                resolved_spec_hash=app.composition_hash,
                idempotency_key=f"managed:{key}",
            ),
            context,
        )
        record = await self.store.invocation(
            owner, operation, handle=handle.model_dump(mode="json")
        )
        return {"operation": operation, "ref": ref, **record["handle"]}

    @managed_operation
    async def status(self, operation: str, context: RequestContext):
        record = await self.store.invocation(owner_key(context), operation)
        if record["handle"] is None:
            return {
                "operation": operation,
                "state": "admission_pending",
                "retry": "Repeat the original run call with the same operation key.",
            }
        bundle = await self.get(record["ref"], context)
        await self.authorize("read_run", bundle, context)
        archived = await self.store.terminal_status(owner_key(context), operation)
        if archived is not None:
            return archived
        key = (owner_key(context), record["ref"], record["agent"])
        async with self._lock:
            cold = key not in self._applications and key not in self._application_builds
        if cold:
            location = await self.store.history_location(*key)
            if location is not None:
                from sagents.v2.runtime.session.plugins.filesystem import read_session_history

                view = await read_session_history(location, record["handle"]["session_id"], context)
                if view is not None:
                    run = await view.get_run(record["handle"]["run_id"])
                    if run.state in TERMINAL_RUN_STATES:
                        result = await self._read_status_from_store(operation, record, bundle, view)
                        await self.store.terminal_status(key[0], operation, value=result)
                        return result
        app = await self._application(bundle, record["agent"], context)
        result = await self._read_status(operation, record, bundle, app)
        if result["terminal"]:
            await self.store.terminal_status(
                owner_key(context), operation, value=result
            )
        return result

    async def _read_status(self, operation, record, bundle, app):
        return await self._read_status_from_store(operation, record, bundle, app.entrypoint().runtime.session_store)

    async def _read_status_from_store(self, operation, record, bundle, storage):
        run_id = record["handle"]["run_id"]
        run = await storage.get_run(run_id)
        result = (
            await storage.get_run_result(run_id)
            if run.state in TERMINAL_RUN_STATES
            else None
        )
        flow_results = None
        definition = bundle.manifest.agents[record["agent"]]
        if run.state == RunState.COMPLETED and definition.entrypoint.type == "flow":
            # Completion output is committed beside run.completed; avoid replaying
            # the whole trajectory on every status query.
            events = await storage.read_events(
                run_id, after_sequence=max(0, run.last_run_sequence - 32), limit=32
            )
            for event in events:
                if (
                    event.type == "flow.completed"
                    and event.data.flow_id == definition.entrypoint.flow
                ):
                    flow_results = event.data.output
        interaction = None
        if run.state == RunState.SUSPENDED and run.suspension_id:
            suspension = await storage.get_suspension(
                run.suspension_id
            )
            if suspension.interaction_id:
                interaction = (
                    await storage.get_interaction(
                        suspension.interaction_id
                    )
                ).model_dump(mode="json")
        return {
            "operation": operation,
            "ref": record["ref"],
            "run": run.model_dump(mode="json"),
            "result": result.model_dump(mode="json") if result else None,
            "flow_results": flow_results,
            "interaction": interaction,
            "needs_attention": run.state == RunState.SUSPENDED,
            "terminal": run.state in TERMINAL_RUN_STATES,
        }

    async def _archive_application(self, key, app):
        owner, ref, agent = key
        bundle = None
        after = ""
        while True:
            records = await self.store.unarchived_invocations(
                owner, ref, agent, after=after
            )
            if not records:
                return
            if bundle is None:
                bundle = await self.store.get(owner, ref)
            for record in records:
                result = await self._read_status(
                    record["operation"], record, bundle, app
                )
                if result["terminal"]:
                    await self.store.terminal_status(
                        owner, record["operation"], value=result
                    )
            after = records[-1]["operation"]

    @managed_operation
    async def control(
        self,
        operation: str,
        action: str,
        context: RequestContext,
        *,
        decision: str = "",
        interaction_id: str | None = None,
        payload: dict | None = None,
    ):
        record = await self.store.invocation(owner_key(context), operation)
        if record["handle"] is None:
            raise ValueError("invocation admission is not complete")
        bundle = await self.get(record["ref"], context)
        await self.authorize(action, bundle, context)
        app = await self._application(bundle, record["agent"], context)
        native = app.entrypoint()
        run = await native.runtime.get_run(record["handle"]["run_id"])
        if action == "cancel":
            receipt = await native.runtime.cancel_run(
                CancelRun(
                    run_id=run.run_id,
                    expected_revision=run.revision,
                    idempotency_key=f"managed-cancel:{run.run_id}:{run.revision}",
                ),
                context,
            )
        elif action == "reply":
            if not interaction_id:
                raise ValueError("reply requires interaction_id from the status result")
            owner = owner_key(context)
            request = json.dumps(
                {"decision": decision, "payload": payload or {}}, sort_keys=True
            )
            stored = await self.store.reply_command(
                owner, operation, interaction_id, request
            )
            if stored is None:
                if run.state != RunState.SUSPENDED or not run.suspension_id:
                    raise ValueError("run has no pending question")
                suspension = await native.runtime.session_store.get_suspension(
                    run.suspension_id
                )
                if suspension.interaction_id != interaction_id:
                    raise ValueError("question is stale or does not belong to this run")
                question = await native.runtime.session_store.get_interaction(
                    interaction_id
                )
                if question.interaction_type not in {
                    InteractionType.USER_INPUT,
                    InteractionType.ELICITATION,
                }:
                    raise ValueError(
                        "approvals, credentials and permissions must be resolved by the host"
                    )
                if decision not in question.allowed_decisions:
                    raise ValueError("decision is not allowed for this question")
                command = ReplyInteraction(
                    run_id=run.run_id,
                    expected_revision=run.revision,
                    suspension_id=suspension.suspension_id,
                    interaction_id=interaction_id,
                    expected_suspension_revision=suspension.expected_revision,
                    expected_interaction_revision=question.expected_revision,
                    decision=decision,
                    payload=payload or {},
                    idempotency_key=f"managed-reply:{hashlib.sha256(json.dumps([interaction_id, request, run.revision, suspension.expected_revision, question.expected_revision]).encode()).hexdigest()}",
                )
                stored = await self.store.reply_command(
                    owner,
                    operation,
                    interaction_id,
                    request,
                    command.model_dump(mode="json"),
                )
            receipt = await native.runtime.reply_interaction(
                ReplyInteraction.model_validate(stored), context
            )
            if receipt.error and receipt.error.code in {
                "run.revision_conflict",
                "suspension.revision_conflict",
                "interaction.revision_conflict",
            }:
                # These monotonic revision checks precede acceptance; the rejected
                # command can never succeed. Retry must capture fresh revisions.
                await self.store.discard_stale_reply(
                    owner, operation, interaction_id, request, stored
                )
            if receipt.decision.value != "rejected":
                current = await native.runtime.get_run(run.run_id)
                if current.state == RunState.RESUMING:
                    try:
                        await native.continue_run(run.run_id, context)
                    except ValueError:
                        # Another concurrent retry may already have started it.
                        if (
                            await native.runtime.get_run(run.run_id)
                        ).state == RunState.RESUMING:
                            raise
        else:
            raise ValueError("unknown control action")
        return receipt.model_dump(mode="json")

    def capacity(self):
        """Host diagnostics; not exposed as a cross-tenant model tool."""
        return {
            "applications": len(self._applications),
            "building": len(self._application_builds),
            "limit": self.max_applications,
            "inflight_operations": self._inflight,
            "leased_applications": len(self._application_users),
            "automatic_idle_age": self.auto_release_idle_seconds,
            "draining": self._draining,
            "validation_cleanup_pending": len(self._validation_cleanup),
            "model_calls": self.model_budget.snapshot() if self.model_budget else None,
        }

    async def release_idle(self, *, min_idle_seconds: float = 300, limit: int = 1):
        """Host-only, oldest-first reclamation preserving active operation leases."""
        if not 0 <= min_idle_seconds < float("inf") or limit < 1:
            raise ValueError(
                "idle age must be finite and nonnegative and limit must be positive"
            )
        async with self._idle:
            if self._closed or self._closing or self._draining:
                raise RuntimeError("agent management service is closing or closed")
            async with self._lock:
                released = await self._release_idle_locked(min_idle_seconds, limit)
                return {"released": released, "busy": bool(self._application_users)}

    async def _release_idle_locked(self, min_idle_seconds, limit):
        candidates = sorted(self._applications, key=lambda key: self._last_used[key])
        released = 0
        for key in candidates:
            if released >= limit:
                break
            if self._application_users.get(key, 0):
                continue
            if time.monotonic() - self._last_used[key] < min_idle_seconds:
                continue
            app = self._applications[key]
            entrypoint = getattr(app, "entrypoint", None)
            if entrypoint is None:
                continue
            store = entrypoint().runtime.session_store
            if (
                getattr(store, "capabilities", {}).get("durable_across_process_restart")
                is not True
            ):
                # Closing an in-memory store would destroy same-Session continuation.
                continue
            probe = getattr(store, "has_nonterminal_runs", None)
            if probe is None or await probe():
                continue
            await self._archive_application(key, app)
            try:
                await app.close()
            except BaseException:
                self._draining = True
                raise
            self._applications.pop(key)
            self._last_used.pop(key)
            released += 1
        return released

    async def close(self):
        async with self._idle:
            while self._closing:
                await self._idle.wait()
            if self._closed:
                return
            self._closing = True
            self._draining = True
        try:
            async with self._idle:
                while self._inflight:
                    await self._idle.wait()
            # A cancelled caller may have left a shared build in progress.
            async with self._lock:
                builds = list(self._application_builds.values())
            await asyncio.shield(asyncio.gather(*builds, return_exceptions=True))
            async with self._lock:
                applications = list(self._applications.items())
                archive_results = await asyncio.gather(
                    *(self._archive_application(key, app) for key, app in applications),
                    return_exceptions=True,
                )
                # An archive failure must never skip releasing live resources.
                results = await asyncio.gather(
                    *(app.close() for _, app in applications), return_exceptions=True
                )
                for (key, _), result in zip(applications, results, strict=True):
                    if not isinstance(result, BaseException):
                        self._applications.pop(key, None)
                        self._last_used.pop(key, None)
                pending = list(self._validation_cleanup)
                cleanup_results = await asyncio.gather(
                    *(
                        self._close_validation(app, directory)
                        for app, directory in pending
                    ),
                    return_exceptions=True,
                )
                self._validation_cleanup = [
                    item
                    for item, result in zip(pending, cleanup_results, strict=True)
                    if isinstance(result, BaseException)
                ]
                errors = [
                    result
                    for result in [*archive_results, *results, *cleanup_results]
                    if isinstance(result, BaseException)
                ]
                if errors:
                    # Retain failed applications so shutdown can be retried.
                    raise BaseExceptionGroup(
                        "managed application shutdown failures", errors
                    )
                self._closed = True
        finally:
            async with self._idle:
                self._closing = False
                self._idle.notify_all()
