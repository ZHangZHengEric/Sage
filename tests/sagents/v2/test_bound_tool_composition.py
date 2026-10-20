"""Bound official tools use actual registered Run resources and SDK cleanup."""

import pytest

from sagents.v2.package.manifest.runtime import CapabilitySelection
from sagents.v2.runtime.extensions import (
    CapabilityKey, CapabilityOffer, ExtensionDependency, ExtensionDescriptor, ExtensionRegistration, ExtensionScope,
)
from sagents.v2.runtime.execution.plugins.local_binding import LocalWorkspaceExecutionBindingProvider
from sagents.v2.tool import InMemoryToolCatalog, InMemoryToolExecutor
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.sagents.v2.test_standard_execution_configuration import (
    package,
    response,
    run,
    runtime,
)
from sagents.v2 import SAgentBuilder
from tests.sagents.v2.model_fixture import TEST_MODELS
from tests.sagents.v2.test_standard_execution_configuration import registration, CONTEXT
from sagents.v2.agent.policy import DefaultToolPolicy


def tools_registration(factory):
    return ExtensionRegistration(descriptor=ExtensionDescriptor(plugin_id="test.bound.tools", name="Bound tools", version="1",
        provides=(CapabilityOffer(capability="tool.catalog", api_version="2"), CapabilityOffer(capability="tool.executor", api_version="2")),
        dependencies=(ExtensionDependency(capability="execution.environment"), ExtensionDependency(capability="execution.tool-runtime")),
        supported_scopes=frozenset({ExtensionScope.RUN})), factory=factory,
        start=lambda value, context, dependencies: {CapabilityKey(capability="tool.catalog"): value.catalog,
            CapabilityKey(capability="tool.executor"): value.executor})


def paired_runtime(root):
    selected = runtime(root)
    return selected.model_copy(update={"capabilities": {**selected.capabilities, "tool.catalog": (
        CapabilitySelection(plugin="sage.tool.official"), CapabilitySelection(plugin="test.bound.tools", scope="run"))}})


@pytest.mark.asyncio
async def test_bound_tools_are_run_scoped_and_share_only_selected_services(tmp_path):
    observed, closed = [], []
    class Tools:
        catalog = InMemoryToolCatalog(())
        executor = InMemoryToolExecutor({}, {})
        def __init__(self, run_id):
            self.run_id = run_id
        async def close(self):
            closed.append(self.run_id)
    def create(context, dependencies):
        environment = dependencies.require("execution.environment")
        official = dependencies.require("execution.tool-runtime")
        assert environment.run_id == context.run_id
        assert official.sandbox is environment.sandbox
        assert official.memory_service is environment.memory_service
        observed.append((environment, official))
        return Tools(context.run_id)
    model = ScriptedModelProvider((response(), response()))
    builder = SAgentBuilder()
    builder.register(registration("test.standard.model", "model.provider", model))
    builder.register(registration("test.standard.policy", "agent.tool-policy", DefaultToolPolicy()))
    builder.register(tools_registration(create))
    app = await builder.build(runtime=paired_runtime(tmp_path), models=TEST_MODELS)
    try:
        agent = await app.load_agent(package())
        for key in ("first", "second"):
            result, _ = await run(app, agent, key)
            assert result.state.value == "completed"
        assert len(observed) == 2
        assert observed[0][1] is not observed[1][1]
        assert observed[0][1].job_runtime is observed[1][1].job_runtime
        assert observed[0][0].memory_service is observed[1][0].memory_service
        assert closed == [environment.run_id for environment, _ in observed]
    finally:
        await app.close()
    assert len(closed) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["workspace", "plugin"])
async def test_standard_owner_releases_binding_once_when_tool_assembly_fails(tmp_path, phase):
    acquired, opened = [], []
    class Binding(LocalWorkspaceExecutionBindingProvider):
        async def acquire(self, request):
            binding = await super().acquire(request)
            acquired.append(binding)
            return binding
    class Initializer:
        async def initialize(self, workspace):
            if phase == "workspace":
                raise RuntimeError("workspace failure")
    def create(context, dependencies):
        opened.append(context.run_id)
        raise RuntimeError("plugin failure")
    builder = SAgentBuilder()
    model = ScriptedModelProvider(())
    builder.register(registration("test.standard.model", "model.provider", model))
    builder.register(registration("test.standard.policy", "agent.tool-policy", DefaultToolPolicy()))
    builder.register(tools_registration(create))
    for plugin, capability, factory in (
        ("test.bound.binding", "execution.binding", lambda context, dependencies: Binding(tmp_path / "workspace")),
        ("test.bound.initializer", "workspace.initializer", lambda context, dependencies: Initializer()),
    ):
        builder.register(ExtensionRegistration(descriptor=ExtensionDescriptor(plugin_id=plugin, name=plugin, version="1",
            provides=(CapabilityOffer(capability=capability, api_version="2"),), supported_scopes=frozenset({ExtensionScope.PROCESS})), factory=factory))
    selected = paired_runtime(tmp_path)
    selected = selected.model_copy(update={"capabilities": {**selected.capabilities,
        "execution.binding": CapabilitySelection(plugin="test.bound.binding"),
        "workspace.initializer": CapabilitySelection(plugin="test.bound.initializer")}})
    app = await builder.build(runtime=selected, models=TEST_MODELS)
    try:
        agent = await app.load_agent(package())
        result, _ = await run(app, agent, "failure")
        assert result.state.value == "failed"
        assert len(acquired) == 1 and acquired[0].closed
        assert opened == ([] if phase == "workspace" else [result.run_id])
        assert not model.requests
        assert await app.execution_diagnostics(result.run_id, CONTEXT)
    finally:
        await app.close()
    await app.close()
    assert acquired[0].closed
