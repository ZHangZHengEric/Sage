"""Registered plugins use the same trusted services as standard Agent execution."""
from dataclasses import replace

import asyncio
import pytest

from sagents.v2 import SAgentBuilder
from sagents.v2.agent.policy import DefaultToolPolicy
from sagents.v2.model.contracts import ModelResponse, ModelStreamEvent, ModelToolCall
from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.extensions import (
    CapabilityOffer, ExtensionDependency, ExtensionDescriptor,
    ExtensionRegistration, ExtensionScope,
)
from sagents.v2.tool.decorated import DecoratedToolProvider
from sagents.v2.tool.decorators import tool
from tests.sagents.v2.model_fixture import TEST_MODELS
from tests.sagents.v2.test_standard_execution_configuration import (
    package, registration, runtime, run,
)
from sagents.v2.testing.plugins import ScriptedModelProvider


class InspectingModel:
    async def capabilities(self, binding):
        return await ScriptedModelProvider(()).capabilities(binding)

    async def stream(self, request):
        complete = any(message.role == "tool" for message in request.messages)
        yield ModelStreamEvent(kind="completed", response=ModelResponse(
            response_id="inspect", text="Done" if complete else "",
            finish_reason="stop" if complete else "tool_calls",
            tool_calls=() if complete else (ModelToolCall(
                tool_call_id="identity", name="inspect_identity", arguments={},
            ),),
        ))


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [ExtensionScope.PROCESS, ExtensionScope.TENANT,
                                 ExtensionScope.AGENT, ExtensionScope.RUN])
async def test_custom_tools_receive_actual_store_and_scope_identity(tmp_path, scope):
    created, observed, stopped, stores, model_stores = [], [], [], [], []

    class IdentityTools:
        def __init__(self, context, store):
            self.context, self.store = context, store
            self.provider = DecoratedToolProvider(self)

        @tool()
        async def inspect_identity(self, invocation):
            current = await self.store.get_run(invocation.call.owner_run_id)
            actual_context = await self.store.get_run_context(current.run_id)
            assert actual_context.actor == invocation.request_context.actor
            if self.context.scope == ExtensionScope.RUN:
                assert self.context.run_id == current.run_id
            observed.append((current.run_id, current.session_id, actual_context.actor.tenant_id))
            return {"run_id": current.run_id, "tenant": actual_context.actor.tenant_id}

        async def close(self):
            stopped.append(self.context.scope_id)

    def create(context, dependencies):
        store = dependencies.require("session.store")
        stores.append(store)
        created.append(context)
        return IdentityTools(context, store)

    custom = ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="test.scope.identity", name="Identity", version="1",
            provides=(CapabilityOffer(capability="tool.catalog", api_version="2", name="identity"),
                      CapabilityOffer(capability="tool.executor", api_version="2", name="identity")),
            dependencies=(ExtensionDependency(capability="session.store"),),
            supported_scopes=frozenset({scope}),
            config_schema={"type": "object", "additionalProperties": False},
        ), factory=create,
        start=lambda instance, context, dependencies: {
            "tool.catalog:identity": instance.provider,
            "tool.executor:identity": instance.provider,
        },
    )
    builder = SAgentBuilder()
    model_registration = registration("test.standard.model", "model.provider", InspectingModel())
    def model_factory(context, dependencies):
        model_stores.append(dependencies.require("session.store"))
        return InspectingModel()
    builder.register(replace(model_registration,
        descriptor=model_registration.descriptor.model_copy(update={
            "dependencies": (ExtensionDependency(capability="session.store"),),
        }), factory=model_factory))
    builder.register(registration("test.standard.policy", "agent.tool-policy", DefaultToolPolicy()))
    builder.register(custom)
    config = runtime(tmp_path)
    config = config.model_copy(update={"capabilities": {
        **config.capabilities,
        "tool.catalog": (CapabilitySelection(plugin="sage.tool.official"),
                         CapabilitySelection(plugin="test.scope.identity", name="identity", scope=scope, grant_tools=True)),
    }})
    app = await builder.build(runtime=config, models=TEST_MODELS)
    try:
        loaded = await app.load_agent(package())
        outcomes = await asyncio.gather(*(run(app, loaded, key) for key in ("first", "second")))
        assert all(result.state.value == "completed" for result, _ in outcomes), outcomes
        assert len(observed) == 2
        assert len({row[0] for row in observed}) == 2
        assert len({row[1] for row in observed}) == 2
        assert all(store is app.runtime.session_store for store in stores)
        assert model_stores and all(store is app.runtime.session_store for store in model_stores)
        assert len(created) == (2 if scope == ExtensionScope.RUN else 1)
        assert len(stopped) == (2 if scope == ExtensionScope.RUN else 0)
    finally:
        await app.close()
    assert len(stopped) == len(created)


@pytest.mark.asyncio
async def test_run_scoped_model_context_and_continuation_open_after_admission(tmp_path):
    from sagents.v2.context.contracts import ContextSegment, ContextStability
    from sagents.v2.agent.policy.continuation import ContinuationDecision
    from sagents.v2.model.contracts import ModelCapabilities
    from tests.sagents.v2.test_standard_execution_configuration import response

    created, stopped, used = [], [], []

    class RunModel(ScriptedModelProvider):
        def __init__(self, run_id):
            super().__init__((response(),))
            self.run_id = run_id

        async def capabilities(self, binding):
            return ModelCapabilities(supports_streaming=True, supports_tools=True,
                supports_parallel_tool_calls=True, supports_reasoning=False,
                supports_multimodal_input=False, supports_structured_output=False)

        async def stream(self, request):
            assert request.run_id == self.run_id
            assert self.run_id in str(request.messages)
            used.append(("model", self.run_id))
            async for event in super().stream(request):
                yield event

        async def close(self):
            stopped.append(("model.provider", self.run_id))

    class RunContext:
        def __init__(self, run_id):
            self.run_id = run_id

        async def segments(self, command, *, run_id=None):
            assert run_id == self.run_id
            used.append(("context", run_id))
            return (ContextSegment(segment_id="test.run-identity", content=self.run_id,
                                   stability=ContextStability.STABLE),)

        async def close(self):
            stopped.append(("context.segment-provider", self.run_id))

    class RunContinuation:
        def __init__(self, run_id):
            self.run_id = run_id

        async def decide(self, context):
            assert context.run_id == self.run_id
            used.append(("policy", self.run_id))
            return ContinuationDecision(action="complete_run", reason_code="test.complete", reason="done")

        async def close(self):
            stopped.append(("agent.continuation-policy", self.run_id))

    builder = SAgentBuilder()
    config = runtime(tmp_path)
    choices = dict(config.capabilities)
    builder.register(registration("test.standard.policy", "agent.tool-policy", DefaultToolPolicy()))
    run_models = {}
    for capability, implementation in (("model.provider", RunModel), ("context.segment-provider", RunContext),
                                        ("agent.continuation-policy", RunContinuation)):
        plugin_id = "test.run." + capability
        async def create(context, dependencies, capability=capability, implementation=implementation):
            assert context.run_id is not None
            store = dependencies.require("session.store")
            accepted = await store.get_run(context.run_id)
            authenticated = await store.get_run_context(accepted.run_id)
            assert authenticated.actor.tenant_id == context.tenant_id
            environment = dependencies.require("execution.environment")
            assert environment.run_id == accepted.run_id
            assert environment.context == authenticated
            assert environment.sandbox.ref.owner_run_id == accepted.run_id
            assert context.agent_configuration["model_routes"]["primary"]
            if capability != "model.provider":
                assert dependencies.require("model.provider") is run_models[context.run_id]
            created.append((capability, context.run_id))
            value = implementation(context.run_id)
            if capability == "model.provider":
                run_models[context.run_id] = value
            return value
        builder.register(ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id=plugin_id, name=capability, version="1",
                provides=(CapabilityOffer(capability=capability, api_version="2"),),
                dependencies=(ExtensionDependency(capability="session.store"),
                              ExtensionDependency(capability="execution.environment"),
                              *((ExtensionDependency(capability="model.provider"),) if capability != "model.provider" else ())),
                supported_scopes=frozenset({ExtensionScope.RUN}),
                config_schema={"type": "object", "additionalProperties": False},
            ), factory=create,
        ))
        choices[capability] = CapabilitySelection(plugin=plugin_id, scope=ExtensionScope.RUN)
    app = await builder.build(runtime=config.model_copy(update={"capabilities": choices}), models=TEST_MODELS)
    try:
        loaded = await app.load_agent(package())
        assert created == []
        outcomes = await asyncio.gather(*(run(app, loaded, key) for key in ("run-a", "run-b")))
        assert all(result.state.value == "completed" for result, _ in outcomes), outcomes
        ids = {result.run_id for result, _ in outcomes}
        assert set(created) == {(capability, run_id) for capability in (
            "model.provider", "context.segment-provider", "agent.continuation-policy",
        ) for run_id in ids}
        assert set(used) == {(kind, run_id) for kind in ("model", "context", "policy") for run_id in ids}
        assert sorted(stopped) == sorted(created)
    finally:
        await app.close()
    assert sorted(stopped) == sorted(created)
