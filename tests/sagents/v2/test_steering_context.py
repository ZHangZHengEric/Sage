"""Steering guidance is a fresh model projection, never a conversation fact."""
import pytest

from sagents.v2.context import DefaultContextAssembler
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.model import ModelMessage, ModelToolCall
from sagents.v2.prompt_i18n import prompt_text


def command(language):
    return StartRun(
        agent_id="agent", resolved_spec_hash="sha256:spec", idempotency_key="start",
        input=(InputItem(role="user", content=(TextBlock(text="original goal"),)),),
        config=RunConfig(metadata={"response_language": language}),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("provenance", ["steer_run_id", "source_run_id"])
async def test_guidance_is_localized_and_applied_only_to_owning_run(language, provenance):
    assembler = DefaultContextAssembler()
    original = ModelMessage(role="user", content=(TextBlock(text="original goal"),))
    call = ModelMessage(role="assistant", tool_calls=(ModelToolCall(
        tool_call_id="call", name="lookup", arguments={}),))
    result = ModelMessage(role="tool", tool_call_id="call", content=(TextBlock(text="already done"),))
    supplemental = ModelMessage(
        role="user", content=(TextBlock(text="new constraint"),
                              ImageBlock(uri="https://example.test/image.png", mime_type="image/png")),
        metadata={"steer_id": "steer", provenance: "current_run"},
    )
    ledger = (original, call, result, supplemental)
    before = tuple(message.model_dump() for message in ledger)
    first = await assembler.prepare_messages(command(language), ledger, run_id="current_run")
    second = await assembler.prepare_messages(command(language), ledger, run_id="current_run")
    hint = prompt_text("steering", language)
    assert sum(hint in block.text for message in first for block in message.content
               if isinstance(block, TextBlock)) == 1
    assert first == second
    assert first[-1] == supplemental
    assert tuple(message.model_dump() for message in ledger) == before
    assert [message.role for message in first[-3:]] == ["assistant", "tool", "user"]
    historical = await assembler.prepare_messages(command(language), ledger, run_id="next_run")
    assert all(hint not in block.text for message in historical for block in message.content
               if isinstance(block, TextBlock))


@pytest.mark.asyncio
async def test_regular_followup_does_not_inherit_steering_runtime_note():
    assembler = DefaultContextAssembler()
    ledger = (
        ModelMessage(role="user", content=(TextBlock(text="old steer"),),
                     metadata={"steer_id": "steer", "steer_run_id": "current_run"}),
        ModelMessage(role="user", content=(TextBlock(text="a separate request"),)),
    )
    prepared = await assembler.prepare_messages(command("en"), ledger, run_id="current_run")
    assert all(message.role != "system" for message in prepared)
