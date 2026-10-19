"""Public Run behavior replaces the retired host materializer contract."""
import asyncio

import pytest

from sagents.v2.contracts.principals import ActorRef, RequestContext
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig
from sagents.v2.runtime.extensions import (
    CapabilityOffer, ExtensionDependency, ExtensionDescriptor, ExtensionRegistration, ExtensionScope,
)
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.sagents.v2.model_fixture import TEST_MODELS
from tests.sagents.v2.sdk_fixture import build_registered_app
from tests.sagents.v2.test_standard_execution_configuration import package, response, run


@pytest.mark.asyncio
@pytest.mark.parametrize("scope,instances", [(ExtensionScope.PROCESS, 1), (ExtensionScope.TENANT, 2),
                                            (ExtensionScope.AGENT, 4), (ExtensionScope.RUN, 8)])
async def test_registered_context_scope_isolated_by_real_tenant_agent_and_run(tmp_path, scope, instances):
    created, observed, closed = [], [], []
    class Context:
        def __init__(self, context, store):
            self.context, self.store = context, store
        async def segments(self, command, *, run_id):
            actual = await self.store.get_run_context(run_id)
            if scope != ExtensionScope.PROCESS:
                assert actual.actor.tenant_id == self.context.tenant_id
            if scope in {ExtensionScope.AGENT, ExtensionScope.RUN}:
                assert command.agent_id == self.context.agent_id
            if scope == ExtensionScope.RUN:
                assert run_id == self.context.run_id
            observed.append((run_id, actual.actor.tenant_id, command.agent_id))
            return ()
        async def close(self):
            closed.append(self.context.scope_id)
    def factory(context, deps):
        created.append(context)
        return Context(context, deps.require("session.store"))
    registration = ExtensionRegistration(descriptor=ExtensionDescriptor(
        plugin_id="test.context.identity", name="Context identity", version="1",
        provides=(CapabilityOffer(capability="context.segment-provider", api_version="2"),),
        dependencies=(ExtensionDependency(capability="session.store"),),
        supported_scopes=frozenset({scope}), default_scope=scope,
        config_schema={"type": "object", "additionalProperties": False}), factory=factory)
    runtime = RuntimeConfig.model_validate({"capabilities": {
        "session.store": {"plugin": "sage.session.ephemeral"},
        "context.segment-provider": {"plugin": "test.context.identity", "scope": scope},
        "agent.continuation-policy": {"plugin": "sage.agent.continuation.deterministic"},
        "tool.selection-policy": {"plugin": "sage.tool-selection.direct"},
    }})
    app = await build_registered_app(tmp_path, runtime=runtime, models=TEST_MODELS,
        model=ScriptedModelProvider(tuple(response() for _ in range(8))), registrations=(registration,))
    try:
        first = package()
        second = first.model_copy(update={"metadata": first.metadata.model_copy(update={"id": "test.other"})})
        agents = [await app.load_agent(value) for value in (first, second)]
        results = await asyncio.gather(*(run(app, agent, f"{tenant}-{agent.id}-{repeat}",
            context=RequestContext(actor=ActorRef(principal_id=tenant, tenant_id=tenant, principal_type="user")))
            for tenant in ("one", "two") for agent in agents for repeat in range(2)))
        assert all(result.state.value == "completed" for result, _ in results), results
        assert len(created) == instances
        assert {tenant for _, tenant, _ in observed} == {"one", "two"}
        assert {agent for _, _, agent in observed} == {agent.id for agent in agents}
        assert len({run_id for run_id, _, _ in observed}) == 8
        assert len(closed) == (8 if scope == ExtensionScope.RUN else 0)
    finally:
        await app.close()
    assert len(closed) == instances


@pytest.mark.asyncio
@pytest.mark.parametrize("limit,accepted", [(12000, False), (48000, True)])
async def test_skill_loading_budget_reaches_actual_standard_loader(tmp_path, limit, accepted):
    from sagents.v2.skill import InMemorySkillProvider, InMemorySkillWorkspace, SkillBundle, SkillDescriptor
    source = InMemorySkillProvider((SkillBundle(descriptor=SkillDescriptor(name="large", description="Large", source_id="test"),
        files={"SKILL.md": b"x" * 30000}, content_hash="sha256:large"),))
    manifest = package()
    definition = manifest.agents["main"].model_copy(update={"skills": ("large",),
        "preload_skills": ("large",), "tools": ("load_skill",)})
    manifest = manifest.model_copy(update={"agents": {"main": definition}})
    model = ScriptedModelProvider((response(),))
    config = RuntimeConfig.model_validate({"capabilities": {
        "session.store": {"plugin": "sage.session.ephemeral"},
        "skill.loading": {"plugin": "sage.skill.loading.lazy", "config": {"max_active_characters": limit}},
        "agent.continuation-policy": {"plugin": "sage.agent.continuation.deterministic"},
        "tool.selection-policy": {"plugin": "sage.tool-selection.direct"},
    }})
    app = await build_registered_app(tmp_path, models=TEST_MODELS, model=model, runtime=config,
        skills=(source, source, InMemorySkillWorkspace()))
    try:
        agent = await app.load_agent(manifest)
        result, events = await run(app, agent, "skill-budget")
        if accepted:
            assert result.state.value == "completed", events
            assert model.requests and "x" * 30000 in model.requests[0].model_dump_json()
        else:
            # Preload rejection is observable; the oversized skill must not be
            # silently materialized or passed to the model.
            assert any("budget" in event.model_dump_json().lower() or "capacity" in event.model_dump_json().lower()
                       for event in events), events
            assert not any("x" * 30000 in request.model_dump_json() for request in model.requests)
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_run_factory_failure_rolls_back_prior_owned_capabilities(tmp_path):
    closed = []
    class Model(ScriptedModelProvider):
        async def close(self):
            closed.append("model")
    class Summarizer:
        async def close(self):
            closed.append("summarizer")
    def registration(capability, factory, dependencies=()):
        return ExtensionRegistration(descriptor=ExtensionDescriptor(
            plugin_id="test.failure." + capability, name=capability, version="1",
            provides=(CapabilityOffer(capability=capability, api_version="2"),),
            dependencies=tuple(ExtensionDependency(capability=value) for value in dependencies),
            supported_scopes=frozenset({ExtensionScope.RUN}),
            config_schema={"type": "object", "additionalProperties": False}), factory=factory)
    def fail(scope, dependencies):
        assert isinstance(dependencies.require("context.summarizer"), Summarizer)
        raise ValueError("later capability factory failed")
    registrations = (
        registration("model.provider", lambda scope, deps: Model((response(),))),
        registration("context.summarizer", lambda scope, deps: Summarizer()),
        registration("agent.continuation-policy", fail, ("context.summarizer",)),
    )
    config = RuntimeConfig.model_validate({"capabilities": {
        "session.store": {"plugin": "sage.session.ephemeral"},
        **{capability: {"plugin": "test.failure." + capability, "scope": "run"}
           for capability in ("model.provider", "context.summarizer", "agent.continuation-policy")},
    }})
    app = await build_registered_app(tmp_path, runtime=config, models=TEST_MODELS, registrations=registrations)
    try:
        agent = await app.load_agent(package())
        result, events = await run(app, agent, "rollback")
        assert result.state.value in {"failed", "suspended"}, events
        assert sorted(closed) == ["model", "summarizer"]
        assert any("later capability factory failed" in event.model_dump_json() for event in events)
    finally:
        await app.close()
    assert sorted(closed) == ["model", "summarizer"]


@pytest.mark.asyncio
async def test_selected_custom_policy_parameters_control_actual_run_and_frozen_revision(tmp_path):
    from sagents.v2.agent.policy.continuation import ContinuationDecision
    created = []
    class Policy:
        def __init__(self, count):
            self.count = count
        async def decide(self, context):
            return ContinuationDecision(action="complete_run" if context.step_number >= self.count else "continue_step",
                reason_code="test.configured", reason="Configured step count")
    def factory(scope, dependencies):
        created.append((scope.run_id, dict(scope.config)))
        return Policy(scope.config["steps"])
    registration = ExtensionRegistration(descriptor=ExtensionDescriptor(
        plugin_id="test.policy.steps", name="Step policy", version="1",
        provides=(CapabilityOffer(capability="agent.continuation-policy", api_version="2"),),
        supported_scopes=frozenset({ExtensionScope.RUN}),
        config_schema={"type": "object", "properties": {"steps": {"type": "integer", "minimum": 1}},
                       "required": ["steps"], "additionalProperties": False}), factory=factory)
    config = RuntimeConfig.model_validate({"capabilities": {
        "session.store": {"plugin": "sage.session.ephemeral"},
        "agent.continuation-policy": {"plugin": "test.policy.steps", "scope": "run", "config": {"steps": 2}},
    }})
    model = ScriptedModelProvider(tuple(response(text=f"step-{index}") for index in range(3)))
    app = await build_registered_app(tmp_path, runtime=config, models=TEST_MODELS, model=model, registrations=(registration,))
    try:
        original = await app.load_agent(package())
        first, events = await run(app, original, "two-steps")
        assert first.state.value == "completed", events
        assert len(model.requests) == 2
        current = app.runtime_configuration
        await app.update_runtime(current.model_copy(update={"capabilities": {**current.capabilities,
            "agent.continuation-policy": CapabilitySelection(plugin="test.policy.steps", scope="run", config={"steps": 1})}}))
        updated = await app.update_agent(agent=original, package=package())
        second, events = await run(app, updated, "one-step")
        assert second.state.value == "completed", events
        assert len(model.requests) == 3
        from tests.sagents.v2.test_standard_execution_configuration import CONTEXT
        before = await app.run_configuration(first.run_id, CONTEXT)
        after = await app.run_configuration(second.run_id, CONTEXT)
        assert before["runtime"]["capabilities"]["agent.continuation-policy"]["config"] == {"steps": 2}
        assert after["runtime"]["capabilities"]["agent.continuation-policy"]["config"] == {"steps": 1}
        assert before["composition_hash"] != after["composition_hash"]
        assert created == [(first.run_id, {"steps": 2}), (second.run_id, {"steps": 1})]
    finally:
        await app.close()
