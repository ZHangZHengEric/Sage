"""Public host composition keeps budget and prompt behavior consistent."""

from tests.sagents.v2.model_fixture import TEST_MODELS

from types import SimpleNamespace

import pytest

from sagents.v2.agent.factory import AgentCompositionFactory
from sagents.v2.context.assembler import StaticContextProvider
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.context.contracts import ContextSegment, ContextStability
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.package.presets import BuiltinPackageFactory
from sagents.v2.runtime.session import EphemeralSessionStore


def resolved():
    return CompositionResolver(models=TEST_MODELS).resolve(
        BuiltinPackageFactory.create(
            "assistant",
            package_id="context.test",

        )
    )


@pytest.mark.parametrize(
    "window,ceiling,output,expected",
    [
        (None, None, None, (32768, 0)),
        (64000, 24000, 4000, (24000, 4000)),
        (16000, 32000, 2000, (16000, 2000)),
    ],
)
def test_host_context_applies_route_and_policy_budget(
    window, ceiling, output, expected
):
    spec = resolved()
    agent_id = spec.entrypoint_agent
    route_id = spec.agents[agent_id].model_bindings["primary"]
    spec.model_routes[route_id]["limits"] = {
        "context_window": window,
        "max_output_tokens": 0,
    }
    spec.model_routes[route_id]["request"] = {"max_output_tokens": output}
    spec.policy_ceilings[agent_id] = spec.policy_ceilings[agent_id].model_copy(
        update={
            "max_input_tokens": ceiling,
            "max_output_tokens": None,
            "protected_recent_tokens": 0,
        }
    )
    context = AgentCompositionFactory(
        SimpleNamespace(session_store=EphemeralSessionStore())
    ).create_context(spec, agent_id)
    assert (
        context.budget.max_input_tokens,
        context.budget.reserve_output_tokens,
    ) == expected
    assert context.budget.protected_recent_tokens == 0


@pytest.mark.asyncio
async def test_custom_context_keeps_provider_order_explicit_instructions_and_ports():
    spec = resolved()
    providers = tuple(
        StaticContextProvider(
            (
                ContextSegment(
                    segment_id=name,
                    content=name,
                    stability=ContextStability.STABLE,
                ),
            )
        )
        for name in ("plan", "goal", "roster")
    )
    reducer, observer, artifacts = object(), object(), object()
    factory = AgentCompositionFactory(
        SimpleNamespace(session_store=EphemeralSessionStore()),
        context_components=ContextComponentBundle(reducer=reducer),
    )
    context = factory.create_context(
        spec,
        spec.entrypoint_agent,
        providers=providers,
        developer_instructions="",
        session_memory_service=observer,
        artifact_store=artifacts,
    )
    # An explicitly empty prompt must not silently restore manifest instructions.
    assert context.providers == providers
    assert context.reducer is reducer
    assert context.projection_observer is observer
    assert context.artifact_store is artifacts
    assert [
        segment.content
        for provider in context.providers
        for segment in await provider.segments(None)
    ] == ["plan", "goal", "roster"]


@pytest.mark.parametrize("options,match", [
    ({"completion_gates": ("typo",)}, "unknown completion gates"),
    ({"context_providers": (), "additional_context_providers": (object(),)},
     "choose explicit or additional"),
])
def test_loop_rejects_ambiguous_or_invalid_host_parameters(options, match):
    spec = resolved()
    factory = AgentCompositionFactory(SimpleNamespace(session_store=EphemeralSessionStore()))
    with pytest.raises(ValueError, match=match):
        factory.create_loop(
            spec, spec.entrypoint_agent, model=object(), tool_catalog=object(),
            tool_executor=object(), **options,
        )
