"""Inventory is derived from executable extension registrations."""

from __future__ import annotations

import pytest

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


def test_builtin_inventory_contains_only_real_factories():
    registry = builtin_extension_registry()
    inventory = {value["plugin_id"]: value for value in registry.inventory()}

    assert {
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
        "sage.credentials.environment",
        "sage.credentials.mapping",
        "sage.flow.agent",
        "sage.job.ephemeral",
        "sage.memory.filesystem-bm25",
        "sage.session.filesystem",
        "sage.session.ephemeral",
        "sage.memory.noop",
        "sage.tool.mcp",
        "sage.tool.multi-agent",
        "sage.tool.official",
        "sage.tool.skill",
        "sage.skill.filesystem",
        "sage.model.openai-responses",
        "sage.model.openai-chat-completions",
        "sage.model.anthropic-messages",
        "sage.observability.filesystem",
        "sage.observability.noop",
        "sage.package-registry.ephemeral",
        "sage.protocol.a2a",
        "sage.protocol.acp",
        "sage.protocol.ag-ui",
        "sage.protocol.mcp",
        "sage.protocol.native",
        "sage.sandbox.ephemeral",
        "sage.sandbox.local-workspace",
        "sage.scheduler.ephemeral",
    } == set(inventory)
    assert all(callable(value.factory) for value in registry.registrations())
    assert (
        inventory["sage.session.filesystem"]["capabilities"]["global_session_index"]
        is False
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
