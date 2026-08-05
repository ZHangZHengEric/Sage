import json
from types import SimpleNamespace

import pytest

from sagents.agent.simple_agent import SimpleAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.context.messages.token_accounting import (
    PromptBudgetManager,
    PromptTokenEstimator,
)


def _msg(
    role: str,
    content: str,
    message_type: str,
    *,
    message_id: str,
    tool_call_id: str | None = None,
    tool_calls: list[dict] | None = None,
    metadata: dict | None = None,
) -> MessageChunk:
    return MessageChunk(
        role=role,
        content=content,
        type=message_type,
        message_id=message_id,
        tool_call_id=tool_call_id,
        tool_calls=tool_calls,
        metadata=metadata or {},
    )


def _tool_call(message_id: str, call_id: str, name: str = "demo_tool") -> MessageChunk:
    return _msg(
        MessageRole.ASSISTANT.value,
        "",
        MessageType.TOOL_CALL.value,
        message_id=message_id,
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": '{"full": "arguments"}'},
            }
        ],
    )


def _tool_result(message_id: str, call_id: str, content: str) -> MessageChunk:
    return _msg(
        MessageRole.TOOL.value,
        content,
        MessageType.TOOL_CALL_RESULT.value,
        message_id=message_id,
        tool_call_id=call_id,
    )


def _compression_pair(
    *,
    call_message_id: str,
    result_message_id: str,
    call_id: str,
    source_ids: list[str],
    summary: str = "compressed summary",
) -> tuple[MessageChunk, MessageChunk]:
    tool_call = _tool_call(
        call_message_id,
        call_id,
        name="compress_conversation_history",
    )
    tool_call.metadata.update(
        {
            "tool_name": "compress_conversation_history",
            "compression_anchor": True,
            "source_start_message_id": source_ids[0],
            "source_end_message_id": source_ids[-1],
            "source_message_ids": source_ids,
            "source_message_count": len(source_ids),
        }
    )
    payload = {
        "summary": summary,
        "decisions": [],
        "open_tasks": [],
        "files_touched": [],
        "commands_run": [],
        "important_errors": [],
        "user_requirements": [],
        "stats": {"source_message_count": len(source_ids)},
    }
    tool_result = _msg(
        MessageRole.TOOL.value,
        json.dumps(payload),
        MessageType.TOOL_CALL_RESULT.value,
        message_id=result_message_id,
        tool_call_id=call_id,
        metadata={
            "tool_name": "compress_conversation_history",
            "status": "success",
            "compression_anchor": True,
            "source_start_message_id": source_ids[0],
            "source_end_message_id": source_ids[-1],
            "source_message_ids": source_ids,
            "source_message_count": len(source_ids),
        },
    )
    return tool_call, tool_result


def test_main_inference_view_preserves_large_history_without_artifact_offload():
    old_user = _msg(
        MessageRole.USER.value,
        "U" * 30_000,
        MessageType.USER_INPUT.value,
        message_id="u-old",
    )
    old_tool_call = _tool_call("a-call", "call-1")
    old_tool = _tool_result("t-old", "call-1", "T" * 30_000)
    recent_tail = [
        _msg(
            MessageRole.ASSISTANT.value,
            f"recent-{idx}",
            MessageType.ASSISTANT_TEXT.value,
            message_id=f"recent-{idx}",
        )
        for idx in range(20)
    ]
    messages = [old_user, old_tool_call, old_tool, *recent_tail]

    view = MessageManager.build_inference_view(messages)

    assert old_tool.content == "T" * 30_000
    assert view[0].content == "U" * 30_000
    assert view[1].tool_calls[0]["function"]["arguments"] == '{"full": "arguments"}'
    assert view[2].content == "T" * 30_000
    assert not view[2].metadata.get("context_artifact_ref")


def test_main_inference_view_uses_llm_compression_pair_without_rewriting_it():
    raw = _msg(
        MessageRole.ASSISTANT.value,
        "raw",
        MessageType.ASSISTANT_TEXT.value,
        message_id="raw-1",
    )
    tool_call, tool_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["raw-1"],
        summary="S" * 30_000,
    )

    view = MessageManager.build_inference_view([raw, tool_call, tool_result])

    assert [msg.message_id for msg in view] == ["compress-call", "compress-result"]
    assert "[Content moved to context artifact]" not in view[-1].content


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"tool_name": "compress_conversation_history", "status": "success"},
        {
            "tool_name": "compress_conversation_history",
            "status": "error",
            "compression_anchor": True,
            "source_message_ids": ["raw-a"],
        },
        {
            "tool_name": "compress_conversation_history",
            "status": "success",
            "compression_anchor": True,
        },
    ],
)
def test_invalid_compression_pair_metadata_does_not_hide_raw_messages(metadata):
    raw = _msg(
        MessageRole.ASSISTANT.value,
        "raw answer",
        MessageType.ASSISTANT_TEXT.value,
        message_id="raw-a",
    )
    tool_call = _tool_call(
        "compress-call", "compress-1", "compress_conversation_history"
    )
    tool_result = _msg(
        MessageRole.TOOL.value,
        "summary",
        MessageType.TOOL_CALL_RESULT.value,
        message_id="compress-result",
        tool_call_id="compress-1",
        metadata=metadata,
    )

    view = MessageManager.extract_messages_for_inference([raw, tool_call, tool_result])

    assert [msg.message_id for msg in view] == [
        "raw-a",
        "compress-call",
        "compress-result",
    ]


def test_empty_or_partial_compression_summary_never_hides_source_messages():
    raw_a = _msg(
        MessageRole.USER.value,
        "request",
        MessageType.USER_INPUT.value,
        message_id="raw-a",
    )
    raw_b = _msg(
        MessageRole.ASSISTANT.value,
        "answer",
        MessageType.ASSISTANT_TEXT.value,
        message_id="raw-b",
    )
    empty_call, empty_result = _compression_pair(
        call_message_id="empty-call",
        result_message_id="empty-result",
        call_id="empty",
        source_ids=["raw-a", "raw-b"],
        summary="",
    )
    partial_call, partial_result = _compression_pair(
        call_message_id="partial-call",
        result_message_id="partial-result",
        call_id="partial",
        source_ids=["raw-a", "missing-source"],
    )

    empty_view = MessageManager.build_inference_view(
        [raw_a, raw_b, empty_call, empty_result]
    )
    partial_view = MessageManager.build_inference_view(
        [raw_a, raw_b, partial_call, partial_result]
    )

    assert [msg.message_id for msg in empty_view][:2] == ["raw-a", "raw-b"]
    assert [msg.message_id for msg in partial_view][:2] == ["raw-a", "raw-b"]


def test_inference_view_keeps_visible_compression_pair_and_hides_covered_raw_messages():
    raw_a = _msg(
        MessageRole.USER.value,
        "first request",
        MessageType.USER_INPUT.value,
        message_id="raw-a",
    )
    raw_b = _msg(
        MessageRole.ASSISTANT.value,
        "old answer",
        MessageType.ASSISTANT_TEXT.value,
        message_id="raw-b",
    )
    tool_call, tool_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["raw-a", "raw-b"],
    )
    current = _msg(
        MessageRole.USER.value,
        "current request",
        MessageType.USER_INPUT.value,
        message_id="current",
    )

    view = MessageManager.extract_messages_for_inference(
        [raw_a, raw_b, tool_call, tool_result, current]
    )

    assert [msg.message_id for msg in view] == [
        "compress-call",
        "compress-result",
        "current",
    ]


def test_inference_view_excludes_system_message_before_compression_coverage():
    system = _msg(
        MessageRole.SYSTEM.value,
        "system instructions",
        MessageType.SYSTEM.value,
        message_id="sys-1",
    )
    raw_user = _msg(
        MessageRole.USER.value,
        "first request",
        MessageType.USER_INPUT.value,
        message_id="raw-u",
    )
    raw_assistant = _msg(
        MessageRole.ASSISTANT.value,
        "old answer",
        MessageType.ASSISTANT_TEXT.value,
        message_id="raw-a",
    )
    tool_call, tool_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["sys-1", "raw-u", "raw-a"],
    )

    view = MessageManager.extract_messages_for_inference(
        [system, raw_user, raw_assistant, tool_call, tool_result]
    )

    assert [msg.message_id for msg in view] == [
        "compress-call",
        "compress-result",
    ]
    assert all(msg.role != MessageRole.SYSTEM.value for msg in view)


def test_nested_compression_keeps_outer_pair_and_hides_inner_pair():
    raw_a = _msg(
        MessageRole.ASSISTANT.value,
        "old answer",
        MessageType.ASSISTANT_TEXT.value,
        message_id="raw-a",
    )
    inner_call, inner_result = _compression_pair(
        call_message_id="inner-call",
        result_message_id="inner-result",
        call_id="inner",
        source_ids=["raw-a"],
        summary="inner summary",
    )
    outer_call, outer_result = _compression_pair(
        call_message_id="outer-call",
        result_message_id="outer-result",
        call_id="outer",
        source_ids=["inner-call", "inner-result"],
        summary="outer summary",
    )

    view = MessageManager.extract_messages_for_inference(
        [raw_a, inner_call, inner_result, outer_call, outer_result]
    )

    assert [msg.message_id for msg in view] == ["outer-call", "outer-result"]


def test_llm_segment_can_include_visible_compression_pair_as_summary_node():
    raw = _msg(
        MessageRole.ASSISTANT.value,
        "old raw",
        MessageType.ASSISTANT_TEXT.value,
        message_id="raw-a",
    )
    inner_call, inner_result = _compression_pair(
        call_message_id="inner-call",
        result_message_id="inner-result",
        call_id="inner",
        source_ids=["raw-a"],
        summary="inner summary " * 200,
    )
    tail = [
        _msg(
            MessageRole.ASSISTANT.value,
            f"tail-{idx}",
            MessageType.ASSISTANT_TEXT.value,
            message_id=f"tail-{idx}",
        )
        for idx in range(12)
    ]

    segment = MessageManager.select_llm_compression_segment(
        [raw, inner_call, inner_result, *tail],
        active_protection_count=12,
    )

    assert segment is not None
    assert [msg.message_id for msg in segment] == ["inner-call", "inner-result"]


def test_detached_summary_remains_eligible_for_repeated_provider_recovery():
    inner_call, inner_result = _compression_pair(
        call_message_id="inner-call",
        result_message_id="inner-result",
        call_id="inner",
        source_ids=["raw-no-longer-in-view"],
        summary="large prior summary",
    )
    current_user = _msg(
        MessageRole.USER.value,
        "current request",
        MessageType.USER_INPUT.value,
        message_id="u-current",
    )

    view = MessageManager.build_inference_view(
        [inner_call, inner_result, current_user]
    )
    segment = MessageManager.select_llm_compression_segment(
        view,
        active_protection_count=2,
    )

    assert [msg.message_id for msg in view] == [
        "inner-call",
        "inner-result",
        "u-current",
    ]
    assert segment is not None
    assert [msg.message_id for msg in segment] == ["inner-call", "inner-result"]


def test_llm_segment_includes_latest_summary_and_later_completed_turns():
    raw = _msg(
        MessageRole.ASSISTANT.value,
        "old raw",
        MessageType.ASSISTANT_TEXT.value,
        message_id="raw-a",
    )
    inner_call, inner_result = _compression_pair(
        call_message_id="inner-call",
        result_message_id="inner-result",
        call_id="inner",
        source_ids=["raw-a"],
    )
    later_user = _msg(
        MessageRole.USER.value,
        "later request",
        MessageType.USER_INPUT.value,
        message_id="u-later",
    )
    later_assistant = _msg(
        MessageRole.ASSISTANT.value,
        "later answer",
        MessageType.ASSISTANT_TEXT.value,
        message_id="a-later",
    )
    current_user = _msg(
        MessageRole.USER.value,
        "current request",
        MessageType.USER_INPUT.value,
        message_id="u-current",
    )
    tail = [
        _msg(
            MessageRole.ASSISTANT.value,
            f"tail-{idx}",
            MessageType.ASSISTANT_TEXT.value,
            message_id=f"tail-{idx}",
        )
        for idx in range(12)
    ]

    segment = MessageManager.select_llm_compression_segment(
        [
            raw,
            inner_call,
            inner_result,
            later_user,
            later_assistant,
            current_user,
            *tail,
        ],
        active_protection_count=12,
    )

    assert segment is not None
    assert [msg.message_id for msg in segment] == [
        "inner-call",
        "inner-result",
        "u-later",
        "a-later",
    ]


def test_single_turn_segment_uses_only_closed_tool_groups():
    current_user = _msg(
        MessageRole.USER.value,
        "current request",
        MessageType.USER_INPUT.value,
        message_id="u-current",
    )
    first_call = _tool_call("call-message-1", "call-1")
    first_result = _tool_result("result-1", "call-1", "first result")
    second_call = _tool_call("call-message-2", "call-2")
    second_result = _tool_result("result-2", "call-2", "second result")
    recent_tail = [
        _msg(
            MessageRole.ASSISTANT.value,
            f"tail-{idx}",
            MessageType.ASSISTANT_TEXT.value,
            message_id=f"tail-{idx}",
        )
        for idx in range(2)
    ]

    segment = MessageManager.select_llm_compression_segment(
        [
            current_user,
            first_call,
            first_result,
            second_call,
            second_result,
            *recent_tail,
        ],
        active_protection_count=2,
    )

    assert segment is not None
    assert [msg.message_id for msg in segment] == [
        "call-message-1",
        "result-1",
        "call-message-2",
        "result-2",
    ]


def test_recent_protection_expands_to_complete_tool_pair():
    old_user = _msg(
        MessageRole.USER.value,
        "old request",
        MessageType.USER_INPUT.value,
        message_id="u-old",
    )
    old_assistant = _msg(
        MessageRole.ASSISTANT.value,
        "old answer",
        MessageType.ASSISTANT_TEXT.value,
        message_id="a-old",
    )
    current_user = _msg(
        MessageRole.USER.value,
        "current request",
        MessageType.USER_INPUT.value,
        message_id="u-current",
    )
    protected_call = _tool_call("protected-call", "protected-1")
    protected_result = _tool_result(
        "protected-result", "protected-1", "recent result"
    )
    recent_tail = _msg(
        MessageRole.ASSISTANT.value,
        "recent tail",
        MessageType.ASSISTANT_TEXT.value,
        message_id="recent-tail",
    )

    segment = MessageManager.select_llm_compression_segment(
        [
            old_user,
            old_assistant,
            current_user,
            protected_call,
            protected_result,
            recent_tail,
        ],
        active_protection_count=2,
    )

    assert segment is not None
    assert [msg.message_id for msg in segment] == ["u-old", "a-old"]


def test_insert_messages_after_places_compression_pair_at_source_tail():
    manager = MessageManager()
    raw_messages = [
        _msg(
            MessageRole.USER.value,
            "request",
            MessageType.USER_INPUT.value,
            message_id="u1",
        ),
        _msg(
            MessageRole.ASSISTANT.value,
            "answer",
            MessageType.ASSISTANT_TEXT.value,
            message_id="a1",
        ),
        _msg(
            MessageRole.USER.value,
            "next",
            MessageType.USER_INPUT.value,
            message_id="u2",
        ),
    ]
    manager.add_messages(raw_messages)
    tool_call, tool_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["u1", "a1"],
    )

    assert manager.insert_messages_after("a1", [tool_call, tool_result]) is True

    assert [msg.message_id for msg in manager.messages] == [
        "u1",
        "a1",
        "compress-call",
        "compress-result",
        "u2",
    ]


def test_insert_messages_after_moves_already_appended_compression_pair():
    manager = MessageManager()
    raw_messages = [
        _msg(
            MessageRole.USER.value,
            "request",
            MessageType.USER_INPUT.value,
            message_id="u1",
        ),
        _msg(
            MessageRole.ASSISTANT.value,
            "answer",
            MessageType.ASSISTANT_TEXT.value,
            message_id="a1",
        ),
        _msg(
            MessageRole.USER.value,
            "next",
            MessageType.USER_INPUT.value,
            message_id="u2",
        ),
    ]
    tool_call, tool_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["u1", "a1"],
    )
    manager.add_messages([*raw_messages, tool_call, tool_result])

    assert manager.insert_messages_after("a1", [tool_call, tool_result]) is True

    assert [msg.message_id for msg in manager.messages] == [
        "u1",
        "a1",
        "compress-call",
        "compress-result",
        "u2",
    ]


def test_stream_merge_relocates_compression_pair_before_current_turn():
    old_messages = [
        _msg(
            MessageRole.USER.value,
            "request",
            MessageType.USER_INPUT.value,
            message_id="u1",
        ),
        _msg(
            MessageRole.ASSISTANT.value,
            "answer",
            MessageType.ASSISTANT_TEXT.value,
            message_id="a1",
        ),
        _msg(
            MessageRole.USER.value,
            "current",
            MessageType.USER_INPUT.value,
            message_id="u2",
        ),
    ]
    tool_call, tool_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["u1", "a1"],
    )

    merged = MessageManager.merge_new_messages_to_old_messages(
        [tool_call, tool_result], old_messages
    )

    assert [msg.message_id for msg in merged] == [
        "u1",
        "a1",
        "compress-call",
        "compress-result",
        "u2",
    ]


def test_insert_messages_after_missing_anchor_does_not_append():
    manager = MessageManager()
    original = _msg(
        MessageRole.USER.value,
        "request",
        MessageType.USER_INPUT.value,
        message_id="u1",
    )
    manager.add_messages([original])
    tool_call, tool_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["missing"],
    )

    assert manager.insert_messages_after("missing", [tool_call, tool_result]) is False
    assert manager.messages == [original]


def test_compact_manifest_indexes_visible_and_covered_compression_pairs():
    raw = _msg(
        MessageRole.ASSISTANT.value,
        "raw",
        MessageType.ASSISTANT_TEXT.value,
        message_id="raw-a",
    )
    inner_call, inner_result = _compression_pair(
        call_message_id="inner-call",
        result_message_id="inner-result",
        call_id="inner-1",
        source_ids=["raw-a"],
        summary="inner summary",
    )
    outer_call, outer_result = _compression_pair(
        call_message_id="outer-call",
        result_message_id="outer-result",
        call_id="outer-1",
        source_ids=["inner-call", "inner-result"],
        summary="outer summary",
    )
    messages = [raw, inner_call, inner_result, outer_call, outer_result]

    manifest = MessageManager.build_compact_manifest(messages)

    assert manifest["compression_pair_count"] == 2
    assert manifest["visible_pair_count"] == 1
    assert manifest["visible_compression_result_message_ids"] == ["outer-result"]
    pairs_by_call = {pair["assistant_message_id"]: pair for pair in manifest["pairs"]}
    assert pairs_by_call["inner-call"]["covered_by_later"] is True
    assert pairs_by_call["inner-call"]["visible"] is False
    assert pairs_by_call["outer-call"]["covered_by_later"] is False
    assert pairs_by_call["outer-call"]["visible"] is True
    assert pairs_by_call["outer-call"]["covered_message_ids"] == [
        "raw-a",
        "inner-call",
        "inner-result",
    ]
    assert pairs_by_call["outer-call"]["summary_preview"] == "outer summary"


def test_message_manager_refreshes_compact_manifest_after_insert():
    manager = MessageManager()
    raw = _msg(
        MessageRole.ASSISTANT.value,
        "raw",
        MessageType.ASSISTANT_TEXT.value,
        message_id="raw-a",
    )
    manager.add_messages([raw])
    tool_call, tool_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["raw-a"],
        summary="summary",
    )

    assert manager.insert_messages_after("raw-a", [tool_call, tool_result]) is True

    assert manager.compact_manifest["compression_pair_count"] == 1
    assert manager.compact_manifest["visible_compression_result_message_ids"] == [
        "compress-result"
    ]


def test_select_llm_compression_segment_preserves_tool_pair_and_current_user():
    old_user = _msg(
        MessageRole.USER.value,
        "old request",
        MessageType.USER_INPUT.value,
        message_id="u-old",
    )
    old_call = _tool_call("a-call", "call-1")
    old_tool = _tool_result("t-old", "call-1", "T" * 1000)
    current_user = _msg(
        MessageRole.USER.value,
        "current request",
        MessageType.USER_INPUT.value,
        message_id="u-current",
    )
    tail = [
        _msg(
            MessageRole.ASSISTANT.value,
            f"tail-{idx}",
            MessageType.ASSISTANT_TEXT.value,
            message_id=f"tail-{idx}",
        )
        for idx in range(12)
    ]

    segment = MessageManager.select_llm_compression_segment(
        [old_user, old_call, old_tool, current_user, *tail],
        active_protection_count=12,
    )

    assert segment is not None
    ids = [msg.message_id for msg in segment]
    assert "u-current" not in ids
    assert "a-call" in ids
    assert "t-old" in ids


def test_select_llm_compression_segment_never_includes_system_message():
    system = _msg(
        MessageRole.SYSTEM.value,
        "S" * 4000,
        MessageType.SYSTEM.value,
        message_id="sys-old",
    )
    old_user = _msg(
        MessageRole.USER.value,
        "old request",
        MessageType.USER_INPUT.value,
        message_id="u-old",
    )
    old_assistant = _msg(
        MessageRole.ASSISTANT.value,
        "A" * 4000,
        MessageType.ASSISTANT_TEXT.value,
        message_id="a-old",
    )
    current_user = _msg(
        MessageRole.USER.value,
        "current request",
        MessageType.USER_INPUT.value,
        message_id="u-current",
    )
    tail = [
        _msg(
            MessageRole.ASSISTANT.value,
            f"tail-{idx}",
            MessageType.ASSISTANT_TEXT.value,
            message_id=f"tail-{idx}",
        )
        for idx in range(12)
    ]

    segment = MessageManager.select_llm_compression_segment(
        [system, old_user, old_assistant, current_user, *tail],
        active_protection_count=12,
    )

    assert segment is not None
    assert all(msg.role != MessageRole.SYSTEM.value for msg in segment)
    assert "sys-old" not in [msg.message_id for msg in segment]


@pytest.mark.asyncio
async def test_prepare_messages_for_llm_inserts_successful_pair_after_source_tail(
    monkeypatch,
):
    agent = SimpleAgent(model=None, model_config={"max_model_len": 1000})
    manager = MessageManager(session_id="sess-prepare")
    raw_messages = [
        _msg(
            MessageRole.USER.value,
            "old request",
            MessageType.USER_INPUT.value,
            message_id="u-old",
        ),
        _msg(
            MessageRole.ASSISTANT.value,
            "A" * 4000,
            MessageType.ASSISTANT_TEXT.value,
            message_id="a-old",
        ),
        _msg(
            MessageRole.USER.value,
            "current request",
            MessageType.USER_INPUT.value,
            message_id="u-current",
        ),
        *[
            _msg(
                MessageRole.ASSISTANT.value,
                f"tail-{idx}",
                MessageType.ASSISTANT_TEXT.value,
                message_id=f"tail-{idx}",
            )
            for idx in range(12)
        ],
    ]
    manager.add_messages(raw_messages)
    session_context = SimpleNamespace(
        message_manager=manager,
        sandbox_agent_workspace=None,
        system_context={},
    )
    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )
    monkeypatch.setattr(
        "sagents.agent.agent_base.MessageManager.calculate_messages_token_length",
        lambda messages: (
            2000
            if not any(msg.message_id == "compress-result" for msg in messages)
            else 100
        ),
    )

    tool_call, tool_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["u-old", "a-old"],
    )

    async def fake_compress(messages, session_id, **kwargs):
        assert [msg.message_id for msg in messages] == ["u-old", "a-old"]
        assert kwargs["source_start_message_id"] == "u-old"
        assert kwargs["source_end_message_id"] == "a-old"
        yield [tool_call]
        yield [tool_result]

    monkeypatch.setattr(agent, "_compress_messages_with_tool", fake_compress)

    chunks = [
        item
        async for item in agent._prepare_messages_for_llm(raw_messages, "sess-prepare")
    ]

    assert chunks[0] == ([tool_call], False)
    assert chunks[1] == ([tool_result], False)
    assert chunks[-1][1] is True
    assert [msg.message_id for msg in manager.messages] == [
        "u-old",
        "a-old",
        "compress-call",
        "compress-result",
        "u-current",
        *[f"tail-{idx}" for idx in range(12)],
    ]
    assert [msg.message_id for msg in chunks[-1][0]][:3] == [
        "compress-call",
        "compress-result",
        "u-current",
    ]
    assert manager.messages[1].content == "A" * 4000
    assert [msg.message_id for msg in manager.inference_messages][:3] == [
        "compress-call",
        "compress-result",
        "u-current",
    ]


@pytest.mark.asyncio
async def test_prepare_messages_for_llm_failed_compression_does_not_modify_manager(
    monkeypatch,
):
    agent = SimpleAgent(model=None, model_config={"max_model_len": 1000})
    manager = MessageManager(session_id="sess-fail")
    raw_messages = [
        _msg(
            MessageRole.USER.value,
            "old request",
            MessageType.USER_INPUT.value,
            message_id="u-old",
        ),
        _msg(
            MessageRole.ASSISTANT.value,
            "A" * 4000,
            MessageType.ASSISTANT_TEXT.value,
            message_id="a-old",
        ),
        _msg(
            MessageRole.USER.value,
            "current request",
            MessageType.USER_INPUT.value,
            message_id="u-current",
        ),
        *[
            _msg(
                MessageRole.ASSISTANT.value,
                f"tail-{idx}",
                MessageType.ASSISTANT_TEXT.value,
                message_id=f"tail-{idx}",
            )
            for idx in range(12)
        ],
    ]
    manager.add_messages(raw_messages)
    session_context = SimpleNamespace(
        message_manager=manager,
        sandbox_agent_workspace=None,
        system_context={},
    )
    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )
    monkeypatch.setattr(
        "sagents.agent.agent_base.MessageManager.calculate_messages_token_length",
        lambda messages: 2000,
    )
    failed_result = _msg(
        MessageRole.TOOL.value,
        "compression failed",
        MessageType.TOOL_CALL_RESULT.value,
        message_id="compress-result",
        tool_call_id="compress-1",
        metadata={
            "tool_name": "compress_conversation_history",
            "status": "error",
            "compression_anchor": False,
        },
    )

    async def fake_compress(messages, session_id, **kwargs):
        yield [failed_result]

    monkeypatch.setattr(agent, "_compress_messages_with_tool", fake_compress)

    chunks = [
        item
        async for item in agent._prepare_messages_for_llm(raw_messages, "sess-fail")
    ]

    assert chunks[0] == ([failed_result], False)
    assert chunks[-1][1] is True
    assert manager.messages == raw_messages
    assert manager.inference_messages == chunks[-1][0]


@pytest.mark.asyncio
async def test_provider_overflow_recovery_does_not_treat_view_filtering_as_compression(
    monkeypatch,
):
    agent = SimpleAgent(model=None, model_config={"max_model_len": 1000})
    manager = MessageManager(session_id="sess-provider-rule")
    old = _msg(
        MessageRole.ASSISTANT.value,
        "old history" * 100,
        MessageType.ASSISTANT_TEXT.value,
        message_id="a-old",
    )
    current = _msg(
        MessageRole.USER.value,
        "current request",
        MessageType.USER_INPUT.value,
        message_id="u-current",
    )
    session_context = SimpleNamespace(
        message_manager=manager,
        sandbox_agent_workspace=None,
        system_context={},
    )
    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )
    monkeypatch.setattr(
        "sagents.agent.agent_base.MessageManager.build_inference_view",
        lambda messages, **kwargs: [current],
    )

    async def must_not_call_llm_compression(*args, **kwargs):
        raise AssertionError("there is no safe LLM compression segment")
        yield []

    monkeypatch.setattr(
        agent, "_compress_messages_with_tool", must_not_call_llm_compression
    )

    chunks = [
        item
        async for item in agent._prepare_messages_for_llm(
            [old, current],
            "sess-provider-rule",
            provider_overflow_recovery=True,
        )
    ]

    assert chunks == []


@pytest.mark.asyncio
async def test_provider_overflow_recovery_uses_llm_compression_directly(
    monkeypatch,
):
    agent = SimpleAgent(model=None, model_config={"max_model_len": 1000})
    manager = MessageManager(session_id="sess-provider-llm")
    old = _msg(
        MessageRole.ASSISTANT.value,
        "old history" * 500,
        MessageType.ASSISTANT_TEXT.value,
        message_id="a-old",
    )
    current = _msg(
        MessageRole.USER.value,
        "current request",
        MessageType.USER_INPUT.value,
        message_id="u-current",
    )
    manager.add_messages([old, current])
    session_context = SimpleNamespace(
        message_manager=manager,
        sandbox_agent_workspace=None,
        system_context={},
    )
    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )

    tool_call, tool_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["a-old"],
    )

    def fake_build_view(messages, **kwargs):
        if any(message.message_id == "compress-result" for message in messages):
            return [tool_call, tool_result, current]
        return list(messages)

    monkeypatch.setattr(
        "sagents.agent.agent_base.MessageManager.build_inference_view",
        fake_build_view,
    )
    monkeypatch.setattr(
        "sagents.agent.agent_base.MessageManager.select_llm_compression_segment",
        lambda messages, **kwargs: [old],
    )

    async def fake_compress(messages, session_id, **kwargs):
        yield [tool_call]
        yield [tool_result]

    monkeypatch.setattr(agent, "_compress_messages_with_tool", fake_compress)

    chunks = [
        item
        async for item in agent._prepare_messages_for_llm(
            [old, current],
            "sess-provider-llm",
            provider_overflow_recovery=True,
        )
    ]

    assert chunks[0] == ([tool_call], False)
    assert chunks[1] == ([tool_result], False)
    assert chunks[-1] == ([tool_call, tool_result, current], True)


@pytest.mark.asyncio
async def test_ineffective_summary_is_audited_but_never_becomes_anchor(monkeypatch):
    agent = SimpleAgent(model=None, model_config={"max_model_len": 100})
    manager = MessageManager(session_id="sess-ineffective")
    old_user = _msg(
        MessageRole.USER.value,
        "old request",
        MessageType.USER_INPUT.value,
        message_id="u-old",
    )
    old_assistant = _msg(
        MessageRole.ASSISTANT.value,
        "old answer",
        MessageType.ASSISTANT_TEXT.value,
        message_id="a-old",
    )
    current_user = _msg(
        MessageRole.USER.value,
        "current request",
        MessageType.USER_INPUT.value,
        message_id="u-current",
    )
    tail = [
        _msg(
            MessageRole.ASSISTANT.value,
            f"tail-{idx}",
            MessageType.ASSISTANT_TEXT.value,
            message_id=f"tail-{idx}",
        )
        for idx in range(12)
    ]
    raw_messages = [old_user, old_assistant, current_user, *tail]
    manager.add_messages(raw_messages)
    session_context = SimpleNamespace(
        message_manager=manager,
        sandbox_agent_workspace=None,
        system_context={},
    )
    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )
    monkeypatch.setattr(
        "sagents.agent.agent_base.MessageManager.calculate_messages_token_length",
        lambda messages: 1000,
    )
    tool_call, tool_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["u-old", "a-old"],
        summary="S" * 20_000,
    )

    async def fake_compress(messages, session_id, **kwargs):
        yield [tool_call]
        yield [tool_result]

    monkeypatch.setattr(agent, "_compress_messages_with_tool", fake_compress)

    chunks = [
        item
        async for item in agent._prepare_messages_for_llm(
            raw_messages, "sess-ineffective"
        )
    ]

    assert chunks[0] == ([tool_call], False)
    assert chunks[1] == ([tool_result], False)
    assert chunks[-1] == (raw_messages, True)
    assert tool_call.metadata["compression_anchor"] is False
    assert tool_result.metadata["compression_anchor"] is False
    assert tool_result.metadata["status"] == "ineffective"
    assert tool_result.metadata["llm_scope"] == "never"
    assert manager.messages == raw_messages
    assert [msg.message_id for msg in MessageManager.build_inference_view(raw_messages)] == [
        msg.message_id for msg in raw_messages
    ]


@pytest.mark.asyncio
async def test_soft_estimate_does_not_block_when_no_compressible_segment(
    monkeypatch,
):
    agent = SimpleAgent(model=None, model_config={"max_model_len": 1000})
    manager = MessageManager(session_id="sess-over-limit")
    raw_messages = [
        _msg(
            MessageRole.USER.value,
            "current request" * 1000,
            MessageType.USER_INPUT.value,
            message_id="u-current",
        )
    ]
    manager.add_messages(raw_messages)
    session_context = SimpleNamespace(
        message_manager=manager,
        sandbox_agent_workspace=None,
        system_context={},
    )
    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )
    monkeypatch.setattr(
        "sagents.agent.agent_base.MessageManager.calculate_messages_token_length",
        lambda messages: 2000,
    )

    chunks = [
        item
        async for item in agent._prepare_messages_for_llm(
            raw_messages, "sess-over-limit"
        )
    ]

    assert len(chunks) == 1
    request_view, is_final = chunks[0]
    assert is_final is True
    assert request_view == raw_messages
    assert manager.messages == raw_messages


@pytest.mark.asyncio
async def test_provider_usage_checkpoint_can_trigger_soft_compression(monkeypatch):
    agent = SimpleAgent(
        model=None,
        model_config={"model": "gpt-test", "max_model_len": 1000},
    )
    manager = MessageManager(session_id="sess-checkpoint-trigger")
    raw_messages = [
        _msg(
            MessageRole.USER.value,
            "old request",
            MessageType.USER_INPUT.value,
            message_id="u-old",
        ),
        _msg(
            MessageRole.ASSISTANT.value,
            "old answer",
            MessageType.ASSISTANT_TEXT.value,
            message_id="a-old",
        ),
        _msg(
            MessageRole.USER.value,
            "current request",
            MessageType.USER_INPUT.value,
            message_id="u-current",
        ),
        *[
            _msg(
                MessageRole.ASSISTANT.value,
                f"tail-{idx}",
                MessageType.ASSISTANT_TEXT.value,
                message_id=f"tail-{idx}",
            )
            for idx in range(12)
        ],
    ]
    manager.add_messages(raw_messages)
    budget_manager = PromptBudgetManager()
    session_context = SimpleNamespace(
        message_manager=manager,
        prompt_budget_manager=budget_manager,
        sandbox_agent_workspace=None,
        system_context={},
    )
    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: session_context
    )

    async def build_request(history_messages):
        return list(history_messages)

    provider_messages = [
        MessageManager.convert_message_to_dict_for_request(message)
        for message in raw_messages
    ]
    manifest = PromptTokenEstimator.manifest(provider_messages)
    model_name, provider_identity = agent._resolve_prompt_accounting_identity()
    profile_id = PromptBudgetManager.build_profile_id(
        model=model_name,
        provider_identity=provider_identity,
        agent_class=agent.__class__.__name__,
        step_name="direct_execution",
        view_policy_id=agent._resolved_context_view_spec_hash(),
    )
    assert manifest.estimated_tokens < 850
    budget_manager.update_checkpoint(profile_id, 900, manifest)

    compression_called = False
    failed_result = _msg(
        MessageRole.TOOL.value,
        "compression failed",
        MessageType.TOOL_CALL_RESULT.value,
        message_id="compress-result",
        tool_call_id="compress-1",
        metadata={
            "tool_name": "compress_conversation_history",
            "status": "error",
            "compression_anchor": False,
        },
    )

    async def fake_compress(messages, session_id, **kwargs):
        nonlocal compression_called
        compression_called = True
        yield [failed_result]

    monkeypatch.setattr(agent, "_compress_messages_with_tool", fake_compress)

    chunks = [
        item
        async for item in agent._prepare_context_messages_for_llm(
            raw_messages,
            "sess-checkpoint-trigger",
            request_builder=build_request,
            request_tools=[],
            step_name="direct_execution",
        )
    ]

    assert compression_called is True
    assert chunks[0] == ([failed_result], False)
    assert chunks[-1][1] is True


@pytest.mark.asyncio
async def test_simple_agent_prepares_fresh_system_after_compressed_history_view(
    monkeypatch,
):
    agent = SimpleAgent(model=None, model_config={"max_model_len": 1000})
    captured: dict[str, list] = {}

    system_chunk = _msg(
        MessageRole.SYSTEM.value,
        "fresh system",
        MessageType.SYSTEM.value,
        message_id="sys-fresh",
    )
    compressed_call, compressed_result = _compression_pair(
        call_message_id="compress-call",
        result_message_id="compress-result",
        call_id="compress-1",
        source_ids=["old-u", "old-a"],
    )

    async def fake_prepare_system_messages(*args, **kwargs):
        return [system_chunk]

    async def fake_prepare_messages_for_llm(messages_input, session_id):
        assert all(msg.role != MessageRole.SYSTEM.value for msg in messages_input)
        yield ([compressed_call, compressed_result], True)

    async def fake_llm_streaming(**kwargs):
        captured["messages"] = kwargs["messages"]
        if False:
            yield None

    monkeypatch.setattr(
        "sagents.agent.simple_agent._get_system_prefix", lambda *args, **kwargs: ""
    )
    monkeypatch.setattr(
        agent, "prepare_unified_system_messages", fake_prepare_system_messages
    )
    monkeypatch.setattr(
        agent, "_prepare_messages_for_llm", fake_prepare_messages_for_llm
    )
    monkeypatch.setattr(agent, "_call_llm_streaming", fake_llm_streaming)
    monkeypatch.setattr(
        agent,
        "_get_live_session_context",
        lambda session_id: SimpleNamespace(get_language=lambda: "zh"),
    )

    [
        chunk
        async for chunk, _ in agent._call_llm_and_process_response(
            messages_input=[compressed_call, compressed_result],
            tools_json=[],
            tool_manager=None,
            session_id="sess-loop-system",
        )
    ]

    assert [msg.role for msg in captured["messages"][:3]] == [
        MessageRole.SYSTEM.value,
        MessageRole.ASSISTANT.value,
        MessageRole.TOOL.value,
    ]
    assert captured["messages"][0].content == "fresh system"
