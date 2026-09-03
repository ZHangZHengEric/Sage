from __future__ import annotations

import asyncio
import json

import pytest

from sagents.prompts.simple_agent_prompts import task_complete_template
from sagents.v2.agent.policy import (
    ContinuationAction,
    ContinuationContext,
    ExplicitStatusContinuationPolicy,
    HybridContinuationPolicy,
    InteractionDraft,
    LLMContinuationJudge,
    LLMJudgeContinuationPolicy,
)
from sagents.v2.agent.policy.legacy_v1_judge_prompt import (
    LEGACY_V1_TASK_COMPLETE_TEMPLATE,
)
from sagents.v2.contracts.items import JsonBlock, TextBlock, UsageSummary
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.model import (
    ModelEventKind,
    ModelMessage,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)


def _response(text: str = "Work is complete.", *, tools=()) -> ModelResponse:
    return ModelResponse(
        response_id="main_response",
        text=text,
        tool_calls=tools,
        finish_reason="tool_calls" if tools else "stop",
    )


def _context(**updates) -> ContinuationContext:
    values = {
        "run_id": "run_1",
        "step_number": 1,
        "max_steps": 10,
        "response": _response(),
        "language": "en",
        "agent_system_requirements": "Create files only after verification.",
        "available_tools": ("file_write", "todo_write"),
        "ledger": (
            ModelMessage(role="user", content=(TextBlock(text="Create the report."),)),
            ModelMessage(
                role="assistant", content=(TextBlock(text="Work is complete."),)
            ),
        ),
    }
    values.update(updates)
    return ContinuationContext(**values)


def _judge_step(
    decision: str,
    *,
    reason: str = "The requested result is present.",
    usage: UsageSummary | None = None,
    assertion=None,
) -> ScriptedModelStep:
    return ScriptedModelStep(
        assertion=assertion,
        events=(
            ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="judge_response",
                    text=json.dumps({"decision": decision, "reason": reason}),
                    finish_reason="stop",
                    usage=usage or UsageSummary(),
                ),
            ),
        ),
    )


class SlowModel:
    def stream(self, request):
        async def events():
            await asyncio.sleep(60)
            if False:
                yield None

        return events()


def test_v2_vendors_the_v1_judge_prompts_without_modification():
    assert LEGACY_V1_TASK_COMPLETE_TEMPLATE == task_complete_template


@pytest.mark.asyncio
async def test_llm_judge_uses_v1_prompt_contract_and_reports_usage():
    def assert_request(request):
        assert request.model_binding == "fast"
        assert request.max_output_tokens is None
        assert request.response_format == "json_object"
        assert request.response_schema is None
        assert request.tools == ()
        assert request.metadata == {
            "purpose": "continuation_judge",
            "implementation": "v1",
        }
        prompt = request.messages[0].content[0].text
        assert "Apply the Todo invariant first" in prompt
        assert "Create the report." in prompt
        assert "Create files only after verification." in prompt
        assert '["file_write", "todo_write"]' in prompt
        assert "confidence" not in prompt

    model = ScriptedModelProvider(
        (
            _judge_step(
                "completed",
                usage=UsageSummary(input_tokens=17, output_tokens=5),
                assertion=assert_request,
            ),
        )
    )
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(model))

    decision = await policy.decide(_context())

    assert decision.action == ContinuationAction.COMPLETE_RUN
    assert decision.reason_code == "judge.completed"
    assert decision.usage.input_tokens == 17
    assert decision.usage.output_tokens == 5
    assert decision.metadata == {"policy": "llm_judge", "implementation": "v1"}


@pytest.mark.asyncio
async def test_llm_judge_timeout_is_reported_by_selected_plugin():
    policy = LLMJudgeContinuationPolicy(
        LLMContinuationJudge(SlowModel(), timeout_seconds=0.01)
    )

    with pytest.raises(SageV2Error) as caught:
        await policy.decide(_context())

    assert caught.value.info.code == "agent.continuation.judge_timeout"
    assert caught.value.info.category == ErrorCategory.PROVIDER_TRANSIENT
    assert caught.value.info.metadata["plugin_id"] == (
        "sage.agent.continuation.llm-judge"
    )


@pytest.mark.asyncio
async def test_llm_judge_never_skips_an_unsettled_tool_result():
    model = ScriptedModelProvider(())
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(model))
    context = _context(
        response=_response(
            "",
            tools=(
                ModelToolCall(tool_call_id="call_1", name="file_read", arguments={}),
            ),
        )
    )

    decision = await policy.decide(context)

    assert decision.reason_code == "tool.pending"
    assert model.requests == []


@pytest.mark.parametrize(
    ("verdict", "expected_action", "expected_code"),
    [
        ("continue", ContinuationAction.CONTINUE_STEP, "judge.continue"),
        (
            "need_user_input",
            ContinuationAction.COMPLETE_RUN,
            "judge.need_user_input",
        ),
        ("blocked", ContinuationAction.REQUEST_INTERACTION, "judge.blocked"),
    ],
)
@pytest.mark.asyncio
async def test_llm_judge_preserves_all_v1_decisions(
    verdict, expected_action, expected_code
):
    model = ScriptedModelProvider((_judge_step(verdict, reason="v1 reason"),))
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(model))

    decision = await policy.decide(_context())

    assert decision.action == expected_action
    assert decision.reason_code == expected_code
    assert decision.reason == "v1 reason"
    assert "confidence" not in decision.metadata


@pytest.mark.asyncio
async def test_llm_judge_need_user_input_completes_without_interaction():
    model = ScriptedModelProvider(
        (_judge_step("need_user_input", reason="Choose the deployment target."),)
    )
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(model))

    decision = await policy.decide(
        _context(response=_response("Which deployment target should I use?"))
    )

    assert decision.action == ContinuationAction.COMPLETE_RUN
    assert decision.reason_code == "judge.need_user_input"
    assert decision.interaction is None
    assert decision.metadata["completion_status"] == "need_user_input"
    assert decision.metadata["needs_user_input"] is True


@pytest.mark.asyncio
async def test_llm_judge_preserves_explicit_questionnaire_interaction():
    model = ScriptedModelProvider(())
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(model))
    questionnaire = InteractionDraft(
        interaction_type="questionnaire",
        allowed_decisions=("submit", "cancel"),
        payload={
            "title": "Choose a target",
            "questions": [
                {
                    "id": "target",
                    "type": "single",
                    "title": "Where should I deploy?",
                    "options": ["staging", "production"],
                }
            ],
            "source": "questionnaire_async",
        },
    )

    decision = await policy.decide(
        _context(
            response=_response(
                "",
                tools=(
                    ModelToolCall(
                        tool_call_id="questionnaire_1",
                        name="questionnaire_async",
                        arguments={"questions": []},
                    ),
                ),
            ),
            explicit_status="need_user_input",
            explicit_status_note="Choose a target",
            requested_interaction=questionnaire,
        )
    )

    assert decision.action == ContinuationAction.REQUEST_INTERACTION
    assert decision.reason_code == "interaction.requested"
    assert decision.interaction == questionnaire
    assert decision.metadata["source"] == "explicit_interaction"
    assert model.requests == []


@pytest.mark.asyncio
async def test_llm_judge_repeated_plain_text_requests_recovery_guidance():
    ledger = (
        ModelMessage(role="user", content=(TextBlock(text="Find the questionnaire."),)),
        ModelMessage(role="assistant", content=(TextBlock(text="I checked here."),)),
        ModelMessage(role="assistant", content=(TextBlock(text="I checked there."),)),
        ModelMessage(
            role="assistant",
            content=(TextBlock(text="Which questionnaire do you mean?"),),
        ),
    )
    model = ScriptedModelProvider(
        (_judge_step("need_user_input", reason="The questionnaire is ambiguous."),)
    )
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(model))

    decision = await policy.decide(
        _context(
            response=_response("Which questionnaire do you mean?"),
            ledger=ledger,
        )
    )

    assert decision.action == ContinuationAction.REQUEST_INTERACTION
    assert decision.reason_code == "judge.plain_text_no_progress"
    assert decision.interaction is not None
    assert decision.interaction.interaction_type == "loop_recovery"
    assert decision.interaction.payload["stop_reason"] == "plain_text_no_progress"
    assert model.requests == []


@pytest.mark.asyncio
async def test_llm_judge_invalid_output_matches_v1_and_continues_once():
    invalid = ScriptedModelStep(
        events=(
            ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="invalid",
                    text="not-json",
                    finish_reason="stop",
                    usage=UsageSummary(input_tokens=3, output_tokens=1),
                ),
            ),
        )
    )
    model = ScriptedModelProvider((invalid,))
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(model))

    decision = await policy.decide(_context())

    assert decision.action == ContinuationAction.CONTINUE_STEP
    assert decision.reason_code == "judge.invalid_output"
    assert decision.reason == "completion Judge returned invalid JSON"
    assert "force_tool_choice_required_next" not in decision.metadata
    assert decision.usage.input_tokens == 3
    assert len(model.requests) == 1


@pytest.mark.asyncio
async def test_llm_judge_empty_output_has_a_stable_non_parser_reason():
    empty = ScriptedModelStep(
        events=(
            ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="empty",
                    text="",
                    finish_reason="stop",
                ),
            ),
        )
    )
    policy = LLMJudgeContinuationPolicy(
        LLMContinuationJudge(ScriptedModelProvider((empty,)))
    )

    decision = await policy.decide(_context())

    assert decision.reason_code == "judge.invalid_output"
    assert decision.reason == "completion Judge returned an empty response"
    assert "line 1 column 1" not in decision.reason


@pytest.mark.asyncio
async def test_llm_judge_propagates_permanent_provider_rejection():
    rejected = ScriptedModelStep(
        events=(),
        error=RuntimeErrorInfo(
            code="model.provider_permanent",
            category=ErrorCategory.PROVIDER_PERMANENT,
            message="reasoning_effort rejected",
            provider_code="422",
            safe_to_resume=True,
        ),
    )
    model = ScriptedModelProvider((rejected,))
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(model))

    with pytest.raises(SageV2Error) as caught:
        await policy.decide(_context())

    assert caught.value.info.code == "model.provider_permanent"
    assert caught.value.info.provider_code == "422"
    assert len(model.requests) == 1


@pytest.mark.asyncio
async def test_llm_judge_accepts_structured_verdict_from_reasoning_fallback():
    reasoning_only = ScriptedModelStep(
        events=(
            ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="reasoning_only",
                    text="",
                    reasoning=(
                        '{"decision":"completed","reason":"Result is present."}'
                    ),
                    finish_reason="stop",
                ),
            ),
        )
    )
    policy = LLMJudgeContinuationPolicy(
        LLMContinuationJudge(ScriptedModelProvider((reasoning_only,)))
    )

    decision = await policy.decide(_context())

    assert decision.action == ContinuationAction.COMPLETE_RUN
    assert decision.reason_code == "judge.completed"


@pytest.mark.asyncio
async def test_llm_judge_applies_v1_authoritative_todo_invariant():
    todo_call = ModelToolCall(
        tool_call_id="todo_1",
        name="todo_write",
        arguments={"tasks": []},
    )
    ledger = (
        ModelMessage(role="user", content=(TextBlock(text="Build it."),)),
        ModelMessage(role="assistant", tool_calls=(todo_call,)),
        ModelMessage(
            role="tool",
            tool_call_id="todo_1",
            content=(
                JsonBlock(
                    value={
                        "status": "success",
                        "tasks": [{"id": "1", "content": "Build", "status": "pending"}],
                    }
                ),
            ),
        ),
        ModelMessage(role="assistant", content=(TextBlock(text="Done."),)),
    )

    def assert_request(request):
        assert "<current_todo_plan>" in request.messages[0].content[0].text

    model = ScriptedModelProvider((_judge_step("completed", assertion=assert_request),))
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(model))

    decision = await policy.decide(_context(ledger=ledger))

    assert decision.action == ContinuationAction.CONTINUE_STEP
    assert decision.reason == "authoritative Todo still has pending/in_progress items"


@pytest.mark.asyncio
async def test_llm_judge_v1_continuation_punctuation_skips_judge():
    model = ScriptedModelProvider(())
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(model))

    decision = await policy.decide(
        _context(response=_response("Next:"), ledger=(_context().ledger[0],))
    )

    assert decision.reason_code == "judge.v1_must_continue"
    assert "force_tool_choice_required_next" not in decision.metadata
    assert model.requests == []


@pytest.mark.asyncio
async def test_hybrid_uses_explicit_status_without_calling_judge():
    model = ScriptedModelProvider(())
    policy = HybridContinuationPolicy(LLMContinuationJudge(model))

    decision = await policy.decide(_context(explicit_status="task_done"))

    assert decision.reason_code == "status.complete"
    assert model.requests == []


@pytest.mark.asyncio
async def test_hybrid_accepts_v1_judge_continuation():
    model = ScriptedModelProvider(
        (_judge_step("continue", reason="A required verification remains."),)
    )
    policy = HybridContinuationPolicy(LLMContinuationJudge(model))

    decision = await policy.decide(_context())

    assert decision.action == ContinuationAction.CONTINUE_STEP
    assert decision.reason_code == "judge.continue"
    assert decision.metadata["policy"] == "hybrid"


@pytest.mark.asyncio
async def test_hybrid_invalid_judge_output_falls_back_to_final_text():
    invalid = ScriptedModelStep(
        events=(
            ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="invalid",
                    text="{}",
                    finish_reason="stop",
                ),
            ),
        )
    )
    model = ScriptedModelProvider((invalid,))
    policy = HybridContinuationPolicy(LLMContinuationJudge(model))

    decision = await policy.decide(_context())

    assert decision.action == ContinuationAction.COMPLETE_RUN
    assert decision.reason_code == "hybrid.fallback_text_final"
    assert decision.metadata["fallback"] == "judge_invalid_output"


@pytest.mark.asyncio
async def test_explicit_status_only_requests_guidance_at_step_limit():
    policy = ExplicitStatusContinuationPolicy()

    missing = await policy.decide(_context())
    exhausted = await policy.decide(_context(step_number=10))
    complete = await policy.decide(_context(explicit_status="task_done"))

    assert missing.reason_code == "status.required"
    assert exhausted.action == ContinuationAction.REQUEST_INTERACTION
    assert exhausted.reason_code == "status.missing_at_limit"
    assert exhausted.interaction is not None
    assert complete.reason_code == "status.complete"
