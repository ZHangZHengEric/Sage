from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.context.messages.message_manager import MessageManager
from sagents.context.messages.token_accounting import (
    ContextViewSpec,
    MAX_CHECKPOINTS_PER_SESSION,
    PromptBudgetManager,
    PromptTokenEstimator,
)


def _provider_message(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def test_measure_inference_view_reports_per_message_and_prefix_totals():
    messages = [
        MessageChunk(role=MessageRole.USER.value, content="first", message_id="u1"),
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content="",
            message_id="a1",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "demo",
                        "arguments": '{"long_argument":"value"}',
                    },
                }
            ],
        ),
        MessageChunk(
            role=MessageRole.TOOL.value,
            content="tool result",
            tool_call_id="call-1",
            message_id="t1",
        ),
    ]

    report = MessageManager.measure_inference_view(
        messages,
        ContextViewSpec(policy_id="test"),
        through_message_id="a1",
        model_identity="model-a",
    )

    assert [item["message_id"] for item in report["messages"]] == ["u1", "a1"]
    assert report["messages"][1]["estimated_tokens"] > 0
    assert (
        report["messages"][1]["cumulative_estimated_tokens"]
        == report["total_estimated_tokens"]
    )
    assert (
        report["messages"][0]["cumulative_estimated_tokens"]
        < report["total_estimated_tokens"]
    )


def test_prompt_projection_uses_actual_baseline_plus_added_delta():
    manager = PromptBudgetManager()
    profile = manager.build_profile_id(
        model="model-a",
        provider_identity="provider-a",
        agent_class="AgentA",
        step_name="run",
        view_policy_id="default",
    )
    baseline_messages = [
        _provider_message("system", "stable system" * 100),
        _provider_message("user", "stable history" * 100),
    ]
    baseline = PromptTokenEstimator.manifest(
        baseline_messages,
        tools=[{"type": "function", "function": {"name": "demo"}}],
    )
    manager.update_checkpoint(profile, 2000, baseline)

    current = PromptTokenEstimator.manifest(
        [*baseline_messages, _provider_message("assistant", "new response")],
        tools=[{"type": "function", "function": {"name": "demo"}}],
    )
    projection = manager.project(profile, current)

    assert projection.source == "actual_delta"
    assert projection.actual_prompt_tokens == 2000
    assert projection.added_estimated_tokens > 0
    assert projection.projected_tokens > 2000
    assert projection.removed_estimated_tokens == 0


def test_unknown_tokenizer_estimate_accounts_for_high_risk_text_shapes():
    prose = PromptTokenEstimator.manifest(
        [_provider_message("user", "ordinary prose with spaces " * 100)]
    )
    cjk = PromptTokenEstimator.manifest(
        [_provider_message("user", "上下文压缩很容易低估中文分词" * 100)]
    )
    emoji = PromptTokenEstimator.manifest(
        [_provider_message("user", "🧑🏽‍💻🚀" * 100)]
    )
    opaque = PromptTokenEstimator.manifest(
        [_provider_message("user", "aB9_7KpQ2xYz0LmN4RtV8WcD6EfG1HiJ" * 100)]
    )

    assert prose.conservative_tokens >= prose.estimated_tokens
    assert cjk.conservative_tokens > cjk.estimated_tokens * 2
    assert emoji.conservative_tokens > emoji.estimated_tokens * 4
    assert opaque.conservative_tokens > opaque.estimated_tokens * 2


def test_dynamic_checkpoint_uses_calibrated_delta_and_keeps_risk_diagnostic():
    manager = PromptBudgetManager()
    baseline_messages = [_provider_message("system", "stable ascii prompt " * 100)]
    baseline = PromptTokenEstimator.manifest(baseline_messages)
    manager.update_checkpoint("profile", baseline.estimated_tokens, baseline)

    current = PromptTokenEstimator.manifest(
        [*baseline_messages, _provider_message("user", "🧑🏽‍💻🚀" * 500)]
    )
    projection = manager.project("profile", current)

    assert projection.source == "actual_delta"
    assert projection.projected_tokens < current.conservative_tokens
    assert projection.projected_tokens >= current.estimated_tokens
    assert projection.conservative_estimate == current.conservative_tokens


def test_uncalibrated_soft_trigger_uses_ordinary_estimate_not_worst_case_bound():
    manager = PromptBudgetManager()
    manifest = PromptTokenEstimator.manifest(
        [_provider_message("user", "🧑🏽‍💻🚀" * 500)]
    )

    projection = manager.project("new-profile", manifest)

    assert projection.source == "full_estimate"
    assert projection.projected_tokens == manifest.estimated_tokens
    assert projection.conservative_estimate > projection.projected_tokens


def test_request_profiles_isolate_agents_and_steps():
    manager = PromptBudgetManager()
    common = {
        "model": "model-a",
        "provider_identity": "provider-a",
        "view_policy_id": "default",
    }
    profile_a = manager.build_profile_id(
        **common, agent_class="AgentA", step_name="run"
    )
    profile_b = manager.build_profile_id(
        **common, agent_class="AgentB", step_name="run"
    )
    profile_step = manager.build_profile_id(
        **common, agent_class="AgentA", step_name="judge"
    )

    assert profile_a != profile_b
    assert profile_a != profile_step


def test_request_profile_normalizes_model_and_changes_with_view_spec():
    common = {
        "provider_identity": "HTTPS://PROVIDER.EXAMPLE ",
        "agent_class": "AgentA",
        "step_name": "run",
    }
    normalized = PromptBudgetManager.build_profile_id(
        **common,
        model=" MODEL-A ",
        view_policy_id=ContextViewSpec(policy_id="default").fingerprint(),
    )
    same = PromptBudgetManager.build_profile_id(
        **{**common, "provider_identity": "https://provider.example"},
        model="model-a",
        view_policy_id=ContextViewSpec(policy_id="default").fingerprint(),
    )
    changed_view = PromptBudgetManager.build_profile_id(
        **common,
        model="model-a",
        view_policy_id=ContextViewSpec(
            policy_id="default", recent_turns=3
        ).fingerprint(),
    )

    assert normalized == same
    assert normalized != changed_view


def test_input_limit_is_percentage_only_and_honors_explicit_input_cap():
    assert PromptBudgetManager.input_limit(100_000, 0.85) == 85_000
    assert PromptBudgetManager.input_limit(100_000, 0.70) == 70_000
    assert PromptBudgetManager.input_limit(100_000, 0.85, 60_000) == 60_000


def test_checkpoint_round_trip_contains_no_prompt_content():
    manager = PromptBudgetManager()
    manifest = PromptTokenEstimator.manifest(
        [_provider_message("user", "secret prompt content")]
    )
    manager.update_checkpoint("profile", 100, manifest)
    payload = manager.to_dict()

    assert "secret prompt content" not in str(payload)
    restored = PromptBudgetManager(payload)
    projection = restored.project("profile", manifest)
    assert projection.source == "actual_delta"
    assert projection.projected_tokens == 100


def test_low_overlap_falls_back_to_full_estimate():
    manager = PromptBudgetManager()
    old_manifest = PromptTokenEstimator.manifest(
        [_provider_message("user", "old context" * 100)]
    )
    manager.update_checkpoint("profile", 500, old_manifest)
    new_manifest = PromptTokenEstimator.manifest(
        [_provider_message("user", "entirely different" * 100)]
    )

    projection = manager.project("profile", new_manifest)

    assert projection.source == "full_estimate"
    assert projection.fallback_reason == "checkpoint_low_overlap"


def test_checkpoint_store_is_bounded_by_lru_limit():
    manager = PromptBudgetManager()
    manifest = PromptTokenEstimator.manifest([_provider_message("user", "message")])
    for index in range(MAX_CHECKPOINTS_PER_SESSION + 3):
        manager.update_checkpoint(f"profile-{index}", 100 + index, manifest)

    payload = manager.to_dict()
    assert len(payload) == MAX_CHECKPOINTS_PER_SESSION
    assert "profile-0" not in payload
    assert f"profile-{MAX_CHECKPOINTS_PER_SESSION + 2}" in payload
