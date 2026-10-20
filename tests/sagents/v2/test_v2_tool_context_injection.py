from contextlib import asynccontextmanager

import pytest

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.agent.policy.tool_policy import DefaultToolPolicy
from sagents.v2.agent.policy.approval_config import ToolApprovalConfig
from sagents.v2.contracts.commands import InputItem, ReplyInteraction, RunConfig, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.run_state import RunState
from sagents.v2.context.system_context import with_session_context
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider, ScriptedModelStep
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.tool.arguments import apply_system_context_overrides
from sagents.v2.tool.contracts import ToolDefinition
from sagents.v2.tool.decorated import DecoratedToolProvider
from sagents.v2.tool.decorators import tool
from sagents.v2.tool.plugins.mcp import McpServerConfig, McpToolPlugin
from sagents.v2.model.contracts import ModelToolCall
from tests.sagents.v2.test_agent_loop_matrix import CONTEXT as BASE_CONTEXT, completed

CONTEXT = BASE_CONTEXT.model_copy(update={"actor": BASE_CONTEXT.actor.model_copy(
    update={"scopes": (*BASE_CONTEXT.actor.scopes, "tool.external_side_effect")},
)})


SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}, "user_id": {"type": "string"}},
    "required": ["query", "user_id"],
    "additionalProperties": False,
}
DEFINITION = ToolDefinition(name="lookup", description="Lookup", input_schema=SCHEMA)


@pytest.mark.parametrize("value", [False, 0, "", [], {}, "host", {"nested": [1]}])
def test_context_overrides_declared_values_including_falsy_values(value):
    result = apply_system_context_overrides(
        DEFINITION, {"query": "model"}, {"system_context": {"query": value}},
    )
    assert result == {"query": value}


@pytest.mark.parametrize("system_context", [None, [], "text", 42, {"query": None}])
def test_missing_or_none_context_preserves_model_arguments(system_context):
    assert apply_system_context_overrides(
        DEFINITION, {"query": "model"}, {"system_context": system_context},
    ) == {"query": "model"}


def test_context_fills_omitted_arguments_without_leaking_or_recursing():
    model = {"query": "model", "payload": {"user_id": "nested-model"}}
    metadata = {"query": "outer-metadata", "system_context": {
        "user_id": "host", "secret": "never-forwarded", "nested": "unused",
    }}
    assert apply_system_context_overrides(DEFINITION, model, metadata) == {
        "query": "model", "user_id": "host", "payload": {"user_id": "nested-model"},
    }
    assert "user_id" not in model
    assert metadata["system_context"]["secret"] == "never-forwarded"


def test_injected_mutable_values_do_not_alias_runtime_context():
    metadata = {"system_context": {"query": {"nested": [1]}}}
    result = apply_system_context_overrides(DEFINITION, {}, metadata)
    result["query"]["nested"].append(2)
    assert metadata["system_context"]["query"] == {"nested": [1]}


class CapturingPolicy(DefaultToolPolicy):
    def __init__(self, *, needs_approval=False):
        super().__init__(
            approval_levels=frozenset(),
            tool_approval=ToolApprovalConfig(default="ask") if needs_approval else None,
        )
        self.arguments = []

    async def decide(self, context):
        self.arguments.append(context.call.arguments.copy())
        return await super().decide(context)


async def prepare_loop(*, adapter, model_arguments, needs_approval=False, system_context=None):
    received = []

    class Tools:
        @tool(name="lookup", input_schema=SCHEMA, requires_approval=needs_approval)
        async def lookup(self, query: str, user_id: str):
            received.append({"query": query, "user_id": user_id})
            return "found"

    class Session:
        async def list_tools(self):
            return {"tools": [{"name": "lookup", "description": "Lookup", "inputSchema": SCHEMA}]}

        async def call_tool(self, name, arguments):
            assert name == "lookup"
            received.append(arguments.copy())
            return {"content": [{"type": "text", "text": "found"}]}

    @asynccontextmanager
    async def session_factory(config):
        yield Session()

    if adapter == "mcp":
        provider = McpToolPlugin(
            (McpServerConfig(name="remote", protocol="streamable_http", url="https://mcp.test"),),
            session_factory=session_factory,
        )
        definitions = await provider.list_tools(run_id="discovery")
        name = definitions[0].name
        catalog = executor = provider
    else:
        provider = DecoratedToolProvider(Tools())
        name = "lookup"
        catalog, executor = provider.catalog, provider.executor
    model = ScriptedModelProvider((
        ScriptedModelStep(events=(completed("", calls=(ModelToolCall(
            tool_call_id="call_1", name=name, arguments=model_arguments,
        ),)),)),
        ScriptedModelStep(events=(completed("done"),)),
    ))
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(StartRun(
        agent_id="test", input=(InputItem(role="user", content=(TextBlock(text="find"),)),),
        config=RunConfig(model_bindings={"primary": "test"}, metadata={
            "system_context": system_context if system_context is not None else {
                "query": "host-query", "user_id": "host-user", "secret": "private",
            },
        }),
        resolved_spec_hash="sha256:test", idempotency_key="start",
    ), CONTEXT)
    policy = CapturingPolicy(needs_approval=needs_approval)
    kwargs = dict(runtime=runtime, model=model, tool_catalog=catalog,
                  tool_executor=executor, tool_policy=policy)
    return runtime, handle, AgentLoopEngine(**kwargs), received, policy, kwargs


@pytest.mark.parametrize("adapter", ["decorated", "mcp"])
@pytest.mark.parametrize("arguments", [{}, {"query": "model-query", "user_id": "model-user"}])
async def test_context_binding_precedes_schema_policy_and_remote_dispatch(adapter, arguments):
    runtime, handle, loop, received, policy, _ = await prepare_loop(
        adapter=adapter, model_arguments=arguments,
    )
    result = await loop.execute(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    expected = {"query": "host-query", "user_id": "host-user"}
    assert received == [expected]
    assert policy.arguments == [expected]
    proposals = [e for e in await runtime.session_store.read_events(handle.run_id)
                 if e.type == "tool.call.proposed"]
    assert len(proposals) == 1
    assert proposals[0].data.arguments == expected


@pytest.mark.parametrize("adapter", ["decorated", "mcp"])
async def test_approval_and_recreated_loop_execute_the_frozen_bound_arguments_once(adapter):
    runtime, handle, loop, received, policy, kwargs = await prepare_loop(
        adapter=adapter, model_arguments={"query": "model"}, needs_approval=True,
    )
    suspended = await loop.execute(handle.run_id, CONTEXT)
    assert suspended.state == RunState.SUSPENDED
    assert received == []
    expected = {"query": "host-query", "user_id": "host-user"}
    assert policy.arguments == [expected]
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    assert interaction.payload["arguments"] == expected
    await runtime.reply_interaction(ReplyInteraction(
        run_id=handle.run_id, suspension_id=suspension.suspension_id,
        interaction_id=interaction.interaction_id, expected_revision=suspended.revision,
        expected_suspension_revision=suspension.expected_revision,
        expected_interaction_revision=interaction.expected_revision,
        decision="approve_once", idempotency_key="approve",
    ), CONTEXT)
    restarted = AgentLoopEngine(**kwargs)
    result = await restarted.resume(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    assert received == [expected]
    assert all(arguments == expected for arguments in policy.arguments)


@pytest.mark.parametrize("adapter", ["decorated", "mcp"])
async def test_invalid_context_value_is_validated_before_tool_side_effect(adapter):
    runtime, handle, loop, received, policy, _ = await prepare_loop(
        adapter=adapter, model_arguments={"query": "model", "user_id": "model"},
        system_context={"query": 123},
    )
    result = await loop.execute(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    assert received == []
    events = await runtime.session_store.read_events(handle.run_id)
    failure = next(e for e in events if e.type == "tool.call.failed")
    assert failure.data.error.code == "tool.arguments_invalid"


@pytest.mark.parametrize("automatic", [False, True])
async def test_official_memory_tool_and_automatic_recall_bind_context(automatic):
    from types import SimpleNamespace
    from sagents.v2.tool.official.memory import MemoryTools

    received = []

    class SessionMemory:
        async def recall(self, **kwargs):
            received.append(kwargs)
            return []

    provider = DecoratedToolProvider(MemoryTools(SimpleNamespace(
        memory_service=None, session_memory_service=SessionMemory(),
    )))
    calls = () if automatic else (ModelToolCall(
        tool_call_id="memory", name="search_memory", arguments={},
    ),)
    steps = [ScriptedModelStep(events=(completed("" if calls else "done", calls=calls),))]
    if calls:
        steps.append(ScriptedModelStep(events=(completed("done"),)))
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(StartRun(
        agent_id="test", input=(InputItem(role="user", content=(TextBlock(text="model-query"),)),),
        config=RunConfig(model_bindings={"primary": "test"}, metadata={"system_context": {
            "query": "host-query", "session_id": "host-session", "top_k": 3,
        }}), resolved_spec_hash="sha256:test", idempotency_key="start",
    ), CONTEXT)
    loop = AgentLoopEngine(
        runtime=runtime, model=ScriptedModelProvider(tuple(steps)),
        tool_catalog=provider.catalog, tool_executor=provider.executor,
        automatic_memory_recall=automatic,
    )
    result = await loop.execute(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    assert len(received) == 1
    assert received[0]["text"] == "host-query"
    assert received[0]["session_id"] == handle.session_id
    assert received[0]["limit"] == 3
    proposals = [e for e in await runtime.session_store.read_events(handle.run_id)
                 if e.type == "tool.call.proposed"]
    assert proposals[0].data.arguments == {
        "query": "host-query", "session_id": handle.session_id, "top_k": 3,
    }


def test_every_builtin_tool_declares_session_id_in_schema_and_signature():
    import inspect
    from sagents.v2.tool import builtin_tool_definitions
    from tests.sagents.v2.tool_fixture import builtin_tool_methods

    definitions = {}
    for definition, method in builtin_tool_methods():
        assert "session_id" in inspect.signature(method).parameters, definition.name
        assert "session_id" in definition.input_schema["properties"], definition.name
        definitions[definition.name] = definition
    assert {tool.name for tool in builtin_tool_definitions()} <= definitions.keys()
    assert "agent_self_configure" in definitions
    assert "target_session_id" in definitions["agent_package_run"].input_schema["properties"]


@pytest.mark.parametrize("configured", [None, {}, {"session_id": None}, {"session_id": ""},
                                         {"session_id": " "}, {"session_id": "host-session", "query": "keep"}])
def test_session_context_uses_run_identity_without_mutating_admitted_command(configured):
    metadata = {"other": "keep"}
    if configured is not None:
        metadata["system_context"] = configured.copy()
    command = StartRun(
        agent_id="test", input=(InputItem(role="user", content=(TextBlock(text="read"),)),),
        config=RunConfig(metadata=metadata),
        resolved_spec_hash="sha256:test", idempotency_key="start",
    )
    admitted = command.model_dump(mode="json")

    effective = with_session_context(command, "actual-session")

    assert effective.config.metadata == {
        **metadata, "system_context": {**(configured or {}), "session_id": "actual-session"},
    }
    assert command.model_dump(mode="json") == admitted


# Exercise each adapter with both a new and a forked Session. Configuration
# normalization is covered above, without repeating the entire Agent loop.
@pytest.mark.parametrize("configured,fork,adapter", [
    pytest.param(None, False, "official", id="official-new-missing"),
    pytest.param({"session_id": "host-session"}, True, "official", id="official-fork-override"),
    pytest.param({"session_id": "host-session"}, False, "mcp", id="mcp-new-override"),
    pytest.param(None, True, "mcp", id="mcp-fork-missing"),
])
async def test_missing_session_context_uses_real_run_session_in_prompt_and_tool(configured, fork, adapter):
    from sagents.v2.context import DefaultContextAssembler
    from sagents.v2.context.runtime_metadata import RunMetadataContextProvider
    from sagents.v2.contracts.run_state import SessionConcurrencyMode

    received = []

    from types import SimpleNamespace
    from sagents.v2.tool.official.planning import PlanningTools

    async def load_todos(invocation, *, session_id):
        received.append(session_id)
        return []

    if adapter == "mcp":
        class Session:
            async def list_tools(self):
                return {"tools": [{"name": "read_session", "inputSchema": {
                    "type": "object", "properties": {"session_id": {"type": "string"}},
                    "required": ["session_id"], "additionalProperties": False,
                }}]}

            async def call_tool(self, name, arguments):
                received.append(arguments["session_id"])
                return {"content": [{"type": "text", "text": "done"}]}

        @asynccontextmanager
        async def factory(config):
            yield Session()

        provider = McpToolPlugin((McpServerConfig(
            name="remote", protocol="streamable_http", url="https://mcp.test",
        ),), session_factory=factory)
        name = (await provider.list_tools(run_id="discovery"))[0].name
        catalog = executor = provider
    else:
        provider = DecoratedToolProvider(PlanningTools(SimpleNamespace(load_todos=load_todos)))
        name = "todo_read"
        catalog, executor = provider.catalog, provider.executor
    runtime = ephemeral_runtime()
    metadata = {} if configured is None else {"system_context": configured}
    command = StartRun(
        agent_id="test", input=(InputItem(role="user", content=(TextBlock(text="read"),)),),
        config=RunConfig(model_bindings={"primary": "test"}, metadata=metadata),
        resolved_spec_hash="sha256:test", idempotency_key="start",
    )
    if fork:
        parent = await runtime.start_run(command.model_copy(update={"idempotency_key": "parent"}), CONTEXT)
        command = command.model_copy(update={
            "session_id": parent.session_id, "session_concurrency_mode": SessionConcurrencyMode.FORK,
        })
    handle = await runtime.start_run(command, CONTEXT)
    if fork:
        assert handle.session_id != parent.session_id
    model = ScriptedModelProvider((
        ScriptedModelStep(events=(completed("", calls=(ModelToolCall(
            tool_call_id="read", name=name, arguments={"session_id": "model-session"},
        ),)),)), ScriptedModelStep(events=(completed("done"),)),
    ))
    loop = AgentLoopEngine(
        runtime=runtime, model=model, tool_catalog=catalog, tool_executor=executor,
        context_assembler=DefaultContextAssembler(providers=(RunMetadataContextProvider(),)),
    )
    result = await loop.execute(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    expected = handle.session_id
    assert received == [expected]
    prompt = "\n".join(block.text for message in model.requests[0].messages
                       for block in message.content if isinstance(block, TextBlock))
    assert f"<session_id>{expected}</session_id>" in prompt
    stored = await runtime.session_store.get_start_command(handle.run_id)
    assert stored.config.metadata == {**metadata, "sagents.memory_identity": {
        "tenant_id": CONTEXT.actor.tenant_id,
        "user_id": CONTEXT.actor.principal_id,
        "workspace_id": "test",
    }}


@pytest.mark.parametrize("target", [None, "target-session"])
async def test_package_run_keeps_target_session_separate_from_system_context(target):
    from types import SimpleNamespace
    from sagents.v2.tool.plugins.agent_management import AgentManagementTools
    from sagents.v2.tool.contracts import ToolCall

    received = []

    async def run(*args, **kwargs):
        received.append(kwargs)
        return {"session_id": kwargs["session_id"] or "new-target-session"}

    provider = DecoratedToolProvider(AgentManagementTools(SimpleNamespace(run=run)))
    definition = await provider.catalog.get_tool("agent_package_run", run_id="run")
    arguments = {"ref": "pkg@1", "agent_id": "worker", "content": "task", "operation": "op"}
    if target:
        arguments["target_session_id"] = target
    bound = apply_system_context_overrides(definition, arguments, {
        "system_context": {"session_id": "caller-session"},
    })
    await provider.executor.execute(ToolCall(
        tool_call_id="call", tool_name="agent_package_run", arguments=bound,
        operation_id="op", idempotency_key="call", owner_run_id="run",
        owner_session_id="caller-session",
    ), CONTEXT)
    assert received == [{"session_id": target}]
    assert bound["session_id"] == "caller-session"
    assert bound.get("target_session_id") == target
    assert "target_session_id" in definition.input_schema["properties"]
