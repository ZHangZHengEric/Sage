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

from sagents.v2.agent.management import AgentPackageBundle
from sagents.v2.agent.management.service import BuilderFactory, PackageAuthorizer
from sagents.v2.contracts.commands import InputItem, StartRun, RunConfig
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.optimization.contracts import OptimizationObservation


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
    ):
        if max_evidence_events < 1 or max_evidence_bytes < 1:
            raise ValueError("evidence limits must be positive")
        self.max_evidence_events = max_evidence_events
        self.max_evidence_bytes = max_evidence_bytes
        self.builder_factory = builder_factory
        self.authorize = authorize
        self.run_metadata = run_metadata
        self.root = Path(root) if root is not None else None
        if self.root is not None:
            self.root.mkdir(parents=True, exist_ok=True)

    async def run(self, package, agent_id, content, context):
        async with self.conversation(package, agent_id, context) as session:
            return await session.send(content)

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
            builder = self.builder_factory(package.model_copy(deep=True), root, context)
            if inspect.isawaitable(builder):
                builder = await builder
            app = await builder.build(runtime=manifest.runtime, tenant_id=context.actor.tenant_id)
            try:
                from sagents.v2.agent.management.loading import load_bundle_agents
                await load_bundle_agents(app, package)
            except BaseException:
                await app.close()
                raise
            try:
                yield _NativeConversation(
                    self, app, package, agent_id, context, started
                )
            finally:
                await app.close()

    async def _send(
        self, app, agent_id, content, context, session_id, started, package
    ):
        stream = None
        try:
            agent = app.entrypoint()
            loaded = next(a for a in app.loaded_agents if a.package_id == package.manifest.metadata.id)
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
            cursor = 0
            scanned = 0
            size = 0
            truncated = False
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
                    if data.kind not in {"tool", "flow", "artifact"} and not (
                        data.kind == "item"
                        and data.item is not None
                        and data.item.data.kind in {"tool_call", "tool_result"}
                    ):
                        continue
                    value = event.model_dump(mode="json")
                    length = len(json.dumps(value, ensure_ascii=False).encode())
                    if size + length > self.max_evidence_bytes:
                        truncated = True
                        continue
                    size += length
                    events.append(value)
            payload["runtime_events"] = events
            payload["runtime_events_truncated"] = (
                truncated or cursor < snapshot.last_run_sequence
            )
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
    def __init__(self, runner, app, package, agent_id, context, started):
        self.runner, self.app, self.package = runner, app, package
        self.agent_id, self.context = agent_id, context
        self.session_id = None
        self.started = started

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
        )
        self.session_id = observed.evidence["session_id"]
        self.started = time.monotonic()
        return observed
