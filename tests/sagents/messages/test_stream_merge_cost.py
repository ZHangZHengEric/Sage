"""Streaming merges preserve snapshots without copying history per token."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from sagents.context.messages.message import MessageChunk, MessageType
from sagents.context.messages.message_manager import MessageManager


def chunk(message_id="answer", **fields):
    return MessageChunk(role="assistant", message_id=message_id, **fields)


def tool(index, *, call_id="", name="", arguments=""):
    return {
        "index": index,
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


@pytest.mark.parametrize("batch_size", [1, 2, 8])
def test_batch_boundaries_preserve_reasoning_text_and_parallel_tools(batch_size):
    source = [MessageChunk(role="user", content="question", message_id="user")]
    parts = [
        chunk(reasoning_content="think", type=MessageType.REASONING_CONTENT.value),
        chunk(reasoning_content=" more", type=MessageType.REASONING_CONTENT.value),
        chunk(content="Hello"),
        chunk(content=" world"),
        chunk(tool_calls=[tool(0, call_id="a", name="first", arguments='{"x":')]),
        chunk(tool_calls=[tool(1, call_id="b", name="second", arguments='{"y":')]),
        chunk(tool_calls=[tool(0, arguments="1}")]),
        chunk(tool_calls=[tool(1, arguments="2}")]),
    ]
    before = deepcopy(source + parts)
    manager = MessageManager()
    manager.add_messages(source)
    merged = source
    for index in range(0, len(parts), batch_size):
        batch = parts[index : index + batch_size]
        manager.add_messages(batch)
        merged = MessageManager.merge_new_messages_to_old_messages(batch, merged)
    assert merged == manager.messages
    assert merged[-1].content == "Hello world"
    assert merged[-1].reasoning_content == "think more"
    assert merged[-1].type == MessageType.TOOL_CALL.value
    assert [t["function"]["arguments"] for t in merged[-1].tool_calls] == [
        '{"x":1}',
        '{"y":2}',
    ]
    assert source + parts == before


def test_live_ledger_detaches_inputs_and_preserves_previous_tail_view():
    manager = MessageManager()
    incoming = chunk(content="first", metadata={"nested": ["original"]})
    manager.add_messages(incoming)
    previous = manager.messages
    manager.add_messages(chunk(content=" second"))
    assert previous[-1].content == "first"
    assert manager.messages[-1].content == "first second"
    manager.messages[-1].metadata["nested"].append("changed")
    assert previous[-1].metadata == incoming.metadata == {"nested": ["original"]}


@pytest.mark.parametrize(
    "merge",
    [
        lambda new, old: MessageManager.merge_new_message_old_messages(new, old),
        lambda new, old: MessageManager.merge_new_messages_to_old_messages([new], old),
    ],
)
def test_public_merges_keep_full_snapshot_isolation(merge):
    old = [MessageChunk(role="user", content=[{"type": "text", "text": "old"}])]
    new = chunk(content=[{"type": "text", "text": "new"}], metadata={"nested": [1]})
    result = merge(new, old)
    result[0].content[0]["text"] = "changed"
    result[-1].content[0]["text"] = "changed"
    result[-1].metadata["nested"].append(2)
    assert old[0].content[0]["text"] == "old"
    assert new.content[0]["text"] == "new"
    assert new.metadata == {"nested": [1]}


def test_multimodal_replacement_does_not_alias_delta():
    manager = MessageManager()
    manager.add_messages(chunk(content="before"))
    incoming = chunk(content=[{"type": "text", "text": "image description"}])
    manager.add_messages(incoming)
    incoming.content[0]["text"] = "mutated by caller"
    assert manager.messages[-1].content[0]["text"] == "image description"
    manager.add_messages(chunk(content="replacement"))
    assert manager.messages[-1].content == "replacement"


class CopyCounter:
    copies = 0

    def __deepcopy__(self, memo):
        type(self).copies += 1
        return type(self)()


def test_stream_cost_does_not_scale_as_history_copies_per_chunk():
    history = [
        MessageChunk(role="user", content="question", metadata={"probe": CopyCounter()})
    ]
    parts = [chunk(content="x") for _ in range(1000)]
    CopyCounter.copies = 0
    merged = MessageManager.merge_new_messages_to_old_messages(parts, history)
    assert merged[-1].content == "x" * 1000
    assert CopyCounter.copies == 1
    manager = MessageManager()
    manager.add_messages(history)
    CopyCounter.copies = 0
    for part in parts:
        manager.add_messages(part)
    assert manager.messages[-1].content == "x" * 1000
    assert CopyCounter.copies == 0


def test_plain_deltas_skip_coverage_rebuild_but_new_messages_refresh():
    manager = MessageManager()
    with patch.object(
        manager,
        "_refresh_history_anchor_index",
        wraps=manager._refresh_history_anchor_index,
    ) as refresh:
        manager.add_messages(chunk(reasoning_content="thinking"))
        for _ in range(20):
            manager.add_messages(chunk(content="text"))
        assert refresh.call_count == 1
        manager.add_messages(chunk("next", content="another message"))
        assert refresh.call_count == 2
        assert manager.compact_manifest["total_messages"] == 2


def test_partial_compression_result_refreshes_until_anchor_becomes_valid():
    manager = MessageManager()
    manager.add_messages(MessageChunk(role="user", content="source", message_id="u"))
    manager.add_messages(
        chunk(
            "compress",
            tool_calls=[tool(0, call_id="c", name="compress_conversation_history")],
        )
    )
    metadata = {
        "tool_name": "compress_conversation_history",
        "status": "success",
        "compression_anchor": True,
        "source_message_ids": ["u"],
    }
    manager.add_messages(
        MessageChunk(
            role="tool",
            tool_call_id="c",
            message_id="result",
            content='{"summary":"hel',
            metadata=metadata,
        )
    )
    assert manager.active_start_index is None
    manager.add_messages(
        MessageChunk(
            role="tool",
            tool_call_id="c",
            message_id="result",
            content='lo"}',
            metadata=metadata,
        )
    )
    assert manager.active_start_index == manager.compute_history_anchor_index() == 1
    assert manager.compact_manifest["visible_pair_count"] == 1
    manager.add_messages(chunk("reply", content="answer"))
    manager.add_messages(chunk("reply", reasoning_content="more"))
    assert manager.active_start_index == 1
    assert manager.compact_manifest["total_messages"] == 4


def test_nonconsecutive_ids_remain_separate_messages():
    parts = [
        chunk("a", content="one"),
        chunk("b", content="two"),
        chunk("a", content="three"),
    ]
    result = MessageManager.merge_new_messages_to_old_messages(parts, [])
    assert [m.content for m in result] == ["one", "two", "three"]


def test_ordinary_tool_argument_deltas_do_not_rebuild_compression_graph():
    manager = MessageManager()
    with patch.object(manager, '_refresh_history_anchor_index', wraps=manager._refresh_history_anchor_index) as refresh:
        manager.add_messages(chunk(tool_calls=[tool(0, call_id='call', name='file_write', arguments='{"content":"')]))
        for _ in range(100):
            manager.add_messages(chunk(tool_calls=[tool(0, arguments='x')]))
        manager.add_messages(chunk(tool_calls=[tool(0, arguments='"}')]))
        assert refresh.call_count == 1
        assert manager.messages[-1].tool_calls[0]['function']['arguments'] == '{"content":"' + 'x' * 100 + '"}'
        assert manager.compact_manifest['total_messages'] == 1


def test_late_compression_tool_name_still_refreshes_after_becoming_complete():
    manager = MessageManager()
    with patch.object(manager, '_refresh_history_anchor_index', wraps=manager._refresh_history_anchor_index) as refresh:
        manager.add_messages(chunk(tool_calls=[tool(0, call_id='call', name='')]))
        manager.add_messages(chunk(tool_calls=[tool(0, name='compress_conversation_history')]))
        manager.add_messages(chunk(tool_calls=[tool(0, arguments='{}')]))
        assert refresh.call_count == 3
        assert manager._is_compress_history_tool_call(manager.messages[-1])


def test_tool_delta_preserves_old_snapshot_and_detaches_incoming_arguments():
    manager = MessageManager()
    manager.add_messages(chunk(tool_calls=[tool(0, call_id="a", name="first", arguments="one")]))
    previous = manager.messages
    incoming = chunk(tool_calls=[tool(0, arguments="two")])
    manager.add_messages(incoming)
    assert previous[-1].tool_calls[0]["function"]["arguments"] == "one"
    assert manager.messages[-1].tool_calls[0]["function"]["arguments"] == "onetwo"
    manager.messages[-1].tool_calls[0]["function"]["arguments"] = "changed"
    assert incoming.tool_calls[0]["function"]["arguments"] == "two"
    assert previous[-1].tool_calls[0]["function"]["arguments"] == "one"


def test_tool_copy_preserves_normalization_alias_boundary():
    shared = tool(0, call_id="a", name="first", arguments="one")
    manager = MessageManager()
    manager.add_messages(chunk(tool_calls=[shared], metadata={"original_tool": shared}))
    manager.add_messages(chunk(tool_calls=[tool(0, arguments="two")]))
    # The normalized tool-call dictionary is detached from metadata, as before.
    assert manager.messages[-1].tool_calls[0]["function"]["arguments"] == "onetwo"
    assert manager.messages[-1].metadata["original_tool"]["function"]["arguments"] == "one"
