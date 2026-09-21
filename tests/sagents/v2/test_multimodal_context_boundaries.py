from __future__ import annotations


from sagents.v2.agent.policy.judge import LLMContinuationJudge
from sagents.v2.context.assembler import DefaultContextAssembler
from sagents.v2.context.contracts import ContextSegment, ContextStability
from sagents.v2.context.partition import conversation_units, current_turn_boundary
from sagents.v2.contracts.conversation import order_tool_context
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.model.contracts import ModelMessage, ModelToolCall


def ledger():
    return (
        ModelMessage(
            role="user", content=(TextBlock(text="Compare images and write report"),)
        ),
        ModelMessage(
            role="assistant",
            tool_calls=(
                ModelToolCall(tool_call_id="a", name="analyze_image", arguments={}),
                ModelToolCall(tool_call_id="b", name="write_report", arguments={}),
            ),
        ),
        ModelMessage(
            role="tool", tool_call_id="a", content=(TextBlock(text="attached"),)
        ),
        ModelMessage(
            role="user",
            content=(
                TextBlock(text="Inspect frame"),
                ImageBlock(uri="data:image/png;base64,AAAA", mime_type="image/png"),
            ),
            metadata={"tool_source": "analyze_image", "hidden_from_chat": True},
        ),
        ModelMessage(
            role="tool", tool_call_id="b", content=(TextBlock(text="written"),)
        ),
    )


def test_tool_image_does_not_replace_real_request_or_runtime_context():
    messages = order_tool_context(ledger())
    assert current_turn_boundary(conversation_units(messages)) == 0
    assert LLMContinuationJudge._recent_request_trace(messages) == messages
    wrapped = DefaultContextAssembler._inject_latest_user(
        messages,
        (
            ContextSegment(
                segment_id="runtime",
                content="workspace context",
                stability=ContextStability.VOLATILE,
            ),
        ),
    )
    assert "<runtime_context>" in wrapped[0].content[0].text
    assert wrapped[-1] == messages[-1]
    next_user = ModelMessage(role="user", content=(TextBlock(text="New task"),))
    assert LLMContinuationJudge._recent_request_trace((*messages, next_user)) == (
        next_user,
    )


def test_resumed_image_batch_preserves_all_tool_pairs_and_image():
    result = DefaultContextAssembler._sanitize_tool_pairs(ledger())
    assert [m.role for m in result] == ["user", "assistant", "tool", "tool", "user"]
    assert [m.tool_call_id for m in result if m.role == "tool"] == ["a", "b"]
    assert result[-1].content[-1].uri == "data:image/png;base64,AAAA"
    assert order_tool_context(result) == result


def test_reordering_never_crosses_real_user_boundary():
    messages = ledger()
    real_user = ModelMessage(role="user", content=(TextBlock(text="Stop"),))
    sequence = (*messages[:4], real_user, messages[4])
    assert order_tool_context(sequence) == sequence


def test_current_memory_recall_survives_image_followup():
    messages = ledger()
    memory = ModelMessage(
        role="assistant",
        tool_calls=(
            ModelToolCall(tool_call_id="memory", name="search_memory", arguments={}),
        ),
    )
    memory_result = ModelMessage(
        role="tool", tool_call_id="memory", content=(TextBlock(text="constraints"),)
    )
    sequence = (messages[0], memory, memory_result, *messages[1:])
    assert DefaultContextAssembler._strip_historical_search_memory(sequence) == sequence
