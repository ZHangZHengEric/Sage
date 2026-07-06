"""SessionContext pending user injection behavior."""

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext


def _make_session(tmp_path):
    return SessionContext(
        session_id="sess_injection",
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
    )


def test_pending_user_injection_preserves_multimodal_content(tmp_path):
    ctx = _make_session(tmp_path)
    content = [
        {"type": "text", "text": "继续解释这张图"},
        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        {
            "type": "input_audio",
            "input_audio": {"data": "base64-audio", "format": "mp3"},
        },
    ]

    guidance_id = ctx.enqueue_user_injection(
        content,
        guidance_id="guidance-1",
        extra_metadata={"ling_source": "text"},
    )

    assert guidance_id == "guidance-1"
    items = ctx.list_user_injections()
    assert items[0]["content"] == content
    assert items[0]["metadata"]["guidance_id"] == "guidance-1"
    assert items[0]["metadata"]["ling_source"] == "text"

    next_content = [{"type": "text", "text": "改成这个引导"}]
    assert ctx.update_user_injection("guidance-1", next_content) is True
    assert ctx.list_user_injections()[0]["content"] == next_content

    drained = ctx.flush_user_injections()
    assert drained[0].content == next_content
    assert drained[0].metadata["guidance_id"] == "guidance-1"  # pyright: ignore[reportOptionalSubscript]
    assert ctx.list_user_injections() == []


def test_pending_user_injection_rejects_empty_content(tmp_path):
    ctx = _make_session(tmp_path)

    try:
        ctx.enqueue_user_injection([{"type": "text", "text": "  "}])
    except ValueError:
        pass
    else:
        raise AssertionError("empty multimodal content should be rejected")


def test_delete_pending_user_injection(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.enqueue_user_injection("稍后继续", guidance_id="guidance-1")

    assert ctx.delete_user_injection("guidance-1") is True
    assert ctx.delete_user_injection("guidance-1") is False
    assert ctx.list_user_injections() == []


def test_enqueue_user_injection_is_idempotent_for_pending_guidance(tmp_path):
    ctx = _make_session(tmp_path)

    ctx.enqueue_user_injection("第一版", guidance_id="guidance-1")
    ctx.enqueue_user_injection(
        "第二版",
        guidance_id="guidance-1",
        extra_metadata={"ling_source": "updated"},
    )

    pending = ctx.list_user_injections()
    assert len(pending) == 1
    assert pending[0]["content"] == "第二版"
    assert pending[0]["metadata"]["ling_source"] == "updated"

    drained = ctx.flush_user_injections()
    assert len(drained) == 1
    assert drained[0].content == "第二版"


def test_enqueue_user_injection_skips_already_flushed_guidance(tmp_path):
    ctx = _make_session(tmp_path)

    ctx.enqueue_user_injection("喝茶喝茶", guidance_id="guidance-1")
    first_drained = ctx.flush_user_injections()
    ctx.enqueue_user_injection("喝茶喝茶", guidance_id="guidance-1")

    assert len(first_drained) == 1
    assert ctx.list_user_injections() == []
    assert [message.content for message in ctx.message_manager.messages] == ["喝茶喝茶"]


def test_hidden_user_injection_is_persisted_for_model_history(tmp_path):
    ctx = _make_session(tmp_path)
    content = [
        {"type": "text", "text": "工具注入的图片上下文"},
        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
    ]

    ctx.enqueue_user_injection(
        content,
        guidance_id="image-context-1",
        extra_metadata={"hidden_from_chat": True, "sse_visible": False},
    )
    drained = ctx.flush_user_injections()

    assert len(drained) == 1
    assert drained[0].content == content
    assert len(ctx.message_manager.messages) == 1
    stored = ctx.message_manager.messages[0]
    assert stored.role == MessageRole.USER.value
    assert stored.content == content
    assert stored.metadata["hidden_from_chat"] is True  # pyright: ignore[reportOptionalSubscript]


def test_transient_user_injection_is_not_persisted(tmp_path):
    ctx = _make_session(tmp_path)

    ctx.enqueue_user_injection(
        "只给下一轮模型看的上下文",
        guidance_id="transient-1",
        extra_metadata={"transient": True, "persist": False, "sse_visible": False},
    )
    drained = ctx.flush_user_injections()

    assert len(drained) == 1
    assert drained[0].content == "只给下一轮模型看的上下文"
    assert ctx.message_manager.messages == []


def test_flush_user_injection_waits_for_open_tool_call_tail(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.add_messages(
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        )
    )
    ctx.enqueue_user_injection("而且我需要60秒左右的视频", guidance_id="guidance-1")

    assert ctx.flush_user_injections() == []
    assert len(ctx.list_user_injections()) == 1

    ctx.add_messages(
        MessageChunk(
            role=MessageRole.TOOL.value,
            content="ok",
            tool_call_id="call_1",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        )
    )
    drained = ctx.flush_user_injections()

    assert len(drained) == 1
    assert drained[0].metadata["guidance_id"] == "guidance-1"  # pyright: ignore[reportOptionalSubscript]
    assert ctx.list_user_injections() == []


def test_flush_user_injection_uses_supplied_closed_ledger(tmp_path):
    ctx = _make_session(tmp_path)
    assistant_tool_call = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "analyze_image", "arguments": "{}"},
            }
        ],
        message_type=MessageType.TOOL_CALL.value,
    )
    tool_result = MessageChunk(
        role=MessageRole.TOOL.value,
        content='{"status":"success"}',
        tool_call_id="call_1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
        message_id="external-tool-result",
    )
    ctx.add_messages(assistant_tool_call)
    ctx.enqueue_user_injection(
        [{"type": "text", "text": "工具注入的图片上下文"}],
        guidance_id="guidance-image",
        extra_metadata={"hidden_from_chat": True, "sse_visible": False},
    )

    assert ctx.flush_user_injections() == []

    drained = ctx.flush_user_injections(
        ledger_messages=[assistant_tool_call, tool_result]
    )

    assert len(drained) == 1
    assert drained[0].metadata["guidance_id"] == "guidance-image"  # pyright: ignore[reportOptionalSubscript]
    assert all(
        message.message_id != "external-tool-result"
        for message in ctx.message_manager.messages
    )
    assert ctx.list_user_injections() == []


def test_user_message_closes_open_tool_call_before_ledger_insert(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.add_messages(
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        )
    )

    ctx.add_messages(MessageChunk(role=MessageRole.USER.value, content="新的引导"))

    messages = ctx.message_manager.messages
    assert [message.role for message in messages] == [
        MessageRole.ASSISTANT.value,
        MessageRole.TOOL.value,
        MessageRole.USER.value,
    ]
    assert messages[1].tool_call_id == "call_1"
    assert messages[1].metadata["synthetic_interrupted_tool_result"] is True


def test_late_tool_result_replaces_synthetic_interrupted_result(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.add_messages(
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "todo_write", "arguments": "{}"},
                }
            ],
            message_type=MessageType.TOOL_CALL.value,
        )
    )
    ctx.add_messages(MessageChunk(role=MessageRole.USER.value, content="新的引导"))

    ctx.add_messages(
        MessageChunk(
            role=MessageRole.TOOL.value,
            content="真实结果",
            tool_call_id="call_1",
            message_type=MessageType.TOOL_CALL_RESULT.value,
        )
    )

    messages = ctx.message_manager.messages
    assert [message.role for message in messages] == [
        MessageRole.ASSISTANT.value,
        MessageRole.TOOL.value,
        MessageRole.USER.value,
    ]
    assert messages[1].content == "真实结果"
    assert "synthetic_interrupted_tool_result" not in messages[1].metadata


def test_user_message_repairs_existing_interleaved_tool_result(tmp_path):
    ctx = _make_session(tmp_path)
    assistant = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "todo_write", "arguments": "{}"},
            }
        ],
        message_type=MessageType.TOOL_CALL.value,
    )
    first_user = MessageChunk(role=MessageRole.USER.value, content="插队的引导")
    tool_result = MessageChunk(
        role=MessageRole.TOOL.value,
        content="真实结果",
        tool_call_id="call_1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )
    ctx.message_manager.messages = [assistant, first_user, tool_result]

    ctx.add_messages(MessageChunk(role=MessageRole.USER.value, content="下一条引导"))

    messages = ctx.message_manager.messages
    assert [message.content for message in messages] == [
        None,
        "真实结果",
        "插队的引导",
        "下一条引导",
    ]
    assert [message.role for message in messages] == [
        MessageRole.ASSISTANT.value,
        MessageRole.TOOL.value,
        MessageRole.USER.value,
        MessageRole.USER.value,
    ]


def test_update_system_context_handles_legacy_context_without_external_paths(
    tmp_path,
):
    ctx = _make_session(tmp_path)
    if hasattr(ctx, "external_paths"):
        delattr(ctx, "external_paths")

    ctx.add_and_update_system_context({"external_paths": [str(tmp_path / "task")]})

    assert ctx.external_paths == [str(tmp_path / "task")]
    assert ctx.system_context["external_paths"] == [str(tmp_path / "task")]
