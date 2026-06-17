import json
from types import SimpleNamespace

import pytest

from sagents.agent.simple_agent import SimpleAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager


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
        "source_range": {
            "start_message_id": source_ids[0],
            "end_message_id": source_ids[-1],
        },
        "source_message_ids": source_ids,
        "original_content_paths": [],
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


def test_rule_artifact_offload_keeps_main_ledger_and_protects_user_and_tool_args(tmp_path):
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

    view = MessageManager.build_inference_view(
        messages,
        session_id="sess-artifact",
        max_model_len=20_000,
        artifact_root=str(tmp_path),
        apply_rule_compression=True,
    )

    assert old_tool.content == "T" * 30_000
    assert view[0].content == "U" * 30_000
    assert view[1].tool_calls[0]["function"]["arguments"] == '{"full": "arguments"}'
    assert "[Content moved to context artifact]" in view[2].content
    assert (
        "original_content_path: .sage/context/artifacts/sess-artifact/t-old.txt"
        in view[2].content
    )
    assert "original_content_abs_path:" in view[2].content
    original_content_path = view[2].metadata["original_content_path"]
    assert original_content_path == ".sage/context/artifacts/sess-artifact/t-old.txt"
    assert view[2].metadata["original_content_abs_path"].endswith(
        "/sess-artifact/t-old.txt"
    )
    assert (tmp_path / "sess-artifact" / "t-old.txt").read_text() == "T" * 30_000


def test_rule_artifact_offload_does_not_compress_compression_pair(tmp_path):
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

    view = MessageManager.build_inference_view(
        [raw, tool_call, tool_result],
        session_id="sess-compress",
        max_model_len=20_000,
        artifact_root=str(tmp_path),
        apply_rule_compression=True,
    )

    assert [msg.message_id for msg in view] == ["compress-call", "compress-result"]
    assert "[Content moved to context artifact]" not in view[-1].content


@pytest.mark.parametrize(
    ("role", "message_type", "should_offload"),
    [
        (MessageRole.USER.value, MessageType.USER_INPUT.value, False),
        (MessageRole.SYSTEM.value, MessageType.SYSTEM.value, False),
        (MessageRole.ASSISTANT.value, MessageType.ASSISTANT_TEXT.value, True),
        (MessageRole.TOOL.value, MessageType.TOOL_CALL_RESULT.value, True),
        (MessageRole.ASSISTANT.value, MessageType.SKILL_OBSERVATION.value, True),
    ],
)
def test_rule_artifact_offload_role_matrix(
    tmp_path, role, message_type, should_offload
):
    long_msg = _msg(
        role,
        "X" * 30_000,
        message_type,
        message_id="candidate",
        tool_call_id="call-1" if role == MessageRole.TOOL.value else None,
    )
    messages = [
        long_msg,
        *[
            _msg(
                MessageRole.ASSISTANT.value,
                f"tail-{idx}",
                MessageType.ASSISTANT_TEXT.value,
                message_id=f"tail-{idx}",
            )
            for idx in range(20)
        ],
    ]

    view = MessageManager.build_inference_view(
        messages,
        session_id="sess-matrix",
        max_model_len=20_000,
        artifact_root=str(tmp_path),
        apply_rule_compression=True,
    )

    if should_offload:
        assert "[Content moved to context artifact]" in view[0].content
        assert view[0].metadata["original_content_path"].startswith(
            ".sage/context/artifacts/sess-matrix/"
        )
    else:
        assert view[0].content == "X" * 30_000


def test_rule_artifact_offload_requires_artifact_root():
    long_tool = _tool_result("tool-old", "call-1", "T" * 30_000)
    view = MessageManager.build_inference_view(
        [
            long_tool,
            *[
                _msg(
                    MessageRole.ASSISTANT.value,
                    f"tail-{idx}",
                    MessageType.ASSISTANT_TEXT.value,
                    message_id=f"tail-{idx}",
                )
                for idx in range(20)
            ],
        ],
        session_id="sess-no-root",
        max_model_len=20_000,
        artifact_root=None,
        apply_rule_compression=True,
    )

    assert view[0].content == "T" * 30_000
    assert not view[0].metadata.get("context_artifact_ref")


def test_rule_pair_safe_protection_expands_multi_tool_call_group(tmp_path):
    assistant = _msg(
        MessageRole.ASSISTANT.value,
        "",
        MessageType.TOOL_CALL.value,
        message_id="tool-call-group",
        tool_calls=[
            {
                "id": "call-a",
                "type": "function",
                "function": {"name": "a", "arguments": '{"a": "full"}'},
            },
            {
                "id": "call-b",
                "type": "function",
                "function": {"name": "b", "arguments": '{"b": "full"}'},
            },
        ],
    )
    result_a = _tool_result("result-a", "call-a", "A" * 30_000)
    result_b = _tool_result("result-b", "call-b", "B" * 30_000)
    messages = [
        _msg(
            MessageRole.ASSISTANT.value,
            "old",
            MessageType.ASSISTANT_TEXT.value,
            message_id="old",
        ),
        assistant,
        result_a,
        result_b,
    ]

    view = MessageManager.build_inference_view(
        messages,
        session_id="sess-pairsafe",
        max_model_len=20_000,
        artifact_root=str(tmp_path),
        rule_protection_count=1,
        apply_rule_compression=True,
    )

    assert view[1].tool_calls[0]["function"]["arguments"] == '{"a": "full"}'
    assert view[2].content == "A" * 30_000
    assert view[3].content == "B" * 30_000


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
    tool_call = _tool_call("compress-call", "compress-1", "compress_conversation_history")
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
        max_model_len=2000,
        active_protection_count=12,
    )

    assert segment is not None
    assert [msg.message_id for msg in segment] == ["inner-call", "inner-result"]


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
    pairs_by_call = {
        pair["assistant_message_id"]: pair for pair in manifest["pairs"]
    }
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
        max_model_len=2000,
        active_protection_count=12,
    )

    assert segment is not None
    ids = [msg.message_id for msg in segment]
    assert "u-current" not in ids
    assert "a-call" in ids
    assert "t-old" in ids


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
    monkeypatch.setattr(agent, "_get_live_session_context", lambda session_id: session_context)
    monkeypatch.setattr(
        "sagents.agent.agent_base.MessageManager.calculate_messages_token_length",
        lambda messages: 2000
        if not any(msg.message_id == "compress-result" for msg in messages)
        else 100,
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
    monkeypatch.setattr(agent, "_get_live_session_context", lambda session_id: session_context)
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
async def test_prepare_messages_for_llm_returns_error_when_no_compressible_segment(
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
    monkeypatch.setattr(agent, "_get_live_session_context", lambda session_id: session_context)
    monkeypatch.setattr(
        "sagents.agent.agent_base.MessageManager.calculate_messages_token_length",
        lambda messages: 2000,
    )

    chunks = [
        item
        async for item in agent._prepare_messages_for_llm(raw_messages, "sess-over-limit")
    ]

    assert len(chunks) == 1
    error_chunks, is_final = chunks[0]
    assert is_final is False
    assert error_chunks[0].message_type == MessageType.AGENT_EXECUTION_ERROR.value
    assert "压缩后仍超过模型输入限制" in error_chunks[0].content
    assert manager.messages == raw_messages
