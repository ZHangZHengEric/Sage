"""Inventory is derived from executable extension registrations."""

from __future__ import annotations

import pytest

from sagents.v2.agent.policy import (
    CompositeContinuationPolicy,
    ExplicitStatusContinuationPolicy,
    HybridContinuationPolicy,
    LLMJudgeContinuationPolicy,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionRegistry,
    ExtensionScope,
    ExtensionScopeContext,
)
from sagents.v2.runtime.extensions.defaults import builtin_extension_registry
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider


def test_builtin_inventory_contains_only_real_factories():
    registry = builtin_extension_registry()
    inventory = {value["plugin_id"]: value for value in registry.inventory()}

    assert {
        "sage.agent.continuation.deterministic",
        "sage.agent.continuation.llm-judge",
        "sage.agent.continuation.hybrid",
        "sage.agent.continuation.explicit-status",
        "sage.artifact.ephemeral",
        "sage.context.reducer.persistent-summary",
        "sage.context.reducer.window",
        "sage.context.summarizer.extractive",
        "sage.context.summarizer.model",
        "sage.context.summary-store.ephemeral",
        "sage.context.summary-store.session-derived",
        "sage.context.token-estimator.json-heuristic",
        "sage.context.token-estimator.tiktoken",
        "sage.context.token-estimator.unicode-heuristic",
        "sage.context.unit-compactor.reference",
        "sage.credentials.environment",
        "sage.credentials.mapping",
        "sage.flow.agent",
        "sage.job.ephemeral",
        "sage.memory.filesystem-bm25",
        "sage.memory.recall-query.direct",
        "sage.memory.recall-query.llm",
        "sage.session.filesystem",
        "sage.session.postgres",
        "sage.session.mysql",
        "sage.session.ephemeral",
        "sage.session-memory.noop",
        "sage.session-memory.sqlite-bm25",
        "sage.memory.noop",
        "sage.tool.mcp",
        "sage.tool.multi-agent",
        "sage.tool.official",
        "sage.tool.skill",
        "sage.tool-selection.direct",
        "sage.tool-selection.lexical",
        "sage.tool-selection.llm",
        "sage.tool-selection.recent",
        "sage.skill.filesystem",
        "sage.model.openai-responses",
        "sage.model.openai-chat-completions",
        "sage.model.anthropic-messages",
        "sage.observability.filesystem",
        "sage.observability.noop",
        "sage.logging.filesystem",
        "sage.logging.noop",
        "sage.package-registry.ephemeral",
        "sage.protocol.a2a",
        "sage.protocol.acp",
        "sage.protocol.ag-ui",
        "sage.protocol.mcp",
        "sage.protocol.native",
        "sage.sandbox.ephemeral",
        "sage.sandbox.local-workspace",
        "sage.scheduler.ephemeral",
        "sage.scheduler.filesystem",
        "sage.workspace.initializer.bare",
        "sage.workspace.initializer.claw",
    } == set(inventory)
    assert all(callable(value.factory) for value in registry.registrations())
    assert (
        inventory["sage.session.filesystem"]["capabilities"]["global_session_index"]
        is False
    )
    assert (
        inventory["sage.scheduler.filesystem"]["capabilities"]
        ["durable_across_process_restart"]
        is True
    )
    assert (
        inventory["sage.scheduler.filesystem"]["capabilities"]
        ["multi_process_writes"]
        is False
    )
    assert (
        inventory["sage.session.postgres"]["capabilities"]["multi_process_writes"]
        is False
    )
    assert (
        inventory["sage.session.mysql"]["capabilities"]["multi_process_writes"]
        is False
    )


def test_every_registered_plugin_has_a_pydantic_config_boundary():
    registry = builtin_extension_registry()

    assert all(
        registration.config_model is not None
        for registration in registry.registrations()
    )
    assert all(
        registration.config_model.model_json_schema()["type"] == "object"
        for registration in registry.registrations()
    )


def test_duplicate_registration_is_rejected():
    registry = ExtensionRegistry()
    registration = ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="vendor.test",
            version="2.0.0",
            name="Test",
            provides=(CapabilityOffer(capability="test", api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
        ),
        factory=lambda context, dependencies: object(),
    )
    registry.register(registration)
    with pytest.raises(SageV2Error) as duplicate:
        registry.register(registration)
    assert duplicate.value.info.code == "extension.duplicate_id"


def test_registered_factory_creates_the_selected_instance():
    registry = builtin_extension_registry()
    registration = registry.get("sage.memory.noop")
    value = registration.factory(
        ExtensionScopeContext(
            scope=ExtensionScope.PROCESS,
            scope_id="test-process",
        ),
        {},
    )
    assert value.__class__.__name__ == "NoopMemoryProvider"


@pytest.mark.parametrize(
    ("plugin_id", "expected_type"),
    [
        (
            "sage.agent.continuation.deterministic",
            CompositeContinuationPolicy,
        ),
        ("sage.agent.continuation.llm-judge", LLMJudgeContinuationPolicy),
        ("sage.agent.continuation.hybrid", HybridContinuationPolicy),
        (
            "sage.agent.continuation.explicit-status",
            ExplicitStatusContinuationPolicy,
        ),
    ],
)
def test_every_continuation_plugin_factory_creates_a_real_policy(
    plugin_id, expected_type
):
    registry = builtin_extension_registry()
    registration = registry.get(plugin_id)

    value = registration.factory(
        ExtensionScopeContext(
            scope=ExtensionScope.AGENT,
            scope_id="test-continuation",
            config={"model": ScriptedModelProvider(())},
        ),
        {},
    )

    assert isinstance(value, expected_type)
