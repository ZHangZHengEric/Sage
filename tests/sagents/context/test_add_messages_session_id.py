import os

from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.context.session_context import SessionContext


def _make_session(tmp_path, session_id="parent-sess"):
    ctx = SessionContext(
        session_id=session_id,
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
    )
    ctx.session_workspace = os.path.join(str(tmp_path), session_id)
    os.makedirs(ctx.session_workspace, exist_ok=True)
    return ctx


def _chunk(session_id, content="hello", message_id=None):
    return MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=content,
        session_id=session_id,
        message_id=message_id or f"msg-{session_id}-{content}",
    )


def test_add_messages_accepts_own_and_untagged(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.add_messages(
        [
            _chunk(None, "untagged"),
            _chunk(ctx.session_id, "own"),
        ]
    )
    contents = [m.content for m in ctx.message_manager.messages]
    assert "untagged" in contents
    assert "own" in contents


def test_add_messages_rejects_direct_and_nested_sub_sessions(tmp_path):
    ctx = _make_session(tmp_path)
    child = f"{ctx.session_id}_sub_0"
    nested = f"{ctx.session_id}_sub_0_sub_1"

    assert not ctx._is_acceptable_message_session_id(child)
    assert not ctx._is_acceptable_message_session_id(nested)

    ctx.add_messages(
        [
            _chunk(child, "child-progress"),
            _chunk(nested, "nested-progress"),
        ]
    )

    contents = [m.content for m in ctx.message_manager.messages]
    assert contents == []


def test_add_messages_rejects_unrelated_session_ids(tmp_path):
    ctx = _make_session(tmp_path)

    assert not ctx._is_acceptable_message_session_id("other-session")
    assert not ctx._is_acceptable_message_session_id(f"{ctx.session_id}_other")
    assert not ctx._is_acceptable_message_session_id(f"{ctx.session_id}_sub")

    ctx.add_messages(
        [
            _chunk("other-session", "stranger"),
            _chunk(f"{ctx.session_id}_other", "lookalike"),
            _chunk(f"{ctx.session_id}_sub", "missing-index"),
        ]
    )

    contents = [m.content for m in ctx.message_manager.messages]
    assert contents == []
