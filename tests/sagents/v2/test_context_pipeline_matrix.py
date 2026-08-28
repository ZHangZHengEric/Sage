from __future__ import annotations

import pytest

from sagents.v2.context import (
    ContextBudget,
    ContextPlacement,
    ContextSegment,
    ContextStability,
    DefaultContextAssembler,
    RunMetadataContextProvider,
    StaticContextProvider,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.model import ModelMessage, ModelToolCall
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import ImageBlock, TextBlock


def command(*, metadata=None):
    return StartRun(
        agent_id="agent_1",
        input=(InputItem(role="user", content=(TextBlock(text="question"),)),),
        config={"metadata": metadata or {}},
        resolved_spec_hash="sha256:spec",
        idempotency_key="start",
    )


@pytest.mark.asyncio
async def test_system_segments_are_fresh_ordered_and_never_stored_in_ledger():
    provider = StaticContextProvider(
        (
            ContextSegment(
                segment_id="volatile",
                content="now",
                stability=ContextStability.VOLATILE,
            ),
            ContextSegment(
                segment_id="skills",
                content="skills",
                stability=ContextStability.SEMI_STABLE,
            ),
            ContextSegment(
                segment_id="identity",
                content="identity",
                stability=ContextStability.STABLE,
            ),
        )
    )
    assembler = DefaultContextAssembler(
        developer_instructions="role",
        providers=(provider,),
        runtime_context_in_user=False,
    )
    ledger = await assembler.initial_ledger(command())
    first = await assembler.prepare_messages(command(), ledger)
    second = await assembler.prepare_messages(command(), ledger)
    assert all(message.role != "system" for message in ledger)
    assert [message.content[0].text for message in first[:-1]] == [
        "<role_definition>\nrole\n</role_definition>\nidentity",
        "skills",
        "now",
    ]
    assert first[0].metadata["context_segment_ids"] == (
        "agent_instructions",
        "identity",
    )
    assert first == second
    assert [message.metadata["cache_segment"] for message in first[:-1]] == [
        "stable",
        "semi_stable",
        "volatile",
    ]


@pytest.mark.asyncio
async def test_volatile_context_wraps_latest_user_and_preserves_multimodal_blocks():
    assembler = DefaultContextAssembler(
        providers=(
            StaticContextProvider(
                (
                    ContextSegment(
                        segment_id="runtime",
                        content="time=now",
                        stability=ContextStability.VOLATILE,
                    ),
                )
            ),
        )
    )
    ledger = (
        ModelMessage(role="user", content=(TextBlock(text="old"),)),
        ModelMessage(role="assistant", content=(TextBlock(text="answer"),)),
        ModelMessage(
            role="user",
            content=(
                TextBlock(text="new"),
                ImageBlock(uri="https://example.invalid/a.png", mime_type="image/png"),
            ),
        ),
    )
    prepared = await assembler.prepare_messages(command(), ledger)
    assert prepared[0].content[0].text == "old"
    assert "<runtime_context>\ntime=now" in prepared[-1].content[0].text
    assert prepared[-1].content[0].text.endswith("<user_request>")
    assert prepared[-1].content[1].text == "new"
    assert isinstance(prepared[-1].content[2], ImageBlock)
    assert prepared[-1].content[3].text == "</user_request>"


@pytest.mark.asyncio
async def test_tool_pair_sanitizer_keeps_complete_pairs_and_drops_orphans():
    complete_call = ModelToolCall(tool_call_id="call_1", name="one", arguments={})
    incomplete_call = ModelToolCall(tool_call_id="call_2", name="two", arguments={})
    ledger = (
        ModelMessage(
            role="tool", tool_call_id="orphan", content=(TextBlock(text="x"),)
        ),
        ModelMessage(role="assistant", tool_calls=(complete_call,)),
        ModelMessage(
            role="tool", tool_call_id="call_1", content=(TextBlock(text="ok"),)
        ),
        ModelMessage(role="assistant", tool_calls=(incomplete_call,)),
        ModelMessage(role="user", content=(TextBlock(text="continue"),)),
    )
    prepared = await DefaultContextAssembler().prepare_messages(command(), ledger)
    assert [message.role for message in prepared] == ["assistant", "tool", "user"]
    assert prepared[0].tool_calls == (complete_call,)


@pytest.mark.asyncio
async def test_explicit_latest_user_segment_is_injected_even_when_not_volatile():
    assembler = DefaultContextAssembler(
        providers=(
            StaticContextProvider(
                (
                    ContextSegment(
                        segment_id="protected",
                        content="policy-state",
                        stability=ContextStability.STABLE,
                        placement=ContextPlacement.LATEST_USER,
                    ),
                )
            ),
        ),
        runtime_context_in_user=False,
    )
    prepared = await assembler.prepare_messages(
        command(), await assembler.initial_ledger(command())
    )
    assert len(prepared) == 1
    assert "policy-state" in prepared[0].content[0].text


@pytest.mark.asyncio
async def test_run_metadata_context_has_stable_prefix_and_volatile_user_state():
    current = command(
        metadata={
            "response_language": "zh-CN",
            "identity_documents": {"SOUL": "Be careful", "USER": "Likes detail"},
            "system_context": {"session_id": "session_1"},
            "current_time": "2026-08-28T12:00:00+08:00",
            "working_directory": "/workspace/project",
        }
    )
    assembler = DefaultContextAssembler(providers=(RunMetadataContextProvider(),))

    prepared = await assembler.prepare_messages(
        current, await assembler.initial_ledger(current)
    )

    assert len(prepared) == 2
    assert prepared[0].metadata["context_segment_ids"] == (
        "response_language",
        "system_reminder_hint",
        "runtime_context_hint",
        "identity_soul",
        "identity_user",
    )
    assert prepared[0].metadata["cache_segment"] == "stable"
    assert "<soul>\nBe careful\n</soul>" in prepared[0].content[0].text
    assert "<user>\nLikes detail\n</user>" in prepared[0].content[0].text
    latest = prepared[-1].content[0].text
    assert latest.index("<runtime_context>") < latest.index("<user_request>")
    assert "<working_directory>/workspace/project</working_directory>" in latest
    assert "question" in latest


@pytest.mark.asyncio
async def test_historical_user_keeps_its_frozen_time_but_not_old_runtime_state():
    current = command(
        metadata={
            "response_language": "zh-CN",
            "current_time": "Fri, 28 Aug 2026 12:30:00 +0800",
        }
    )
    assembler = DefaultContextAssembler(providers=(RunMetadataContextProvider(),))
    ledger = (
        ModelMessage(
            role="user",
            content=(TextBlock(text="old request"),),
            metadata={
                "frozen_current_time_context": (
                    "<current_time>Thu, 27 Aug 2026 09:00:00 +0800</current_time>"
                )
            },
        ),
        ModelMessage(role="assistant", content=(TextBlock(text="old answer"),)),
        ModelMessage(role="user", content=(TextBlock(text="new request"),)),
    )

    prepared = await assembler.prepare_messages(current, ledger)

    old_user = prepared[-3].content[0].text
    new_user = prepared[-1].content[0].text
    assert "Thu, 27 Aug 2026 09:00:00 +0800" in old_user
    assert "Fri, 28 Aug 2026 12:30:00 +0800" not in old_user
    assert "Fri, 28 Aug 2026 12:30:00 +0800" in new_user


@pytest.mark.asyncio
async def test_budget_reduction_drops_oldest_complete_units_not_half_tool_pairs():
    call = ModelToolCall(tool_call_id="call_1", name="lookup", arguments={})
    ledger = (
        ModelMessage(role="user", content=(TextBlock(text="old question"),)),
        ModelMessage(role="assistant", tool_calls=(call,)),
        ModelMessage(
            role="tool", tool_call_id="call_1", content=(TextBlock(text="old result"),)
        ),
        ModelMessage(role="assistant", content=(TextBlock(text="old answer"),)),
        ModelMessage(role="user", content=(TextBlock(text="latest question"),)),
    )
    assembler = DefaultContextAssembler(
        system_instructions="system",
        budget=ContextBudget(max_input_tokens=10_000, max_messages=4),
    )
    projection = await assembler.prepare_projection(command(), ledger)

    assert projection.strategy == "window"
    assert projection.dropped_message_count == 3
    assert projection.dropped_digest.startswith("sha256:")
    assert [message.role for message in projection.messages] == [
        "system",
        "assistant",
        "user",
    ]
    assert projection.messages[-1].content[0].text == "latest question"


@pytest.mark.asyncio
async def test_budget_never_truncates_protected_latest_user_silently():
    assembler = DefaultContextAssembler(
        system_instructions="system",
        budget=ContextBudget(max_input_tokens=1),
    )
    with pytest.raises(SageV2Error) as caught:
        await assembler.prepare_messages(
            command(),
            (ModelMessage(role="user", content=(TextBlock(text="must survive"),)),),
        )
    assert caught.value.info.code == "context.budget_exhausted"
