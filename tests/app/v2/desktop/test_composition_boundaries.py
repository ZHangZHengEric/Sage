"""Desktop composition responsibilities can be exercised without a running host."""

from copy import deepcopy

import pytest

from app.v2.desktop.backend.catalog import (
    DesktopAgentRecord,
    DesktopModelProviderRecord,
    DesktopModelCompatibilityProfile,
)
from app.v2.desktop.backend.component_plan import DesktopComponentPlan
from app.v2.desktop.backend.model_providers import DesktopModelProviders
from app.v2.desktop.backend.schemas import DesktopV2Settings
from sagents.v2.model.middleware.concurrency import ModelConcurrencyBudget


def agent(**config):
    return DesktopAgentRecord(agent_id="a", user_id="u", name="A", config=config)


def provider(**updates):
    return DesktopModelProviderRecord(
        id="p",
        user_id="u",
        name="P",
        model="gpt-5",
        base_url="https://example.invalid/v1",
        api_key="secret",
    ).model_copy(update=updates)


@pytest.mark.parametrize(
    "protocol",
    [
        "openai-chat-completions",
        "openai-responses",
        "anthropic-messages",
        "gemini-generate-content",
    ],
)
@pytest.mark.parametrize("thinking", [False, True])
def test_verified_legacy_profile_keeps_request_contract(protocol, thinking):
    profile = DesktopModelCompatibilityProfile(
        route_fingerprint="verified",
        max_output_tokens_field="max_completion_tokens",
        effective_max_output_tokens=1234,
        reasoning_disable_strategy="thinking_type_disabled",
        supported_reasoning_efforts=("high",),
    )
    route = DesktopModelProviders.route(
        provider(protocol=protocol),
        agent(deepThinking=thinking, thinkingLevel="high"),
        compatibility_profile=profile,
    )
    assert route.request.max_output_tokens == route.limits.max_output_tokens == 1234
    assert route.request.reasoning_effort == ("high" if thinking else None)
    expected = {} if thinking else {"thinking": {"type": "disabled"}}
    if protocol == "openai-chat-completions":
        expected["max_output_tokens_field"] = "max_completion_tokens"
    assert route.request.extra == expected


def test_auxiliary_reasoning_request_does_not_send_minimal_effort():
    route = DesktopModelProviders.route(
        provider(protocol="openai-chat-completions"),
        agent(deepThinking=True),
        enable_thinking=False,
    )
    assert route.request.reasoning_effort is None
    assert route.request.extra == {"reasoning_parameter_fallback": True}


def test_provider_cache_isolates_credentials_agents_and_request_modes(monkeypatch):
    monkeypatch.setattr(
        "app.v2.desktop.backend.model_providers.create_registered_model_provider",
        lambda *args, **kwargs: object(),
    )
    models = DesktopModelProviders(ModelConcurrencyBudget(2))
    record, owner = provider(), agent()
    first = models.get(record, owner)
    assert models.get(record, owner) is first
    assert (
        models.get(record.model_copy(update={"api_key": "rotated"}), owner) is not first
    )
    assert models.get(record, owner.model_copy(update={"agent_id": "b"})) is not first
    assert models.get(record, owner, enable_thinking=False) is not first
    models.clear()
    assert models.get(record, owner) is not first


def test_component_plan_uses_snapshot_precedence_without_mutating_inputs(tmp_path):
    owner = agent(toolSelection={"plugin": "sage.tool-selection.direct"})
    settings = DesktopV2Settings(
        component_selections={"tool.selection-policy": "sage.tool-selection.lexical"},
        component_configs={"tool.selection-policy": {"max_visible_tools": 7}},
    )
    before = deepcopy(settings.model_dump())
    plan = DesktopComponentPlan.resolve(
        settings=settings,
        agent=owner,
        provider=provider(),
        judge_provider=provider(id="fast"),
        runtime_root=tmp_path,
        summary_store_plugin_id="sage.context.summary-store.session-derived",
    )
    assert (
        plan.manifest.runtime.capabilities["tool.selection-policy"].plugin
        == "sage.tool-selection.lexical"
    )
    assert plan.tool_selection_config["max_visible_tools"] == 7
    assert settings.model_dump() == before
    assert owner.config["toolSelection"]["plugin"] == "sage.tool-selection.direct"
    models = [object() for _ in range(3)]
    locked = plan.locked_configs(
        primary=models[0], judge=models[1], memory_query=models[2]
    )
    assert locked["context.summarizer"]["model"] is models[0]
    assert locked["agent.continuation-policy"]["model"] is models[1]
    assert "secret" not in repr(plan.cache_identities)
