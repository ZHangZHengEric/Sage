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
    CapabilityKey,
    ProviderSet,
    CapabilityRequirement,
    ExtensionDescriptor,
    ExtensionHost,
    ExtensionRegistration,
    ExtensionRegistry,
    ExtensionScope,
    ExtensionScopeContext,
    plugin_identity,
)
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider


def test_builtin_inventory_contains_only_real_factories():
    registry = builtin_extension_registry()
    inventory = {value["plugin_id"]: value for value in registry.inventory()}

    assert {key for key in inventory if key.startswith("sage.session.")} == {
        "sage.session.ephemeral", "sage.session.filesystem", "sage.session.mysql", "sage.session.redis-mysql",
    }
    assert {
        "sage.agent.continuation.deterministic",
        "sage.agent.continuation.llm-judge",
        "sage.agent.continuation.hybrid",
        "sage.agent.continuation.explicit-status",
        "sage.artifact.session",
        "sage.artifact.ephemeral",
        "sage.artifact.filesystem",
        "sage.context.reducer.persistent-summary",
        "sage.context.reducer.window",
        "sage.context.summarizer.extractive",
        "sage.context.summarizer.model",
        "sage.context.summary-store.ephemeral",
        "sage.context.summary-store.session-derived",
        "sage.context.unit-compactor.reference",
        "sage.credentials.environment",
        "sage.credentials.mapping",
        "sage.flow.agent",
        "sage.job.ephemeral",
        "sage.job.redis-distributed",
        "sage.memory.filesystem-bm25",
        "sage.memory.recall-query.direct",
        "sage.memory.recall-query.llm",
        "sage.session.filesystem",
        "sage.session.mysql",
        "sage.session.redis-mysql",
        "sage.session.ephemeral",
        "sage.session-memory.noop",
        "sage.session-memory.sqlite-bm25",
        "sage.memory.noop",
        "sage.tool.ephemeral",
        "sage.tool.mcp",
        "sage.tool.multi-agent",
        "sage.tool.official",
        "sage.tool.result-processor.file",
        "sage.tool.skill",
        "sage.tool-selection.direct",
        "sage.tool-selection.lexical",
        "sage.tool-selection.llm",
        "sage.tool-selection.recent",
        "sage.skill.filesystem",
        "sage.skill.loading.lazy",
        "sage.skill.repository.sqlite",
        "sage.skill.repository.memory",
        "sage.skill.workspace.readonly-mount",
        "sage.skill.workspace.auto-sync",
        "sage.skill.workspace.fixed-copy",
        "sage.model.openai-responses",
        "sage.model.openai-chat-completions",
        "sage.model.anthropic-messages",
        "sage.model.gemini-generate-content",
        "sage.observability.filesystem",
        "sage.observability.noop",
        "sage.logging.filesystem",
        "sage.logging.noop",
        "sage.logging.stdout",
        "sage.trace.noop",
        "sage.trace.otlp",
        "sage.trace.langfuse",
        "sage.trace.phoenix",
        "sage.package-registry.ephemeral",
        "sage.protocol.a2a",
        "sage.protocol.acp",
        "sage.protocol.ag-ui",
        "sage.protocol.mcp",
        "sage.protocol.native",
        "sage.sandbox.ephemeral",
        "sage.sandbox.local-workspace",
        "sage.sandbox.cube-volume",
        "sage.scheduler.ephemeral",
        "sage.scheduler.filesystem",
        "sage.scheduler.redis-distributed",
        "sage.workspace.initializer.bare",
        "sage.workspace.initializer.claw",
        "sage.execution.binding.local-workspace",
        "sage.execution.binding.ephemeral",
        "sage.execution.environment",
        "sage.execution.tool-runtime",
        "sage.agent.tool-policy.default",
        "sage.agent.approval-memory.session",
        "sage.derived-state.session",
        "sage.derived-state.ephemeral",
        "sage.model.concurrency-budget",
    } == set(inventory)
    assert all(callable(value.factory) for value in registry.registrations())
    assert (
        inventory["sage.session.filesystem"]["capabilities"]["global_session_index"]
        is False
    )
    assert (
        inventory["sage.scheduler.filesystem"]["capabilities"][
            "durable_across_process_restart"
        ]
        is True
    )
    assert (
        inventory["sage.artifact.ephemeral"]["capabilities"][
            "durable_across_process_restart"
        ]
        is False
    )
    assert (
        inventory["sage.package-registry.ephemeral"]["capabilities"][
            "supports_package_signatures"
        ]
        is False
    )
    assert (
        inventory["sage.scheduler.filesystem"]["capabilities"]["multi_process_writes"]
        is False
    )
    assert (
        inventory["sage.session.mysql"]["capabilities"]["multi_process_writes"] is False
    )
    assert inventory["sage.tool.ephemeral"]["capabilities"]["durable"] is False
    assert inventory["sage.tool.ephemeral"]["capabilities"]["testing"] is True
    for plugin_id in (
        "sage.sandbox.ephemeral",
        "sage.sandbox.local-workspace",
        "sage.sandbox.cube-volume",
    ):
        assert inventory[plugin_id]["version"] == "3.0.0"
        assert inventory[plugin_id]["provides"][0]["capability"] == "execution.sandbox"
        assert inventory[plugin_id]["provides"][0]["api_version"] == "3"


def test_official_plugins_declare_identity():
    from sagents.v2.model import (
        OpenAIChatCompletionsModelProvider,
        OpenAICompatibleModelProvider,
    )

    registry = builtin_extension_registry()
    missing = [
        value["plugin_id"]
        for value in registry.inventory()
        if not str(value.get("name") or "").strip()
        or not str(value.get("description") or "").strip()
    ]
    assert missing == []
    assert plugin_identity(CompositeContinuationPolicy) == (
        "sage.agent.continuation.deterministic",
        "Deterministic continuation policy",
        "Applies ordered safety, budget, and completion rules without a model call.",
    )
    # Both public entry points implement the same Chat Completions protocol.
    assert plugin_identity(OpenAICompatibleModelProvider) == plugin_identity(
        OpenAIChatCompletionsModelProvider
    )


def test_plugin_identity_rejects_incomplete_classes():
    class Incomplete:
        plugin_id = "acme.test"

    with pytest.raises(TypeError, match="name, description"):
        plugin_identity(Incomplete)

    class UndeclaredIdentity(CompositeContinuationPolicy):
        pass

    with pytest.raises(TypeError, match="plugin_id"):
        plugin_identity(UndeclaredIdentity)


@pytest.mark.parametrize(
    "plugin_id",
    [
        "sage.agent.tool-policy.default",
        "sage.agent.approval-memory.session",
        "sage.derived-state.ephemeral",
        "sage.model.concurrency-budget",
        "sage.execution.binding.local-workspace",
        "sage.execution.binding.ephemeral",
        "sage.execution.environment",
        "sage.execution.tool-runtime",
    ],
)
def test_service_plugin_factories_return_their_own_declared_identity(
    plugin_id, tmp_path
):
    from sagents.v2.contracts.commands import StartRun
    from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
    from sagents.v2.runtime.artifact import InMemoryArtifactStore
    from sagents.v2.runtime.execution.environment import (
        RunExecutionEnvironment,
        _bind_execution_environment,
    )
    from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
    from sagents.v2.runtime.extensions.contracts import CapabilityKey, ProviderSet
    from sagents.v2.runtime.session import (
        EphemeralSessionStore,
        InMemoryDerivedStateStore,
    )

    # Borrowed host resources are not exercised by identity construction.
    environment = RunExecutionEnvironment(
        run_id="identity-run",
        command=StartRun(
            agent_id="agent",
            input=(),
            resolved_spec_hash="sha256:identity",
            idempotency_key="identity",
        ),
        context=RequestContext(
            actor=ActorRef(principal_id="user", principal_type=PrincipalType.USER)
        ),
        sandbox=object(),
        grant_issuer=object(),
    )
    providers = {
        "derived-state.store": InMemoryDerivedStateStore(),
        "session.store": EphemeralSessionStore(),
        "execution.environment": environment,
        "execution.job-runtime": InMemoryJobRuntime({}),
        "artifact.store": InMemoryArtifactStore(),
        "tool.selection-policy": object(),
    }
    dependencies = ProviderSet(
        {CapabilityKey(capability=key): value for key, value in providers.items()}
    )
    registration = builtin_extension_registry().get(plugin_id)
    context = ExtensionScopeContext(
        scope=registration.descriptor.resolved_default_scope(),
        scope_id="identity-scope",
        run_id=environment.run_id,
        config={"workspace": str(tmp_path)}
        if plugin_id.endswith("local-workspace")
        else {},
    )
    with _bind_execution_environment(environment):
        instance = registration.factory(context, dependencies)
    assert plugin_identity(type(instance))[0] == registration.descriptor.plugin_id


def test_external_diagnostic_sink_has_a_distinct_identity():
    from sagents.v2.runtime.observability.plugins.diagnostic_noop import (
        NoopDiagnosticSink,
    )
    from sagents.v2.runtime.observability.plugins.external import ExternalEvidenceSink

    assert (
        plugin_identity(ExternalEvidenceSink)[0]
        != plugin_identity(NoopDiagnosticSink)[0]
    )


def test_package_source_module_scope_declares_its_plugin_identity():
    from sagents.v2.agent.management.plugins.source_modules import SourcePluginScope

    assert plugin_identity(SourcePluginScope)[0] == "sage.package.source-modules"


@pytest.mark.parametrize(
    ("module", "implementation", "expected_id"),
    [
        ("skill.plugins.ephemeral", "InMemorySkillProvider", "sage.skill.ephemeral"),
        (
            "skill.plugins.ephemeral",
            "InMemorySkillWorkspace",
            "sage.skill.workspace.ephemeral",
        ),
        (
            "skill.plugins.ephemeral",
            "InMemorySkillActivationRepository",
            "sage.skill.activation.ephemeral",
        ),
        (
            "skill.plugins.session",
            "SessionDerivedSkillActivationRepository",
            "sage.skill.activation.session-derived",
        ),
        (
            "skill.plugins.sandbox",
            "SandboxSkillWorkspace",
            "sage.skill.workspace.sandbox",
        ),
        (
            "testing.plugins.scripted_model",
            "ScriptedModelProvider",
            "sage.model.scripted",
        ),
    ],
)
def test_directly_injected_plugins_declare_identity(
    module, implementation, expected_id
):
    from importlib import import_module

    plugin = getattr(import_module(f"sagents.v2.{module}"), implementation)
    assert plugin_identity(plugin)[0] == expected_id


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
    assert all(
        registration.descriptor.config_schema.get("additionalProperties") is False
        for registration in registry.registrations()
    )


@pytest.mark.parametrize(
    ("capability", "plugin_id"),
    [
        ("session-memory.provider", "sage.session-memory.sqlite-bm25"),
        ("observability.log-sink", "sage.logging.filesystem"),
    ],
)
def test_official_plugin_required_config_fails_during_planning(capability, plugin_id):
    host = ExtensionHost(builtin_extension_registry())

    with pytest.raises(SageV2Error) as caught:
        host.plan(
            (CapabilityRequirement(capability=capability, api_version=">=2,<3"),),
            selections={capability: plugin_id},
        )

    assert caught.value.info.code == "extension.config_invalid"


def test_no_config_official_plugin_rejects_unknown_fields_during_planning():
    host = ExtensionHost(builtin_extension_registry())

    with pytest.raises(SageV2Error) as caught:
        host.plan(
            (CapabilityRequirement(capability="artifact.store", api_version=">=2,<3"),),
            selections={"artifact.store": "sage.artifact.ephemeral"},
            configs={"sage.artifact.ephemeral": {"typo": True}},
        )

    assert caught.value.info.code == "extension.config_invalid"


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


def test_ephemeral_tool_plugin_factory_exposes_paired_catalog_and_executor():
    registry = builtin_extension_registry()
    registration = registry.get("sage.tool.ephemeral")
    context = ExtensionScopeContext(
        scope=ExtensionScope.PROCESS,
        scope_id="test-tools",
    )
    plugin = registration.factory(context, ProviderSet())

    assert plugin.__class__.__name__ == "EphemeralToolPlugin"
    assert plugin.plugin_id == "sage.tool.ephemeral"
    assert registration.start is not None
    providers = registration.start(plugin, context, {})
    assert set(providers) == {"tool.catalog:ephemeral", "tool.executor:ephemeral"}
    assert providers["tool.catalog:ephemeral"] is plugin.catalog
    assert providers["tool.executor:ephemeral"] is plugin.executor


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
        ),
        ProviderSet({CapabilityKey(capability="model.provider"): ScriptedModelProvider(())}),
    )

    assert isinstance(value, expected_type)


def test_local_sandbox_command_path_passes_through_plugin_config():
    from sagents.v2.runtime.extensions.contracts import ExtensionScopeContext

    registry = builtin_extension_registry()
    config = {"verification_key": "key", "command_path": "/configured/bin:/bin"}
    host = ExtensionHost(registry)
    host.plan(
        (CapabilityRequirement(capability="execution.sandbox", api_version=">=3,<4"),),
        selections={"execution.sandbox": "sage.sandbox.local-workspace"},
        configs={"sage.sandbox.local-workspace": config},
    )
    registration = registry.get("sage.sandbox.local-workspace")
    provider = registration.factory(
        ExtensionScopeContext(
            scope=ExtensionScope.PROCESS, scope_id="path-test", config=config
        ),
        {},
    )
    assert provider.command_path == config["command_path"]


def test_local_sandbox_read_paths_pass_through_plugin_config():
    from sagents.v2.runtime.extensions.contracts import ExtensionScopeContext

    registry = builtin_extension_registry()
    config = {
        "verification_key": "key",
        "read_paths": ["/opt/host-runtime"],
    }
    host = ExtensionHost(registry)
    host.plan(
        (CapabilityRequirement(capability="execution.sandbox", api_version=">=3,<4"),),
        selections={"execution.sandbox": "sage.sandbox.local-workspace"},
        configs={"sage.sandbox.local-workspace": config},
    )
    registration = registry.get("sage.sandbox.local-workspace")
    provider = registration.factory(
        ExtensionScopeContext(
            scope=ExtensionScope.PROCESS, scope_id="read-paths-test", config=config
        ),
        {},
    )
    assert provider.read_paths == ("/opt/host-runtime",)
