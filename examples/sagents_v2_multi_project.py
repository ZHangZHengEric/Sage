"""Offline, single-process concurrency example using only public Core APIs.

Run: .venv/bin/python -m examples.sagents_v2_multi_project
The scripted model and in-process MCP transport need no API keys or network.
The tool router is host application code, not a Desktop service subclass.
"""

import asyncio
import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from sagents.v2 import ActorRef, RequestContext, SAgentBuilder, StartRun
from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.contracts.commands import CancelRun, InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import PrincipalType
from sagents.v2.model import (
    ModelCapabilities,
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
)
from sagents.v2.model.contracts import ModelToolCall
from sagents.v2.package.manifest import SageManifestLoader
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.tool import McpServerConfig, McpToolPlugin


MANIFEST = """
schema_version: sage/v2
kind: application
metadata: {id: example.multi-project, version: 1.0.0, name: Multi-project}
models:
  route_a: {provider: openai-compatible, model: model-a}
  route_b: {provider: openai-compatible, model: model-b}
agents:
  main:
    name: Shared agent
    instructions: {inline: "Write only within your bound project."}
    models: {primary: route_a, alternate: route_b}
    tools: [mcp_project_write]
runtime:
  capabilities:
    execution.scheduler:
      plugin: sage.scheduler.ephemeral
      config: {max_concurrent_runs: 4, max_concurrent_runs_per_tenant: 4}
entrypoint: {agent: main}
"""


class ProjectTools:
    """Route by durable Run identity; never set process cwd or environment."""

    def __init__(self, store):
        self.store = store
        self.plugins = {}
        self.operations = {}
        self.writes = []

    async def plugin(self, run_id):
        command = await self.store.get_start_command(run_id)
        while command.parent_run_id:
            command = await self.store.get_start_command(command.parent_run_id)
        spec = command.config.metadata["project_binding"]
        if run_id not in self.plugins:
            directory = Path(spec["directory"])
            session = (await self.store.get_run(run_id)).session_id
            owner = self

            class Session:
                async def list_tools(self):
                    return {
                        "tools": [
                            {
                                "name": "write",
                                "description": "Write the next project artifact",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "round": {
                                            "type": "integer",
                                            "minimum": 0,
                                            "maximum": 2,
                                        }
                                    },
                                    "required": ["round"],
                                    "additionalProperties": False,
                                },
                            }
                        ]
                    }

                async def call_tool(self, name, arguments):
                    assert name == "write"
                    directory.mkdir(parents=True, exist_ok=True)
                    path = directory / f"{session}-{arguments['round']}.json"
                    value = {
                        "project": spec["project"],
                        "session": session,
                        "run": run_id,
                    }
                    path.write_text(json.dumps(value), encoding="utf-8")
                    owner.writes.append(value)
                    await asyncio.sleep(0)  # Allow other Runs to interleave.
                    return {"content": [{"type": "text", "text": str(path)}]}

            @asynccontextmanager
            async def transport(config):
                assert config.env["PROJECT_DIRECTORY"] == str(directory)
                yield Session()

            self.plugins[run_id] = McpToolPlugin(
                (
                    McpServerConfig(
                        name="project",
                        protocol="stdio",
                        command="offline-example",
                        env={"PROJECT_DIRECTORY": str(directory)},
                    ),
                ),
                session_factory=transport,
            )
        return self.plugins[run_id]

    async def list_tools(self, *, run_id):
        return await (await self.plugin(run_id)).list_tools(run_id=run_id)

    async def get_tool(self, name, *, run_id):
        return await (await self.plugin(run_id)).get_tool(name, run_id=run_id)

    async def execute(self, call, context):
        plugin = await self.plugin(call.owner_run_id)
        self.operations[call.operation_id] = plugin
        return await plugin.execute(call, context)

    async def reconcile(self, operation_id, context):
        return await self.operations[operation_id].reconcile(operation_id, context)

    async def release_run(self, run_id):
        plugin = self.plugins.pop(run_id, None)
        if plugin is not None:
            await plugin.release_run(run_id)
            self.operations = {
                key: value
                for key, value in self.operations.items()
                if value is not plugin
            }


class ConcurrentModel:
    def __init__(self, store):
        self.store = store
        self.entered = set()
        self.all_started = asyncio.Event()
        self.release = asyncio.Event()
        self.requests = []

    async def capabilities(self, model_binding):
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_parallel_tool_calls=True,
            supports_reasoning=False,
            supports_multimodal_input=False,
            supports_structured_output=False,
        )

    async def stream(self, request):
        command = await self.store.get_start_command(request.run_id)
        self.requests.append(request)
        assert request.model_binding == command.config.model_bindings["primary"]
        marker = command.config.metadata["system_context"]["project_marker"]
        assert marker in str([message.model_dump() for message in request.messages])
        self.entered.add(request.run_id)
        if len(self.entered) == 3:
            self.all_started.set()
        await self.release.wait()
        round_number = sum(message.role == "tool" for message in request.messages)
        calls = (
            ()
            if round_number >= 3
            else (
                ModelToolCall(
                    tool_call_id=f"call_{request.run_id}_{round_number}",
                    name="mcp_project_write",
                    arguments={"round": round_number},
                ),
            )
        )
        yield ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(
                response_id=request.request_id,
                text="done" if not calls else "",
                tool_calls=calls,
                finish_reason="tool_calls" if calls else "stop",
            ),
        )


async def run_example(root: Path, *, cancel_first: bool = False):
    store = FilesystemSessionStore(root / "sessions")  # Host-owned, opened once.
    model = ConcurrentModel(store)
    tools = ProjectTools(store)
    manifest = SageManifestLoader().loads(MANIFEST)
    resolved = CompositionResolver().resolve(manifest)
    app = await (
        SAgentBuilder()
        .with_defaults(session_root=root / "runtime")
        .with_session_store(store)
        .with_model_provider(model)
        .with_tool_provider(tools, tools)
        .with_tool_policy(
            DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)
        )
        .build(manifest)
    )
    streams = []
    try:
        context = RequestContext(
            actor=ActorRef(
                principal_id="example-user",
                principal_type=PrincipalType.USER,
                tenant_id="example",
                scopes=("tool.external_side_effect",),
            )
        )
        for project, session in (("a", "a1"), ("b", "b1"), ("a", "a2")):
            config = CompositionResolver().resolve_run_config(
                resolved,
                "main",
                model_bindings={"primary": f"route_{project}"},
                metadata={
                    "system_context": {
                        "project_marker": f"project-{project}-{session}"
                    },
                    "project_binding": {
                        "project": project,
                        "directory": str(root / "projects" / project),
                    },
                },
            )
            streams.append(
                await app.entrypoint().run_stream(
                    StartRun(
                        agent_id="main",
                        session_id=session,
                        config=config,
                        input=(
                            InputItem(
                                role="user",
                                content=(TextBlock(text="Write three artifacts"),),
                            ),
                        ),
                        idempotency_key=session,
                        resolved_spec_hash=app.composition_hash,
                    ),
                    context,
                )
            )
        # All three must enter the model before any is allowed to finish.
        await asyncio.wait_for(model.all_started.wait(), timeout=10)
        if cancel_first:
            target = await app.service("session.access").get_run(
                streams[0].handle.run_id, context
            )
            await app.entrypoint().runtime.cancel_run(
                CancelRun(
                    run_id=target.run_id,
                    expected_revision=target.revision,
                    idempotency_key="cancel-a1",
                ),
                context,
            )
        model.release.set()
        results = await asyncio.wait_for(
            asyncio.gather(*(stream.wait() for stream in streams)), timeout=20
        )
        assert [result.state.value for result in results] == (
            ["cancelled", "completed", "completed"]
            if cancel_first
            else ["completed"] * 3
        )
        assert len(tools.writes) == (6 if cancel_first else 9)
        for project, session in (("a", "a1"), ("b", "b1"), ("a", "a2")):
            if cancel_first and session == "a1":
                assert not list((root / "projects" / "a").glob("a1-*.json"))
                continue
            for index in range(3):
                artifact = json.loads(
                    (
                        root / "projects" / project / f"{session}-{index}.json"
                    ).read_text()
                )
                assert artifact["project"] == project and artifact["session"] == session
        return {
            "sessions": len(results),
            "concurrent_runs": len(model.entered),
            "artifacts": len(tools.writes),
        }
    finally:
        model.release.set()
        await app.close()
        for stream in streams:
            await stream.detach()
            await tools.release_run(stream.handle.run_id)
        await store.close()  # Borrowed store is closed by the host, after app.


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sage-multi-project-") as directory:
        print(asyncio.run(run_example(Path(directory))))
