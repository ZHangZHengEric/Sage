"""Run with python -m examples.v2.standard_host; no host execution driver."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys

from sagents.v2 import ActorRef, RequestContext, SAgentBuilder, StartRun
from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.contracts.commands import InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelCapabilities, ModelResponse, ModelStreamEvent, ModelToolCall
from sagents.v2.package.manifest import SageManifest
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.runtime.extensions import CapabilityOffer, ExtensionDescriptor, ExtensionRegistration, ExtensionScope


class DemonstrationModel:
    """A deterministic model plugin; exercises the real tools, sandbox and Teams."""
    async def capabilities(self, binding):
        return ModelCapabilities(supports_streaming=True, supports_tools=True,
                                 supports_parallel_tool_calls=True, supports_reasoning=False,
                                 supports_multimodal_input=False, supports_structured_output=False)

    async def stream(self, request):
        own = [m for m in request.messages if m.role == "tool" and (m.tool_call_id or "").startswith(request.run_id)]
        names = {tool.name for tool in request.tools}
        call = None
        prefix = request.run_id
        if "sys_team_delegate_task" in names:
            if not own:
                # The declared direct roster is provided by Sage, including nested aliases.
                text = "\n".join(str(m.content) for m in request.messages if m.role in {"system", "developer"})
                members = re.findall(r"- ([A-Za-z0-9_.-]+):", text)
                if not members:
                    raise RuntimeError("standard Team roster is missing")
                call = ModelToolCall(tool_call_id=prefix + "_delegate", name="sys_team_delegate_task",
                                     arguments={"tasks": [{"agent_id": members[-1], "content": "Run the media checks."}]})
        else:
            operations = [
                ("file_write", {"file_path": "standard-host.txt", "content": "standard-sdk"}),
                ("execute_shell_command", {"command": "ffmpeg -hide_banner -loglevel error -f lavfi -i color=size=16x16:rate=1 -t 1 -y media.mp4 && python3 -c \"import json,pathlib; from PIL import Image; Image.new('RGB',(16,16)).save('frame.png'); print(json.dumps({'media_bytes':pathlib.Path('media.mp4').stat().st_size}))\"", "block_until_ms": 30000}),
                ("mcp_demo_echo", {"message": "MCP via standard run scope"}),
            ]
            if len(own) < len(operations):
                name, arguments = operations[len(own)]
                if name not in names:
                    raise RuntimeError(f"standard tool is missing: {name}")
                call = ModelToolCall(tool_call_id=prefix + f"_{len(own)}", name=name, arguments=arguments)
        yield ModelStreamEvent(kind="completed", response=ModelResponse(
            response_id=prefix + f"_{len(own)}", text="" if call else "Media checks completed.",
            tool_calls=(call,) if call else (), finish_reason="tool_calls" if call else "stop",
        ))


def registration(plugin_id, capability, factory):
    return ExtensionRegistration(descriptor=ExtensionDescriptor(
        plugin_id=plugin_id, name=plugin_id, version="1.0.0",
        provides=(CapabilityOffer(capability=capability, api_version="2"),),
        supported_scopes=frozenset({ExtensionScope.AGENT}),
        config_schema={"type": "object", "additionalProperties": False},
    ), factory=factory)


def package(name, *, team=False, children=()):
    return SageManifest.model_validate({
        "schema_version": "sage/v2", "kind": "agent-package",
        "metadata": {"id": "example.standard." + name, "version": "1", "name": name},
        "agents": {"main": {"name": name, "mode": "team" if team else "simple",
                            "instructions": {"inline": "Complete the delegated media work using the declared tools."},
                            "models": {"primary": "primary"},
                            "tools": ["sys_team_delegate_task"] if team else ["file_write", "execute_shell_command", "load_skill"],
                            "skills": [] if team else ["media"],
                            "preload_skills": [] if team else ["media"],
                            "subagents": list(children)}},
        "entrypoint": {"agent": "main"},
    })


def runtime_configuration(root, *, isolation_python, command_path, resources):
    return RuntimeConfig.model_validate({"capabilities": {
        "session.store": {"plugin": "sage.session.filesystem", "config": {"root": str(root / "state")}},
        "execution.binding": {"plugin": "sage.execution.binding.local-workspace", "config": {
            "workspace": str(root / "workspace"), "isolation_python": isolation_python,
            "command_path": command_path,
            "read_paths": [str(Path(isolation_python).resolve().parent.parent)],
            "policy": {"filesystem": {"allowed_operations": ["read", "list", "create", "write", "delete", "rename"],
                                      "max_file_bytes": 512 * 1024**2, "max_total_bytes": 8 * 1024**3},
                       "process": {"enabled": True, "allow_shell": True, "allowed_executables": ["bash", "sh", "python3", "ffmpeg"],
                                   "max_wall_time_seconds": 7200, "max_output_bytes": 16 * 1024**2},
                       "resources": {"memory_mb": 2048, "disk_mb": 8192, "require_hard_limits": False}},
        }},
        "model.provider": {"plugin": "example.standard.model"},
        "agent.tool-policy": {"plugin": "example.standard.tool-policy"},
        "tool.catalog": [
            {"plugin": "sage.tool.official"},
            {"plugin": "sage.tool.mcp", "scope": "run", "grant_tools": True, "config": {"servers": [
                {"name": "demo", "protocol": "stdio", "command": isolation_python,
                 "args": ["-I", "-u", str(resources / "mcp_server.py")], "call_timeout_seconds": 7200},
            ]}},
        ],
        "skill.catalog": {"plugin": "sage.skill.filesystem", "config": {"roots": [str(resources / "skills")]}},
        "tool.selection-policy": {"plugin": "sage.tool-selection.direct"},
        "agent.continuation-policy": {"plugin": "sage.agent.continuation.deterministic"},
    }})


async def main(options):
    root = Path(options.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    resources = Path(__file__).resolve().parent
    interpreter = options.isolation_python
    if interpreter is None:
        if getattr(sys, "frozen", False):
            raise ValueError("a frozen host requires --isolation-python pointing to real CPython")
        interpreter = sys.executable
    models = {"models": {"primary": {"provider": "openai-chat-completions", "model": "demonstration"}}}
    runtime = runtime_configuration(root, isolation_python=interpreter,
                                    command_path=options.command_path, resources=resources)
    builder = SAgentBuilder()
    builder.register(registration("example.standard.model", "model.provider", lambda context, deps: DemonstrationModel()))
    builder.register(registration("example.standard.tool-policy", "agent.tool-policy", lambda context, deps: DefaultToolPolicy(
        approval_strategy=ApprovalStrategy.AUTO_APPROVE,
    )))
    app = await builder.build(runtime=runtime, models=models)
    context = RequestContext(actor=ActorRef(principal_id="standard-host-user", principal_type="user", tenant_id="standard-host", scopes=("tool.external_side_effect",)))
    try:
        worker = await app.load_agent(package("worker"))
        group = await app.load_agent(package("group", team=True, children=("worker",)), subagents={"worker": worker})
        agent = await app.load_agent(package("main", team=True, children=("group",)), subagents={"group": group})
        if options.recover:
            run_id = options.recover
            agent = await app.agent_for_run(run_id, context)
            run = await app.service("session.access").get_run(run_id, context)
            if run.state.value == "resuming":
                await (await app.entrypoint().continue_run(run_id, context, agent=agent))
            else:
                from sagents.v2 import EventCursor
                async for event in app.service("session.access").subscribe_events(EventCursor(run_id=run_id), context):
                    print(event.model_dump_json(), flush=True)
                    if event.type in {"run.completed", "run.failed", "run.cancelled", "run.suspended"}:
                        break
        else:
            command = StartRun(agent_id=agent.id, resolved_spec_hash=agent.composition_hash,
                               input=(InputItem(role="user", content=(TextBlock(text="Run all standard media checks."),)),),
                               idempotency_key=options.key)
            stream = await app.entrypoint().run_stream(command, context, agent=agent)
            run_id = stream.handle.run_id
            print(json.dumps({"run_id": run_id}), flush=True)
            async for event in stream.events:
                print(event.model_dump_json(), flush=True)
            result = await stream.wait()
            if result.state.value != "completed":
                raise RuntimeError(f"standard host ended in {result.state.value}")
        configuration = await app.execution_configuration(run_id, context)
        access = app.service("session.access")
        root_run = await access.get_run(run_id, context)
        descendants = await access.list_descendant_sessions(root_run.session_id, context)
        runs = [root_run]
        for session in descendants:
            runs.extend(await access.list_session_runs(session.session_id, context))
        if len(runs) != 3 or any(run.state.value != "completed" for run in runs):
            raise RuntimeError("nested Team acceptance failed")
        successful_tools = set()
        sandbox_ids = set()
        for run in runs:
            facts = await app.execution_diagnostics(run.run_id, context)
            if facts["sandbox"]["owner_run_id"] != run.run_id:
                raise RuntimeError("Run lease ownership acceptance failed")
            sandbox_ids.add(facts["sandbox"]["sandbox_id"])
            for event in await access.read_events(run.run_id, context):
                if event.type == "tool.call.succeeded":
                    successful_tools.add(event.data.tool_name)
        if len(sandbox_ids) != 1:
            raise RuntimeError("shared sandbox acceptance failed")
        if not {"file_write", "execute_shell_command", "mcp_demo_echo", "sys_team_delegate_task"} <= successful_tools:
            raise RuntimeError(f"tool acceptance incomplete: {successful_tools}")
        workspace = Path(configuration.workspace_root)
        if (workspace / "standard-host.txt").read_text() != "standard-sdk":
            raise RuntimeError("file tool acceptance failed")
        if not (workspace / "frame.png").stat().st_size:
            raise RuntimeError("Python media dependency acceptance failed")
        if not (workspace / "media.mp4").stat().st_size:
            raise RuntimeError("media acceptance failed")
        print(json.dumps({"configuration_id": configuration.configuration_id,
                          "diagnostics": await app.execution_diagnostics(run_id, context)}), flush=True)
    finally:
        await app.close()


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".runtime/standard-v2-host")
    parser.add_argument("--key", default="media-smoke")
    parser.add_argument("--recover")
    parser.add_argument("--isolation-python")
    parser.add_argument("--command-path", default=os.environ.get("PATH", os.defpath))
    asyncio.run(main(parser.parse_args()))


if __name__ == "__main__":
    cli()
