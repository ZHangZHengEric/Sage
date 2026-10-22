"""Host-bound fresh-application runner; never touches the active package registry."""

from __future__ import annotations

import inspect
import json
import tempfile
import time
from pathlib import Path
from typing import Protocol
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from uuid import uuid4
from contextvars import ContextVar


from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.agent.management.service import BuilderFactory, PackageAuthorizer
from sagents.v2.contracts.commands import InputItem, StartRun, RunConfig, ReplyInteraction
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.optimization.contracts import OptimizationObservation


# Hosts may use this to pair simulator seeds across independently run packages.
OPTIMIZATION_TRIAL: ContextVar[int] = ContextVar("optimization_trial", default=1)
OPTIMIZATION_CASE: ContextVar[object | None] = ContextVar("optimization_case", default=None)


class OptimizationRunner(Protocol):
    async def run(
        self,
        package: AgentPackageBundle,
        agent_id: str,
        content: str,
        context: RequestContext,
    ) -> OptimizationObservation: ...


class IsolatedOptimizationRunner:
    """Fresh builder, workspace, Application and Session for every invocation.

    The factory supplies frozen model/tool/Skill bindings and an actual sandbox
    or test doubles. A temporary directory alone is NOT an OS sandbox. Bundled
    files are materialized before the factory is called, including Skill files.
    Source plugin code is never imported automatically. The host authorizer must
    enforce credentials, tools, resource grants and total model-call budgets.

    resume_user_input opts a simulated conversation host into replying to explicit
    input-required interactions. Approval and permission suspensions remain closed.
    """

    def __init__(
        self,
        *,
        builder_factory: BuilderFactory,
        authorize: PackageAuthorizer,
        root: str | Path | None = None,
        max_evidence_events: int = 500,
        max_evidence_bytes: int = 262144,
        run_metadata=None,
        resume_user_input: bool = False,
    ):
        if max_evidence_events < 1 or max_evidence_bytes < 1:
            raise ValueError("evidence limits must be positive")
        self.max_evidence_events = max_evidence_events
        self.max_evidence_bytes = max_evidence_bytes
        self.builder_factory = builder_factory
        self.authorize = authorize
        self.run_metadata = run_metadata
        self.resume_user_input = resume_user_input
        self.root = Path(root) if root is not None else None
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)

    async def run(self, package, agent_id, content, context):
        async with self.conversation(package, agent_id, context) as session:
            observation = await session.send(content)
            from sagents.v2.optimization.evaluation_files import collect_evaluation_output, compact_evaluation_receipts
            collected = collect_evaluation_output(session.workspace, package, observation)
            return observation.model_copy(update={"evidence": {**(compact_evaluation_receipts(observation.evidence) if collected else observation.evidence), **collected}})

    @asynccontextmanager
    async def conversation(
        self, package, agent_id, context
    ) -> AsyncIterator["_NativeConversation"]:
        package = AgentPackageBundle.model_validate(package.model_dump(mode="json"))
        await self.authorize("optimize_run", package.model_copy(deep=True), context)
        manifest = package.resolved_manifest()
        if agent_id not in manifest.agents:
            raise ValueError("agent does not exist in target package")
        started = time.monotonic()
        with tempfile.TemporaryDirectory(
            prefix="sage-optimize-", dir=self.root
        ) as directory:
            root = Path(directory)
            for name, text in package.files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            configuration = self.builder_factory(package.model_copy(deep=True), root, context)
            if inspect.isawaitable(configuration):
                configuration = await configuration
            from sagents.v2 import ApplicationConfiguration, SAgentBuilder
            if not isinstance(configuration, ApplicationConfiguration):
                raise TypeError("builder_factory must return ApplicationConfiguration")
            builder = SAgentBuilder()
            for registration in configuration.registrations:
                builder.register(registration)
            app = await builder.build(runtime=configuration.runtime, models=configuration.models, tenant_id=context.actor.tenant_id)
            try:
                from sagents.v2.agent.management.loading import load_bundle_agents
                await load_bundle_agents(app, package)
            except BaseException:
                await app.close()
                raise
            try:
                yield _NativeConversation(
                    self, app, package, agent_id, context, started, root
                )
            finally:
                await app.close()

    async def _send(
        self, app, agent_id, content, context, session_id, started, package,
        resume_observation=None,
    ):
        stream = None
        try:
            agent = app.entrypoint()
            loaded = next(a for a in app.loaded_agents if a.package_id == package.manifest.metadata.id)
            after_sequence = 0
            if resume_observation is not None:
                previous = resume_observation.evidence
                current = await agent.runtime.get_run(previous['run_id'])
                suspension = await agent.runtime.session_store.get_suspension(current.suspension_id)
                if suspension.reason.value != 'input_required' or not suspension.interaction_id:
                    raise RuntimeError('Only explicit user-input suspensions can receive simulated replies')
                interaction = await agent.runtime.session_store.get_interaction(suspension.interaction_id)
                if 'submit' not in interaction.allowed_decisions:
                    raise RuntimeError('Only explicit user-input suspensions can receive simulated replies')
                after_sequence = previous['last_run_sequence']
                await agent.runtime.reply_interaction(ReplyInteraction(
                    run_id=current.run_id, suspension_id=suspension.suspension_id,
                    interaction_id=interaction.interaction_id, expected_revision=current.revision,
                    expected_suspension_revision=suspension.expected_revision,
                    expected_interaction_revision=interaction.expected_revision,
                    decision='submit', payload={'text': content},
                    idempotency_key=f'optimization_reply_{uuid4().hex}',
                ), context)
                execution = await agent.continue_run(current.run_id, context, agent=loaded)
                snapshot = await execution
            else:
                stream = await agent.run_stream(
                    StartRun(
                        agent_id=loaded.id,
                        config=RunConfig(
                            metadata=self.run_metadata(package) if self.run_metadata else {}
                        ),
                        session_id=session_id,
                        input=(InputItem(role="user", content=(TextBlock(text=content),)),),
                        resolved_spec_hash=loaded.composition_hash,
                        idempotency_key=f"optimization_{uuid4().hex}",
                    ),
                    context,
                    agent=loaded,
                )
                snapshot = await stream.wait()
            result = (
                await agent.runtime.session_store.get_run_result(snapshot.run_id)
                if snapshot.state
                in {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
                else None
            )
            payload = (
                result.model_dump(mode="json")
                if result
                else snapshot.model_dump(mode="json")
            )
            events = []
            cursor = after_sequence
            scanned = 0
            size = 0
            truncated = False
            boundary_messages = []
            omitted_events = 0
            while (
                cursor < snapshot.last_run_sequence
                and scanned < self.max_evidence_events
            ):
                page = await agent.runtime.session_store.read_events(
                    snapshot.run_id,
                    after_sequence=cursor,
                    limit=min(100, self.max_evidence_events - scanned),
                )
                if not page:
                    break
                for event in page:
                    cursor = event.run_sequence
                    scanned += 1
                    data = event.data
                    if event.type == 'message.completed' and data.kind == 'item' and data.item is not None:
                        item = data.item.data
                        if item.kind == 'message' and item.role == 'assistant' and data.item.visibility == 'public':
                            boundary_messages.append(''.join(b.text for b in item.content if b.kind == 'text'))
                    if data.kind in {"run", "step"} and data.error is not None:
                        payload["error"] = data.error.model_dump(mode="json")
                    if data.kind not in {"tool", "flow", "artifact", "run", "step", "continuation", "interaction", "checkpoint"} and not (
                        data.kind == "item"
                        and data.item is not None
                        and data.item.data.kind in {"tool_call", "tool_result"}
                    ):
                        continue
                    from sagents.v2.optimization.execution_records import compact_execution_event
                    value = compact_execution_event(event.model_dump(mode="json"), payload.get("final_items", []))
                    if value is None:
                        omitted_events += 1
                        continue
                    length = len(json.dumps(value, ensure_ascii=False).encode())
                    if size + length > self.max_evidence_bytes:
                        truncated = True
                        continue
                    size += length
                    events.append(value)
            payload["runtime_events"] = events
            payload["runtime_lifecycle_events_omitted"] = omitted_events
            payload["runtime_events_truncated"] = (
                truncated or cursor < snapshot.last_run_sequence
            )
            if snapshot.state == RunState.SUSPENDED:
                suspension = await agent.runtime.session_store.get_suspension(snapshot.suspension_id)
                payload["suspension"] = suspension.model_dump(mode="json")
            messages = []
            for item in payload.get("final_items", []):
                data = item["data"]
                if data["kind"] == "message" and data["role"] == "assistant":
                    messages.append(
                        "".join(
                            block["text"]
                            for block in data["content"]
                            if block["kind"] == "text"
                        )
                    )
            if self.resume_user_input and snapshot.state == RunState.SUSPENDED:
                suspension = await agent.runtime.session_store.get_suspension(snapshot.suspension_id)
                if suspension.reason.value == 'input_required' and suspension.interaction_id:
                    interaction = await agent.runtime.session_store.get_interaction(suspension.interaction_id)
                    if 'submit' in interaction.allowed_decisions:
                        payload['awaiting_user_input'] = True
                        messages = boundary_messages
                        if not messages and isinstance(interaction.payload.get('prompt'), str):
                            messages = [interaction.payload['prompt']]
            elif resume_observation is not None:
                messages = boundary_messages
            usage = payload.get("usage", {})
            return OptimizationObservation(
                state=snapshot.state.value,
                output="\n".join(messages),
                evidence=payload,
                elapsed_seconds=time.monotonic() - started,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cost=usage.get("cost"),
            )
        finally:
            if stream is not None:
                await stream.detach()


class _NativeConversation:
    def __init__(self, runner, app, package, agent_id, context, started, workspace=None):
        self.workspace = workspace
        self.runner, self.app, self.package = runner, app, package
        self.agent_id, self.context = agent_id, context
        self.session_id = None
        self.started = started
        self.pending_input = None

    async def send(self, content: str) -> OptimizationObservation:
        if self.session_id is not None:
            await self.runner.authorize(
                "optimize_run", self.package.model_copy(deep=True), self.context
            )
        observed = await self.runner._send(
            self.app,
            self.agent_id,
            content,
            self.context,
            self.session_id,
            self.started if self.session_id is None else time.monotonic(),
            self.package.model_copy(deep=True),
            resume_observation=self.pending_input,
        )
        self.pending_input = observed if observed.evidence.get('awaiting_user_input') else None
        self.session_id = observed.evidence["session_id"]
        self.started = time.monotonic()
        return observed
