import json
import os
import threading
import time

import sagents.context.session_context as session_context_module
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import (
    MESSAGE_JOURNAL_FILE,
    SessionContext,
)
from sagents.session_runtime import Session


def _make_session(tmp_path):
    ctx = SessionContext(
        session_id="sess_journal",
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
    )
    ctx.session_workspace = os.path.join(str(tmp_path), "sess_journal")
    os.makedirs(ctx.session_workspace, exist_ok=True)
    return ctx


def _journal_path(ctx):
    return os.path.join(ctx.session_workspace, MESSAGE_JOURNAL_FILE)


def _read_journal(ctx):
    path = _journal_path(ctx)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _assistant_chunk(message_id, content, is_final=False):
    return MessageChunk(
        role=MessageRole.ASSISTANT.value,
        content=content,
        message_id=message_id,
        message_type=MessageType.DO_SUBTASK_RESULT.value,
        is_final=is_final,
    )


def test_message_journal_writes_user_message_immediately(tmp_path):
    ctx = _make_session(tmp_path)

    ctx.add_messages(
        MessageChunk(
            role=MessageRole.USER.value,
            content="please do this",
            message_id="u1",
        )
    )

    records = _read_journal(ctx)
    assert len(records) == 1
    assert records[0]["message_id"] == "u1"
    assert records[0]["message"]["content"] == "please do this"


def test_message_journal_writes_previous_message_on_id_switch(tmp_path):
    ctx = _make_session(tmp_path)

    ctx.add_messages(_assistant_chunk("m1", "hello"))
    ctx.add_messages(_assistant_chunk("m1", " world"))
    assert _read_journal(ctx) == []

    ctx.add_messages(_assistant_chunk("m2", "next"))

    records = _read_journal(ctx)
    assert len(records) == 1
    assert records[0]["op"] == "put_message"
    assert records[0]["message_id"] == "m1"
    assert records[0]["message"]["content"] == "hello world"


def test_user_boundary_does_not_duplicate_previous_message_journal(tmp_path):
    ctx = _make_session(tmp_path)

    ctx.add_messages(_assistant_chunk("m1", "hello"))
    ctx.add_messages(
        MessageChunk(
            role=MessageRole.USER.value,
            content="next request",
            message_id="u1",
        )
    )

    records = _read_journal(ctx)
    assert [record["message_id"] for record in records] == ["m1", "u1"]


def test_save_flushes_current_message_and_clears_journal_after_snapshot(tmp_path):
    ctx = _make_session(tmp_path)

    ctx.add_messages(_assistant_chunk("m1", "hello"))
    ctx.add_messages(_assistant_chunk("m2", "next"))
    assert _read_journal(ctx)

    ctx.save()

    assert _read_journal(ctx) == []
    messages_path = os.path.join(ctx.session_workspace, "messages.json")
    with open(messages_path, "r", encoding="utf-8") as f:
        messages = json.load(f)
    assert [message["message_id"] for message in messages] == ["m1", "m2"]
    assert messages[-1]["content"] == "next"


def test_duplicate_save_with_message_still_skips_when_journal_is_clean(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.add_messages(_assistant_chunk("m1", "hello"))

    ctx.save()
    ctx.save()

    session_end_events = [
        event
        for event in ctx.execution_timeline_events
        if event.get("event_type") == "session_end"
    ]
    assert len(session_end_events) == 1
    assert _read_journal(ctx) == []


def test_concurrent_add_after_snapshot_replace_survives_journal_clear(
    tmp_path, monkeypatch
):
    ctx = _make_session(tmp_path)
    ctx.add_messages(_assistant_chunk("m1", "hello"))

    original_replace = session_context_module.os.replace
    started = threading.Event()
    finished = threading.Event()
    worker_errors = []

    def add_message_after_replace():
        try:
            started.set()
            ctx.add_messages(_assistant_chunk("m2", "after save", is_final=True))
        except Exception as exc:
            worker_errors.append(exc)
        finally:
            finished.set()

    def replace_and_start_concurrent_add(src, dst):
        original_replace(src, dst)
        worker = threading.Thread(target=add_message_after_replace)
        worker.start()
        assert started.wait(timeout=2)
        time.sleep(0.05)

    monkeypatch.setattr(
        session_context_module.os,
        "replace",
        replace_and_start_concurrent_add,
    )

    ctx.save()

    assert finished.wait(timeout=2)
    assert worker_errors == []
    records = _read_journal(ctx)
    assert [record["message_id"] for record in records] == ["m2"]
    assert records[0]["message"]["content"] == "after save"


def test_load_persisted_message_ledger_replays_journal_and_upserts(tmp_path):
    ctx = _make_session(tmp_path)
    snapshot_message = _assistant_chunk("m1", "old").to_dict()
    messages_path = os.path.join(ctx.session_workspace, "messages.json")
    with open(messages_path, "w", encoding="utf-8") as f:
        json.dump([snapshot_message], f)

    journal_path = _journal_path(ctx)
    records = [
        {
            "schema_version": 1,
            "op": "put_message",
            "session_id": ctx.session_id,
            "message_id": "m1",
            "seq": 1,
            "timestamp": 1.0,
            "message": _assistant_chunk("m1", "new").to_dict(),
        },
        {
            "schema_version": 1,
            "op": "put_message",
            "session_id": ctx.session_id,
            "message_id": "m2",
            "seq": 2,
            "timestamp": 2.0,
            "message": _assistant_chunk("m2", "second").to_dict(),
        },
    ]
    with open(journal_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    messages, max_seq, journal_records = SessionContext.load_persisted_message_ledger(
        ctx.session_workspace,
        session_id=ctx.session_id,
    )

    assert max_seq == 2
    assert journal_records == 2
    assert [message.message_id for message in messages] == ["m1", "m2"]
    assert [message.content for message in messages] == ["new", "second"]


def test_load_persisted_message_ledger_handles_journal_without_snapshot(tmp_path):
    ctx = _make_session(tmp_path)
    journal_path = _journal_path(ctx)
    record = {
        "schema_version": 1,
        "op": "put_message",
        "session_id": ctx.session_id,
        "message_id": "m1",
        "seq": 1,
        "timestamp": 1.0,
        "message": _assistant_chunk("m1", "journal only").to_dict(),
    }
    with open(journal_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    messages, max_seq, journal_records = SessionContext.load_persisted_message_ledger(
        ctx.session_workspace,
        session_id=ctx.session_id,
    )

    assert max_seq == 1
    assert journal_records == 1
    assert [message.content for message in messages] == ["journal only"]


def test_load_persisted_message_ledger_skips_bad_and_other_session_records(tmp_path):
    ctx = _make_session(tmp_path)
    journal_path = _journal_path(ctx)
    valid_record = {
        "schema_version": 1,
        "op": "put_message",
        "session_id": ctx.session_id,
        "message_id": "m1",
        "seq": 3,
        "timestamp": 3.0,
        "message": _assistant_chunk("m1", "valid").to_dict(),
    }
    other_session_record = {
        "schema_version": 1,
        "op": "put_message",
        "session_id": "other",
        "message_id": "m2",
        "seq": 2,
        "timestamp": 2.0,
        "message": _assistant_chunk("m2", "other").to_dict(),
    }
    with open(journal_path, "w", encoding="utf-8") as f:
        f.write("{bad json\n")
        f.write(json.dumps(other_session_record, ensure_ascii=False) + "\n")
        f.write(json.dumps(valid_record, ensure_ascii=False) + "\n")

    messages, max_seq, journal_records = SessionContext.load_persisted_message_ledger(
        ctx.session_workspace,
        session_id=ctx.session_id,
    )

    assert max_seq == 3
    assert journal_records == 1
    assert [message.message_id for message in messages] == ["m1"]
    assert messages[0].content == "valid"


def test_save_failure_keeps_journal_for_later_replay(tmp_path, monkeypatch):
    ctx = _make_session(tmp_path)
    ctx.add_messages(_assistant_chunk("m1", "hello"))
    ctx.flush_message_journal_current(reason="test")

    def fail_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(session_context_module.os, "replace", fail_replace)

    ctx.save()

    records = _read_journal(ctx)
    assert records
    assert records[-1]["message_id"] == "m1"
    tmp_path = os.path.join(ctx.session_workspace, "messages.json.tmp")
    assert not os.path.exists(tmp_path)


def test_save_without_session_workspace_does_not_crash(tmp_path):
    ctx = SessionContext(
        session_id="no_workspace",
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
    )

    ctx.save()

    session_end_events = [
        event
        for event in ctx.execution_timeline_events
        if event.get("event_type") == "session_end"
    ]
    assert len(session_end_events) == 1


def test_session_runtime_get_messages_replays_journal(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.add_messages(_assistant_chunk("m1", "hello"))
    ctx.flush_message_journal_current(reason="test")

    session = Session(session_id=ctx.session_id, enable_obs=False)
    session.set_workspace(ctx.session_workspace)

    messages = session.get_messages()

    assert [message.message_id for message in messages] == ["m1"]
    assert messages[0].content == "hello"
