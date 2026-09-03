from __future__ import annotations

import pytest

from sagents.v2.model.contracts import ModelResponse, ModelToolCall
from sagents.v2.agent.policy.continuation import (
    CompositeContinuationPolicy,
    ContinuationAction,
    ContinuationContext,
    ToolOrTextRule,
)
from sagents.v2.agent.policy.tool_policy import (
    EXACT_ARGUMENTS_MATCHER_ID,
    ApprovalMatcher,
    ApprovalStrategy,
    DefaultToolPolicy,
    ToolOperationAssessment,
    ToolPolicyAction,
    ToolPolicyContext,
)
from sagents.v2.tool.contracts import (
    SideEffectLevel,
    ToolCall,
    ToolDefinition,
)
from sagents.v2.contracts.principals import ActorRef, PrincipalType


def response(*, text="done", tools=()):
    return ModelResponse(
        response_id="response_1",
        text=text,
        tool_calls=tools,
        finish_reason="tool_calls" if tools else "stop",
    )


def continuation_context(**updates):
    values = dict(
        run_id="run_1",
        step_number=1,
        max_steps=10,
        response=response(),
    )
    values.update(updates)
    return ContinuationContext(**values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "action", "reason"),
    [
        ({}, ContinuationAction.COMPLETE_RUN, "text.final"),
        (
            {
                "response": response(
                    text="",
                    tools=(
                        ModelToolCall(tool_call_id="call_1", name="read", arguments={}),
                    ),
                )
            },
            ContinuationAction.CONTINUE_STEP,
            "tool.pending",
        ),
        (
            {"response": response(text="")},
            ContinuationAction.CONTINUE_STEP,
            "response.empty",
        ),
        (
            {"explicit_status": "complete"},
            ContinuationAction.COMPLETE_RUN,
            "status.complete",
        ),
        (
            {"explicit_status": "continue"},
            ContinuationAction.CONTINUE_STEP,
            "status.continue",
        ),
        (
            {"explicit_status": "task_done"},
            ContinuationAction.COMPLETE_RUN,
            "status.complete",
        ),
        (
            {"explicit_status": "continue_work"},
            ContinuationAction.CONTINUE_STEP,
            "status.continue",
        ),
        (
            {
                "explicit_status": "need_user_input",
                "explicit_status_note": "Please choose a target.",
            },
            ContinuationAction.REQUEST_INTERACTION,
            "status.need_user_input",
        ),
        (
            {"explicit_status": "blocked"},
            ContinuationAction.REQUEST_INTERACTION,
            "status.blocked",
        ),
        (
            {"explicit_status": "failed"},
            ContinuationAction.REQUEST_INTERACTION,
            "status.failed",
        ),
        (
            {"explicit_status": "unexpected"},
            ContinuationAction.REQUEST_INTERACTION,
            "status.invalid",
        ),
        (
            {
                "explicit_status": "task_done",
                "response": response(text=""),
            },
            ContinuationAction.CONTINUE_STEP,
            "status.explanation_required",
        ),
        (
            {"repeated_fingerprint_count": 3},
            ContinuationAction.REQUEST_INTERACTION,
            "loop.repeated_pattern",
        ),
        (
            {"flow_boundary": "complete_node"},
            ContinuationAction.COMPLETE_TURN,
            "flow.node_complete",
        ),
        (
            {"flow_boundary": "continue_node"},
            ContinuationAction.CONTINUE_STEP,
            "flow.node_continue",
        ),
        (
            {"flow_boundary": "unexpected"},
            ContinuationAction.FAIL,
            "flow.invalid_boundary",
        ),
    ],
)
async def test_default_continuation_decision_matrix(updates, action, reason):
    decision = await CompositeContinuationPolicy().decide(
        continuation_context(**updates)
    )
    assert decision.action == action
    assert decision.reason_code == reason


@pytest.mark.asyncio
async def test_explicit_input_status_preserves_prompt_and_allowed_decisions():
    decision = await CompositeContinuationPolicy().decide(
        continuation_context(
            explicit_status="need_user_input",
            explicit_status_note="Which environment should I deploy to?",
        )
    )

    assert decision.interaction is not None
    assert decision.interaction.allowed_decisions == ("submit", "cancel")
    assert decision.interaction.payload["status"] == "need_user_input"
    assert decision.interaction.payload["prompt"] == (
        "Which environment should I deploy to?"
    )
    assert decision.interaction.payload["questions"]
    assert decision.interaction.payload["language"] == "en"


@pytest.mark.asyncio
async def test_flow_boundary_never_skips_tool_dispatch():
    decision = await CompositeContinuationPolicy().decide(
        continuation_context(
            flow_boundary="complete_node",
            response=response(
                text="working",
                tools=(
                    ModelToolCall(
                        tool_call_id="call_flow",
                        name="read",
                        arguments={},
                    ),
                ),
            ),
        )
    )

    assert decision.action == ContinuationAction.CONTINUE_STEP
    assert decision.reason_code == "tool.pending"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "action", "reason"),
    [
        (
            {
                "step_number": 3,
                "max_steps": 3,
                "response": response(text=""),
            },
            ContinuationAction.REQUEST_INTERACTION,
            "budget.max_steps",
        ),
        (
            {"total_tokens": 100, "max_total_tokens": 100},
            ContinuationAction.FAIL,
            "budget.max_tokens",
        ),
        (
            {"elapsed_seconds": 10, "deadline_seconds": 10},
            ContinuationAction.FAIL,
            "budget.deadline",
        ),
    ],
)
async def test_budget_has_priority_over_continue_and_loop_recovery(
    updates, action, reason
):
    updates["repeated_fingerprint_count"] = 10
    decision = await CompositeContinuationPolicy().decide(
        continuation_context(**updates)
    )
    assert decision.action == action
    assert decision.reason_code == reason


@pytest.mark.asyncio
async def test_final_text_at_last_allowed_step_can_complete():
    decision = await CompositeContinuationPolicy().decide(
        continuation_context(
            step_number=3, max_steps=3, response=response(text="final")
        )
    )
    assert decision.action == ContinuationAction.COMPLETE_RUN


@pytest.mark.asyncio
async def test_pending_tool_call_cannot_be_misclassified_as_final_text():
    decision = await ToolOrTextRule().evaluate(
        continuation_context(
            response=response(text="I will do it"), pending_tool_calls=1
        )
    )
    assert decision.action == ContinuationAction.CONTINUE_STEP
    assert decision.reason_code == "tool.pending"


@pytest.mark.asyncio
async def test_continuation_decision_hash_is_stable_and_sensitive():
    policy = CompositeContinuationPolicy()
    first = await policy.decide(continuation_context())
    repeat = await policy.decide(continuation_context())
    changed = await policy.decide(continuation_context(response=response(text="")))
    assert first.stable_hash() == repeat.stable_hash()
    assert first.stable_hash() != changed.stable_hash()


def tool_definition(
    level=SideEffectLevel.NONE,
    *,
    scopes=(),
    requires_approval=False,
    plan_safe=False,
):
    return ToolDefinition(
        name="tool",
        description="test",
        input_schema={"type": "object"},
        side_effect_level=level,
        required_scopes=scopes,
        requires_approval=requires_approval,
        plan_safe=plan_safe,
    )


def tool_context(definition, *, actor_scopes=(), arguments=None):
    return ToolPolicyContext(
        run_id="run_1",
        actor=ActorRef(
            principal_id="agent_1",
            principal_type=PrincipalType.AGENT,
            scopes=actor_scopes,
        ),
        definition=definition,
        call=ToolCall(
            tool_call_id="call_1",
            tool_name="tool",
            arguments={"path": "a.txt"} if arguments is None else arguments,
            operation_id="operation_1",
            idempotency_key="key_1",
            owner_run_id="run_1",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (SideEffectLevel.NONE, ToolPolicyAction.ALLOW),
        (SideEffectLevel.READ, ToolPolicyAction.ALLOW),
        (SideEffectLevel.WRITE, ToolPolicyAction.REQUIRE_INTERACTION),
        (SideEffectLevel.REVERSIBLE, ToolPolicyAction.REQUIRE_INTERACTION),
        (SideEffectLevel.IRREVERSIBLE, ToolPolicyAction.REQUIRE_INTERACTION),
    ],
)
async def test_default_tool_side_effect_policy_matrix(level, expected):
    decision = await DefaultToolPolicy().decide(tool_context(tool_definition(level)))
    assert decision.action == expected
    assert decision.policy_hash.startswith("sha256:")
    if expected == ToolPolicyAction.REQUIRE_INTERACTION:
        assert decision.allowed_decisions == ("approve_once", "deny", "cancel")
        assert decision.interaction_payload["arguments"] == {"path": "a.txt"}


@pytest.mark.asyncio
async def test_required_actor_scope_denies_before_approval():
    policy = DefaultToolPolicy()
    denied = await policy.decide(
        tool_context(
            tool_definition(SideEffectLevel.WRITE, scopes=("filesystem:write",))
        )
    )
    allowed_to_ask = await policy.decide(
        tool_context(
            tool_definition(SideEffectLevel.WRITE, scopes=("filesystem:write",)),
            actor_scopes=("filesystem:write",),
        )
    )
    assert denied.action == ToolPolicyAction.DENY
    assert "filesystem:write" in denied.reason
    assert allowed_to_ask.action == ToolPolicyAction.REQUIRE_INTERACTION


@pytest.mark.asyncio
async def test_explicit_approval_flag_applies_even_to_read_only_tool():
    decision = await DefaultToolPolicy().decide(
        tool_context(tool_definition(SideEffectLevel.READ, requires_approval=True))
    )
    assert decision.action == ToolPolicyAction.REQUIRE_INTERACTION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("strategy", "level", "expected"),
    [
        (
            ApprovalStrategy.ALWAYS_ASK,
            SideEffectLevel.READ,
            ToolPolicyAction.REQUIRE_INTERACTION,
        ),
        (
            ApprovalStrategy.HIGH_RISK,
            SideEffectLevel.WRITE,
            ToolPolicyAction.ALLOW,
        ),
        (
            ApprovalStrategy.HIGH_RISK,
            SideEffectLevel.IRREVERSIBLE,
            ToolPolicyAction.REQUIRE_INTERACTION,
        ),
        (
            ApprovalStrategy.AUTO_APPROVE,
            SideEffectLevel.IRREVERSIBLE,
            ToolPolicyAction.ALLOW,
        ),
    ],
)
async def test_approval_strategy_matrix(strategy, level, expected):
    decision = await DefaultToolPolicy(approval_strategy=strategy).decide(
        tool_context(tool_definition(level))
    )

    assert decision.action == expected


@pytest.mark.asyncio
async def test_risk_based_approval_honors_explicit_tool_declaration():
    decision = await DefaultToolPolicy(
        approval_strategy=ApprovalStrategy.HIGH_RISK
    ).decide(
        tool_context(tool_definition(SideEffectLevel.READ, requires_approval=True))
    )

    assert decision.action == ToolPolicyAction.REQUIRE_INTERACTION


@pytest.mark.asyncio
async def test_call_specific_assessment_can_allow_safe_irreversible_tool_call():
    policy = DefaultToolPolicy(
        approval_strategy=ApprovalStrategy.HIGH_RISK,
        operation_assessor=lambda _context: ToolOperationAssessment(
            action=ToolPolicyAction.ALLOW,
            reason="known safe read-only command",
            category="safe_command",
            side_effect_level=SideEffectLevel.READ,
        ),
        operation_assessor_id="test/v1",
    )

    decision = await policy.decide(
        tool_context(
            tool_definition(
                SideEffectLevel.IRREVERSIBLE,
                requires_approval=True,
            )
        )
    )

    assert decision.action == ToolPolicyAction.ALLOW
    assert decision.reason == "known safe read-only command"


@pytest.mark.asyncio
async def test_call_specific_assessment_exposes_concrete_risk_to_interaction():
    policy = DefaultToolPolicy(
        approval_strategy=ApprovalStrategy.HIGH_RISK,
        operation_assessor=lambda _context: ToolOperationAssessment(
            action=ToolPolicyAction.REQUIRE_INTERACTION,
            reason="command deletes workspace files",
            category="filesystem_delete",
            side_effect_level=SideEffectLevel.IRREVERSIBLE,
        ),
    )

    decision = await policy.decide(
        tool_context(tool_definition(SideEffectLevel.IRREVERSIBLE))
    )

    assert decision.action == ToolPolicyAction.REQUIRE_INTERACTION
    assert decision.interaction_payload["risk_reason"] == (
        "command deletes workspace files"
    )
    assert decision.interaction_payload["risk_category"] == "filesystem_delete"


@pytest.mark.asyncio
async def test_call_specific_denial_is_never_bypassed_by_auto_approval():
    policy = DefaultToolPolicy(
        approval_strategy=ApprovalStrategy.AUTO_APPROVE,
        operation_assessor=lambda _context: ToolOperationAssessment(
            action=ToolPolicyAction.DENY,
            reason="blocked system operation",
        ),
    )

    decision = await policy.decide(tool_context(tool_definition()))

    assert decision.action == ToolPolicyAction.DENY
    assert decision.reason == "blocked system operation"


@pytest.mark.asyncio
async def test_auto_approval_never_bypasses_actor_scope():
    decision = await DefaultToolPolicy(
        approval_strategy=ApprovalStrategy.AUTO_APPROVE
    ).decide(
        tool_context(
            tool_definition(
                SideEffectLevel.IRREVERSIBLE,
                scopes=("filesystem:write",),
            )
        )
    )

    assert decision.action == ToolPolicyAction.DENY


@pytest.mark.asyncio
async def test_plan_mode_denies_write_even_with_auto_approval():
    decision = await DefaultToolPolicy(
        approval_strategy=ApprovalStrategy.AUTO_APPROVE
    ).decide(
        tool_context(tool_definition(SideEffectLevel.WRITE)).model_copy(
            update={"invocation_mode": "plan"}
        )
    )

    assert decision.action == ToolPolicyAction.DENY
    assert "Plan mode" in decision.reason


@pytest.mark.asyncio
async def test_plan_mode_allows_explicit_run_control_mutation():
    decision = await DefaultToolPolicy(
        approval_strategy=ApprovalStrategy.AUTO_APPROVE
    ).decide(
        tool_context(tool_definition(SideEffectLevel.WRITE, plan_safe=True)).model_copy(
            update={"invocation_mode": "plan"}
        )
    )

    assert decision.action == ToolPolicyAction.ALLOW


@pytest.mark.asyncio
async def test_tool_policy_decision_id_is_deterministic_per_call_and_policy():
    policy = DefaultToolPolicy(policy_version="7")
    first = await policy.decide(tool_context(tool_definition()))
    repeat = await policy.decide(tool_context(tool_definition()))
    assert first == repeat
    assert first.policy_version == "7"


# ---------- 审批记忆：策略侧只回答"可否记住 + 按什么匹配器记" ----------


@pytest.mark.asyncio
async def test_default_policy_never_marks_a_decision_persistent():
    decision = await DefaultToolPolicy().decide(
        tool_context(tool_definition(SideEffectLevel.WRITE))
    )

    assert decision.action == ToolPolicyAction.REQUIRE_INTERACTION
    assert decision.persistent_approval_allowed is False
    assert decision.approval_matcher is None
    assert "approve_and_remember" not in decision.allowed_decisions
    assert "approval_matcher" not in decision.interaction_payload


@pytest.mark.asyncio
async def test_persistent_policy_exposes_exact_matcher_but_leaves_offering_to_loop():
    policy = DefaultToolPolicy(allow_persistent_approval=True)
    decision = await policy.decide(tool_context(tool_definition(SideEffectLevel.WRITE)))

    assert decision.persistent_approval_allowed is True
    matcher = decision.approval_matcher
    assert matcher is not None
    assert matcher.tool_name == "tool"
    assert matcher.fingerprint.startswith("sha256:")
    assert matcher.summary == 'tool {"path":"a.txt"}'
    assert matcher.key == f"tool:{matcher.fingerprint}"
    assert decision.interaction_payload["approval_matcher"] == matcher.model_dump(
        mode="json"
    )
    # 能否真的"记住"取决于 Loop 是否持有记忆端口；策略本身不提供该选项。
    assert decision.allowed_decisions == ("approve_once", "deny", "cancel")
    assert policy.approval_matcher_id == EXACT_ARGUMENTS_MATCHER_ID


@pytest.mark.asyncio
async def test_exact_matcher_is_deterministic_and_argument_sensitive():
    policy = DefaultToolPolicy(allow_persistent_approval=True)
    definition = tool_definition(SideEffectLevel.WRITE)
    first = await policy.decide(tool_context(definition))
    repeat = await policy.decide(tool_context(definition))
    reordered = await policy.decide(
        tool_context(definition, arguments={"path": "a.txt"})
    )
    other = await policy.decide(tool_context(definition, arguments={"path": "b.txt"}))

    assert first.approval_matcher == repeat.approval_matcher == reordered.approval_matcher
    assert first.approval_matcher != other.approval_matcher


@pytest.mark.asyncio
async def test_always_ask_never_allows_persistent_approval():
    policy = DefaultToolPolicy(
        approval_strategy=ApprovalStrategy.ALWAYS_ASK, allow_persistent_approval=True
    )
    decision = await policy.decide(tool_context(tool_definition(SideEffectLevel.READ)))

    assert decision.action == ToolPolicyAction.REQUIRE_INTERACTION
    assert decision.persistent_approval_allowed is False
    assert decision.approval_matcher is None


@pytest.mark.asyncio
async def test_assessor_decides_persistence_when_present():
    def allow_remember(context):
        del context
        return ToolOperationAssessment(
            action=ToolPolicyAction.REQUIRE_INTERACTION,
            reason="risky",
            persistent_approval_allowed=True,
        )

    def forbid_remember(context):
        del context
        return ToolOperationAssessment(
            action=ToolPolicyAction.REQUIRE_INTERACTION, reason="too risky"
        )

    context = tool_context(tool_definition(SideEffectLevel.WRITE))
    allowed = await DefaultToolPolicy(operation_assessor=allow_remember).decide(context)
    forbidden = await DefaultToolPolicy(
        operation_assessor=forbid_remember, allow_persistent_approval=True
    ).decide(context)

    # 既有行为保持：assessor 允许时策略直接给出 approve_and_remember（宿主自行落地）。
    assert "approve_and_remember" in allowed.allowed_decisions
    assert allowed.persistent_approval_allowed is True
    assert allowed.approval_matcher is not None
    # assessor 逐次判断优先：它说不能记，policy 级开关不能放宽。
    assert forbidden.persistent_approval_allowed is False
    assert forbidden.approval_matcher is None
    assert "approve_and_remember" not in forbidden.allowed_decisions


@pytest.mark.asyncio
async def test_custom_matcher_can_opt_a_call_out_and_is_part_of_policy_hash():
    def path_matcher(context):
        path = str(context.call.arguments.get("path"))
        if path == "secret.txt":
            return None
        return ApprovalMatcher(
            tool_name=context.definition.name,
            fingerprint=f"path:{path}",
            summary=f"{context.definition.name} {path}",
        )

    policy = DefaultToolPolicy(
        allow_persistent_approval=True,
        approval_matcher=path_matcher,
        approval_matcher_id="test.path-matcher/v1",
    )
    definition = tool_definition(SideEffectLevel.WRITE)
    normal = await policy.decide(tool_context(definition))
    secret = await policy.decide(
        tool_context(definition, arguments={"path": "secret.txt"})
    )

    assert normal.approval_matcher is not None
    assert normal.approval_matcher.fingerprint == "path:a.txt"
    assert secret.persistent_approval_allowed is False
    assert secret.approval_matcher is None
    assert policy.approval_matcher_id == "test.path-matcher/v1"
    hashes = {
        DefaultToolPolicy().policy_hash,
        DefaultToolPolicy(allow_persistent_approval=True).policy_hash,
        policy.policy_hash,
    }
    assert len(hashes) == 3
