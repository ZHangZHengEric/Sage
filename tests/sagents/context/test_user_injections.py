"""SessionContext pending user injection behavior."""

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
