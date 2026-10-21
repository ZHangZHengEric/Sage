"""Offline, executable agent-creates-agent example (Python 3.12+).

Run from the repository: python3.12 -m examples.v2.agent_management
Uses scripted model responses to demonstrate the runtime, not model intelligence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any

from sagents.v2.composition.loaded_agents import ApplicationEntrypoint

from sagents.v2 import ApplicationConfiguration
from examples.v2.host.registrations import provided, runtime_for

import asyncio
import json
import tempfile
from pathlib import Path

from sagents.v2 import (
    AgentManagementService,
    AgentPackageBundle,
    SAgentBuilder,
    StartRun,
)
from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.contracts.commands import InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.package.manifest import SageManifest
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)


def step(text="", *, name=None, arguments=None):
    calls = (
        ()
        if name is None
        else (ModelToolCall(tool_call_id=name, name=name, arguments=cast('dict[str, Any]', arguments)),)
    )
    return ScriptedModelStep(
        events=(
            ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id=name or "done",
                    text=text,
                    tool_calls=calls,
                    finish_reason="tool_calls" if calls else "stop",
                ),
            ),
        )
    )


async def demo(root: Path):
    context = RequestContext(
        actor=ActorRef(principal_id="demo", principal_type=PrincipalType.USER)
    )
    child = BuiltinPackageFactory.create(
        "assistant", package_id="demo.expert",
    ).model_dump(mode="json")
    child["agents"]["assistant"].update(
        instructions={"inline": "Convert distances accurately. Verify units."},
        tools=[],
        budgets={"max_steps": 4, "total_tokens": 12000},
    )
    bundle = AgentPackageBundle(manifest=SageManifest.model_validate(child))

    async def authorize(action, package, ctx):
        # This offline demo permits only a fixed package and never loads plugins.
        # A real host replaces this with its tool/model/credential/budget policy.
        if ctx.actor.principal_id != "demo" or package != bundle:
            raise PermissionError("package is outside this demo's grant")

    def builder_factory(package, session_root, ctx):
        return (
            ApplicationConfiguration((provided('example.model-provider', lambda context, deps, value=ScriptedModelProvider((step('2 km = 2000 m'),)): value, 'model.provider'),), runtime_for(session_root, package.manifest.runtime, capabilities={'model.provider': {'plugin': 'example.model-provider'}}), {'models': {'primary': {'provider': 'openai-responses', 'model': 'scripted'}}})
        )

    service = AgentManagementService(
        root / "managed", builder_factory=builder_factory, authorize=authorize
    )
    parent_data = BuiltinPackageFactory.create(
        "assistant", package_id="demo.parent",
    ).model_dump(mode="json")
    parent_data["agents"]["assistant"]["tools"] = [
        "agent_package_save",
        "agent_package_run",
    ]
    parent_model = ScriptedModelProvider(
        (
            step(
                name="agent_package_save",
                arguments={"bundle": bundle.model_dump(mode="json")},
            ),
            step(
                name="agent_package_run",
                arguments={
                    "ref": bundle.content_hash,
                    "agent_id": "assistant",
                    "content": "Convert 2 km to meters",
                    "operation": "demo-conversion",
                },
            ),
            step("Expert created and task started."),
        )
    )
    configuration = ApplicationConfiguration((provided('example.model-provider', lambda context, deps, value=parent_model: value, 'model.provider'), provided('example.agent-management', lambda context, deps, value=service: value, 'agent.management'), provided('example.agent-tool-policy', lambda context, deps, value=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE): value, 'agent.tool-policy'),), runtime_for(root / 'parent', SageManifest.model_validate(parent_data).runtime, capabilities={'model.provider': {'plugin': 'example.model-provider'}, 'agent.management': {'plugin': 'example.agent-management'}, 'agent.tool-policy': {'plugin': 'example.agent-tool-policy'}}), {'models': {'primary': {'provider': 'openai-responses', 'model': 'scripted'}}})
    builder = SAgentBuilder()
    for registration in configuration.registrations:
        builder.register(registration)
    app = await builder.build(runtime=configuration.runtime, models=configuration.models)
    try:
        agent = await app.load_agent(SageManifest.model_validate(parent_data))
        stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(
            StartRun(
                agent_id=agent.id,
                input=(
                    InputItem(
                        role="user",
                        content=(
                            TextBlock(text="Create a conversion expert and use it."),
                        ),
                    ),
                ),
                resolved_spec_hash=agent.composition_hash,
                idempotency_key="demo-parent",
            ),
            context,
            agent=agent,
        )
        await stream.wait()
        await stream.detach()
        async with asyncio.timeout(10):
            while True:
                result = await service.status("demo-conversion", context)
                if result["terminal"] or result["needs_attention"]:
                    break
                await asyncio.sleep(0.01)
        print(
            json.dumps(
                {"packages": await service.list(context), "result": result},
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await app.close()
        await service.close()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sage-agent-management-demo-") as directory:
        asyncio.run(demo(Path(directory)))
