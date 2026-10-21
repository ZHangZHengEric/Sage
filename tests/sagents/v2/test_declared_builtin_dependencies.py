"""Built-ins resolve named ports, validate lifetimes, and reject object configs.

Existing host tests cover generic dependency ordering and rollback. These cases
protect the former built-in config injection path at the real provider boundary.
"""

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    CapabilityRequirement,
    ExtensionDescriptor,
    ExtensionHost,
    ExtensionRegistration,
    ExtensionRegistry,
    ExtensionScope,
    ExtensionScopeContext,
)
from sagents.v2.runtime.extensions.official import builtin_extension_registry


def context_registry():
    builtin = builtin_extension_registry()
    registry = ExtensionRegistry()
    for plugin in (
        "sage.context.reducer.persistent-summary",
        "sage.context.summarizer.model",
        "sage.context.summary-store.session-derived",
        "sage.derived-state.ephemeral",
    ):
        registry.register(builtin.get(plugin))
    model = object()
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="test.named-model",
                name="Named model",
                version="2",
                provides=(
                    CapabilityOffer(
                        capability="model.provider", name="named", api_version="2"
                    ),
                ),
                supported_scopes=frozenset({ExtensionScope.RUN}),
                config_schema={"type": "object", "additionalProperties": False},
            ),
            factory=lambda context, dependencies: model,
        )
    )
    return registry, model


@pytest.mark.asyncio
async def test_builtin_context_uses_declared_named_providers_and_reports_complete_graph():
    registry, model = context_registry()
    host = ExtensionHost(registry)
    plan = host.plan(
        (CapabilityRequirement(capability="context.reducer", api_version="2"),),
        scope_overrides={
            "sage.context.reducer.persistent-summary": ExtensionScope.RUN,
            "sage.context.summarizer.model": ExtensionScope.RUN,
        },
    )
    handle = await host.open_scope_hierarchy(
        ExtensionScopeContext(scope=ExtensionScope.RUN, scope_id="run", run_id="run"),
        plan,
    )
    try:
        reducer = handle.providers.require("context.reducer")
        assert reducer.summarizer.model is model
        assert reducer.store is handle.providers.require("context.summary-store")
        assert reducer.store.derived_state is handle.providers.require(
            "derived-state.store"
        )
        assert set(plan.graph.dependencies) == {
            (
                "sage.context.reducer.persistent-summary",
                "sage.context.summarizer.model",
            ),
            (
                "sage.context.reducer.persistent-summary",
                "sage.context.summary-store.session-derived",
            ),
            ("sage.context.summarizer.model", "test.named-model"),
            (
                "sage.context.summary-store.session-derived",
                "sage.derived-state.ephemeral",
            ),
        }
    finally:
        await handle.close()


def test_builtin_context_rejects_shorter_lived_dependency_during_planning():
    registry, _ = context_registry()
    with pytest.raises(SageV2Error) as error:
        ExtensionHost(registry).plan(
            (CapabilityRequirement(capability="context.reducer", api_version="2"),),
        )
    assert error.value.info.code == "extension.invalid_scope_dependency"


@pytest.mark.parametrize(
    "plugin,capability,missing",
    [
        (
            "sage.context.reducer.persistent-summary",
            "context.reducer",
            "context.summary-store",
        ),
        ("sage.context.summarizer.model", "context.summarizer", "model.provider"),
        (
            "sage.agent.continuation.llm-judge",
            "agent.continuation-policy",
            "model.provider",
        ),
        (
            "sage.context.summary-store.session-derived",
            "context.summary-store",
            "derived-state.store",
        ),
    ],
)
def test_builtin_missing_dependency_is_rejected_before_start(
    plugin, capability, missing
):
    registry = ExtensionRegistry()
    registry.register(builtin_extension_registry().get(plugin))
    with pytest.raises(SageV2Error) as error:
        ExtensionHost(registry).plan(
            (CapabilityRequirement(capability=capability, api_version="2"),)
        )
    assert error.value.info.code == "extension.capability_missing"
    assert missing in error.value.info.message


@pytest.mark.parametrize("value", [object(), {"nested": object()}, float("nan")])
def test_plugin_object_config_is_rejected_before_factory(value):
    created = []
    registry = ExtensionRegistry()
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="test.json-config",
                name="JSON parameters",
                version="2",
                provides=(CapabilityOffer(capability="test.port", api_version="2"),),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={"type": "object", "additionalProperties": True},
            ),
            factory=lambda context, dependencies: created.append(context.config),
        )
    )
    with pytest.raises(SageV2Error) as error:
        ExtensionHost(registry).plan(
            (CapabilityRequirement(capability="test.port", api_version="2"),),
            configs={"test.json-config": {"value": value}},
        )
    assert error.value.info.code == "extension.config_invalid"
    assert created == []


@pytest.mark.asyncio
async def test_scoped_configs_remain_independent_json_snapshots_after_model_validation():
    from pydantic import BaseModel

    class Policy(BaseModel):
        name: str

    class Parameters(BaseModel):
        policy: Policy

    seen = []

    def create(context, dependencies):
        assert isinstance(context.config["policy"], dict)
        seen.append(context.config["policy"]["name"])
        context.config["policy"]["name"] = "factory mutation"
        return context.config

    registry = ExtensionRegistry()
    registry.register(
        ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id="test.parameter-snapshot",
                name="JSON snapshot",
                version="2",
                provides=(
                    CapabilityOffer(capability="test.snapshot", api_version="2"),
                ),
                supported_scopes=frozenset({ExtensionScope.RUN}),
                config_schema=Parameters.model_json_schema(),
            ),
            factory=create,
            config_model=Parameters,
        )
    )
    original = {"policy": {"name": "original"}}
    host = ExtensionHost(registry)
    plan = host.plan(
        (CapabilityRequirement(capability="test.snapshot", api_version="2"),),
        configs={"test.parameter-snapshot": original},
    )
    original["policy"]["name"] = "caller mutation"
    for run_id in ("first", "second"):
        handle = await host.open_scope(
            ExtensionScopeContext(
                scope=ExtensionScope.RUN, scope_id=run_id, run_id=run_id
            ),
            plan,
        )
        await handle.close()
    assert seen == ["original", "original"]
    assert original["policy"]["name"] == "caller mutation"


def test_native_flow_factory_uses_dependency_ports_and_json_definition():
    from sagents.v2.agent.multi_agent.contracts import WorkspaceSharingPolicy
    from sagents.v2.runtime.extensions import CapabilityKey, ProviderSet

    runtime, executor = object(), object()
    node = (
        builtin_extension_registry()
        .get("sage.flow.agent")
        .factory(
            ExtensionScopeContext(
                scope=ExtensionScope.RUN,
                scope_id="run",
                run_id="run",
                config={
                    "descriptor": {
                        "agent_id": "child",
                        "name": "Child",
                        "description": "",
                        "instructions": "Run",
                    },
                    "workspace_policy": "read_only_parent",
                },
            ),
            ProviderSet(
                {
                    CapabilityKey(capability="runtime.kernel"): runtime,
                    CapabilityKey(capability="agent.child-executor"): executor,
                }
            ),
        )
    )
    assert node.runtime is runtime
    assert node.child_executor is executor
    assert node.descriptor.agent_id == "child"
    assert node.workspace_policy is WorkspaceSharingPolicy.READ_ONLY_PARENT
