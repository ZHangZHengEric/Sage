
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    pass

from sagents.v2.composition.loaded_agents import ApplicationEntrypoint

from tests.sagents.v2.sdk_fixture import build_registered_package
from contextlib import asynccontextmanager

from tests.sagents.v2.model_fixture import TEST_MODELS

import pytest

from sagents.v2.agent.policy.approval_config import ToolApprovalConfig
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.package.manifest.root import SageManifest
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep
from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog, InMemoryToolExecutor
from sagents.v2.tool import McpServerConfig, McpToolPlugin, ToolExecutionResult
from sagents.v2.tool.plugins.official import official_tool_definitions
from tests.sagents.v2.test_builder_matrix import _policy_package, _POLICY_USER
from tests.sagents.v2.test_agent_management_matrix import tool_step
from tests.sagents.v2.test_mcp_tool_bridge_matrix import FakeSession


@pytest.mark.parametrize("kind", ["builtin", "mcp"])
@pytest.mark.parametrize("ask", [False, True])
async def test_restored_package_rules_control_actual_loop_dispatch(tmp_path, kind, ask):
    calls = []
    if kind == "mcp":
        session = FakeSession()

        @asynccontextmanager
        async def factory(_):
            yield session

        plugin = McpToolPlugin(
            (
                McpServerConfig(
                    name="drive", protocol="streamable_http", url="https://mcp.test"
                ),
            ),
            session_factory=factory,
        )
        definition = (await plugin.list_tools(run_id="test"))[0]
        catalog = executor = plugin
        arguments = {"query": "files"}
        calls = session.calls
    else:
        definition = next(
            t for t in official_tool_definitions() if t.name == "file_write"
        )

        async def execute(call, _):
            calls.append(call)
            return ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text="ok"),),
            )

        catalog = InMemoryToolCatalog((definition,))
        executor = InMemoryToolExecutor(
            {definition.name: definition}, {definition.name: execute}
        )
        arguments = {"file_path": "/workspace/test.txt", "content": "hello"}
    package = _policy_package("test.approval-config")
    agent_id = package.entrypoint.agent
    key = definition.approval_key or definition.name
    agent = getattr(package.agents[cast('str', agent_id)], 'model_copy')(
        update={
            "tools": (definition.name,),
            "tool_approval": ToolApprovalConfig(
                default="auto_approve", tools={key: "ask"} if ask else {}
            ),
        }
    )
    package = package.model_copy(update={"agents": {agent_id: agent}})
    package = SageManifest.model_validate_json(package.model_dump_json())
    provider = ScriptedModelProvider(
        (
            tool_step(definition.name, arguments, "call"),
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="hello"),
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="done", text="hello", finish_reason="stop"
                        ),
                    ),
                )
            ),
        )
    )
    app = (
        await build_registered_package(tmp_path, models=TEST_MODELS, model=provider, tools=(catalog, executor,), package=package)
    )
    actor = _POLICY_USER.actor.model_copy(update={"scopes": definition.required_scopes})
    try:
        stream = await cast(ApplicationEntrypoint, app.entrypoint()).run_stream(
            (StartRun(
                agent_id=cast(str, agent_id),
                input=(InputItem(role="user", content=(TextBlock(text="go"),)),),
                resolved_spec_hash=app.composition_hash,
                idempotency_key="test",
            )).model_copy(update={"agent_id": app.loaded_agents[-1].id, "resolved_spec_hash": app.loaded_agents[-1].composition_hash}),
            _POLICY_USER.model_copy(update={"actor": actor}), agent=app.loaded_agents[-1],
        )
        events = [event.type async for event in stream.events]
        result = await stream.wait()
        assert ("tool.call.awaiting_approval" in events) == ask
        assert len(calls) == (0 if ask else 1)
        assert result.state.value == ("suspended" if ask else "completed")
    finally:
        await app.close()
