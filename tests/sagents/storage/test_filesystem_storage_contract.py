"""Characterization tests for the legacy session-root filesystem contract.

These tests intentionally exercise the pre-abstraction public behaviour.  A
storage implementation may change internally, but the filesystem backend must
continue to produce and consume this layout and payload shape.
"""

import json
import os
import sqlite3
import time
from typing import Any, cast

from openai.types.chat import chat_completion_chunk

from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.context.session_context import MESSAGE_JOURNAL_FILE, SessionContext
from sagents.session_registry import SessionRegistry


def _context(root, session_id="session-a"):
    context = SessionContext(
        session_id=session_id,
        user_id="user-a",
        agent_id="agent-a",
        session_root_space=str(root),
    )
    context.session_workspace = os.path.join(str(root), session_id)
    os.makedirs(context.session_workspace, exist_ok=True)
    return context


def test_session_save_preserves_filesystem_layout_and_payloads(tmp_path):
    context = _context(tmp_path)
    context.add_messages(
        MessageChunk(
            role=MessageRole.USER.value,
            content="hello",
            message_id="message-1",
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                }
            ],
        )
    )

    context.save()

    workspace = tmp_path / "session-a"
    assert {path.name for path in workspace.iterdir()} == {
        "messages.json",
        MESSAGE_JOURNAL_FILE,
        "compact_manifest.json",
        "session_context.json",
        "tools_usage.json",
    }
    assert not (workspace / "messages.json.tmp").exists()

    messages = json.loads((workspace / "messages.json").read_text("utf-8"))
    snapshot = json.loads((workspace / "session_context.json").read_text("utf-8"))
    tools_usage = json.loads((workspace / "tools_usage.json").read_text("utf-8"))

    assert messages[0]["message_id"] == "message-1"
    assert snapshot["session_id"] == "session-a"
    assert snapshot["session_root_space"] == str(tmp_path)
    assert snapshot["session_workspace"] == str(workspace)
    assert "tokens_usage_info" in snapshot
    assert tools_usage == {"search": 1}
    assert (workspace / MESSAGE_JOURNAL_FILE).read_text("utf-8") == ""


def test_server_session_snapshot_omits_token_usage_info(tmp_path, monkeypatch):
    monkeypatch.setenv("SAGE_INTERNAL_SERVER_PROCESS", "1")
    context = _context(tmp_path)

    context.save()

    snapshot = json.loads(
        (tmp_path / "session-a" / "session_context.json").read_text("utf-8")
    )
    assert "tokens_usage_info" not in snapshot


def test_session_save_counts_openai_tool_call_objects(tmp_path):
    context = _context(tmp_path)
    tool_call = chat_completion_chunk.ChoiceDeltaToolCall(
        index=0,
        id="call-1",
        type="function",
        function=chat_completion_chunk.ChoiceDeltaToolCallFunction(
            name="todo_write",
            arguments="{}",
        ),
    )
    context.add_messages(
        MessageChunk(
            role=MessageRole.ASSISTANT.value,
            tool_calls=cast(
                list[dict[str, Any]],
                [tool_call],
            ),
        )
    )

    context.save()

    workspace = tmp_path / "session-a"
    tools_usage = json.loads((workspace / "tools_usage.json").read_text("utf-8"))
    assert tools_usage == {"todo_write": 1}


def test_message_ledger_loads_snapshot_then_replays_journal(tmp_path):
    context = _context(tmp_path)
    workspace = tmp_path / "session-a"
    original = MessageChunk(
        role=MessageRole.USER.value,
        content="old",
        message_id="message-1",
    ).to_dict()
    updated = {**original, "content": "new"}
    appended = MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content="answer",
        message_id="message-2",
    ).to_dict()
    (workspace / "messages.json").write_text(json.dumps([original]), "utf-8")
    records = [
        {
            "schema_version": 1,
            "op": "put_message",
            "session_id": context.session_id,
            "message_id": "message-1",
            "seq": 4,
            "timestamp": 1.0,
            "reason": "update",
            "message": updated,
        },
        {
            "schema_version": 1,
            "op": "put_message",
            "session_id": context.session_id,
            "message_id": "message-2",
            "seq": 5,
            "timestamp": 2.0,
            "reason": "append",
            "message": appended,
        },
    ]
    (workspace / MESSAGE_JOURNAL_FILE).write_text(
        "".join(json.dumps(record) + "\n" for record in records), "utf-8"
    )

    messages, max_sequence, journal_count = (
        SessionContext.load_persisted_message_ledger(
            str(workspace), session_id=context.session_id
        )
    )

    assert [(message.message_id, message.content) for message in messages] == [
        ("message-1", "new"),
        ("message-2", "answer"),
    ]
    assert max_sequence == 5
    assert journal_count == 2


def test_message_ledger_replays_journal_when_snapshot_is_corrupt(tmp_path):
    context = _context(tmp_path)
    workspace = tmp_path / "session-a"
    (workspace / "messages.json").write_text("{truncated", "utf-8")
    message = MessageChunk(
        role=MessageRole.USER.value,
        content="recovered",
        message_id="message-1",
    ).to_dict()
    record = {
        "schema_version": 1,
        "op": "put_message",
        "session_id": context.session_id,
        "message_id": "message-1",
        "seq": 1,
        "timestamp": 1.0,
        "reason": "recovery",
        "message": message,
    }
    (workspace / MESSAGE_JOURNAL_FILE).write_text(
        json.dumps(record) + "\n", "utf-8"
    )

    messages, max_sequence, journal_count = (
        SessionContext.load_persisted_message_ledger(
            str(workspace), session_id=context.session_id
        )
    )

    assert [item.content for item in messages] == ["recovered"]
    assert max_sequence == 1
    assert journal_count == 1


def test_registry_stores_relative_workspace_and_preserves_parent_relation(tmp_path):
    root = tmp_path / "sessions"
    db_path = root / "sessions_index.sqlite"
    workspace = root / "parent" / "sub_sessions" / "child"
    registry = SessionRegistry(str(db_path), root_dir=str(root))
    try:
        registry.register("child", str(workspace), parent_session_id="parent")
        assert registry.get_workspace("child") == str(workspace)
        assert registry.is_sub_session("child") is True
        assert registry.get_parent_session_id("child") == "parent"
    finally:
        registry.close()

    connection = sqlite3.connect(db_path)
    try:
        stored_workspace = connection.execute(
            "SELECT workspace FROM sessions WHERE session_id = ?", ("child",)
        ).fetchone()[0]
    finally:
        connection.close()

    assert stored_workspace == os.path.join("parent", "sub_sessions", "child")


def test_llm_request_files_remain_numbered_json_records(tmp_path):
    context = _context(tmp_path)
    first = context._save_llm_request_sync(
        {"request": {"step_name": "plan"}, "response": {"ok": 1}, "timestamp": 1.0}
    )
    second = context._save_llm_request_sync(
        {"request": {"step_name": "execute"}, "response": {"ok": 2}, "timestamp": 2.0}
    )

    first_stamp = time.strftime("%Y%m%d%H%M%S", time.localtime(1.0))
    second_stamp = time.strftime("%Y%m%d%H%M%S", time.localtime(2.0))
    assert os.path.basename(first) == f"0_plan_{first_stamp}.json"
    assert os.path.basename(second) == f"1_execute_{second_stamp}.json"
    payload = json.loads(open(second, encoding="utf-8").read())
    assert payload == {
        "schema_version": 2,
        "request": {"step_name": "execute"},
        "response": {"ok": 2},
        "metadata": {
            "step_name": "execute",
            "request_view": "pre_adapter_fallback",
        },
        "timestamp": 2.0,
    }
