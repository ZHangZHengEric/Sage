import json
import threading

from sagents.context.session_context import SessionContext


def _runtime_context() -> str:
    return (
        "<runtime_context>\n"
        "<system_context>\n"
        "<current_time>2026-07-05 12:00:00</current_time>\n"
        "<private_workspace>/tmp/work</private_workspace>\n"
        "</system_context>\n"
        "</runtime_context>"
    )


def _bare_context(tmp_path):
    context = object.__new__(SessionContext)
    context.session_id = "sess"
    context.session_workspace = str(tmp_path)
    context._runtime_context_snapshot_lock = threading.Lock()
    context._runtime_context_snapshot_keys = set()
    context._runtime_context_snapshot_keys_loaded = False
    return context


def test_append_runtime_context_snapshot_writes_jsonl(tmp_path):
    context = _bare_context(tmp_path)

    path = context.append_runtime_context_snapshot(
        message_id="msg-1",
        runtime_context=_runtime_context(),
    )

    assert path == str(tmp_path / "runtime_context_snapshots.jsonl")
    lines = (tmp_path / "runtime_context_snapshots.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 1

    snapshot = json.loads(lines[0])
    assert snapshot["snapshot_key"] == "msg-1"
    assert snapshot["session_id"] == "sess"
    assert snapshot["message_id"] == "msg-1"
    assert (
        snapshot["current_time_context"]
        == "<current_time>2026-07-05 12:00:00</current_time>"
    )
    assert "<runtime_context>" in snapshot["runtime_context"]
    assert "<private_workspace>/tmp/work</private_workspace>" in snapshot[
        "runtime_context"
    ]


def test_append_runtime_context_snapshot_deduplicates_message_id(tmp_path):
    context = _bare_context(tmp_path)

    first = context.append_runtime_context_snapshot(
        message_id="msg-1",
        runtime_context=_runtime_context(),
    )
    second = context.append_runtime_context_snapshot(
        message_id="msg-1",
        runtime_context=_runtime_context().replace("/tmp/work", "/tmp/other"),
    )

    assert first is not None
    assert second is None
    lines = (tmp_path / "runtime_context_snapshots.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 1


def test_append_runtime_context_snapshot_loads_existing_keys(tmp_path):
    snapshot_file = tmp_path / "runtime_context_snapshots.jsonl"
    snapshot_file.write_text(
        json.dumps(
            {
                "snapshot_key": "msg-1",
                "session_id": "sess",
                "message_id": "msg-1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    context = _bare_context(tmp_path)

    result = context.append_runtime_context_snapshot(
        message_id="msg-1",
        runtime_context=_runtime_context(),
    )

    assert result is None
    assert len(snapshot_file.read_text(encoding="utf-8").splitlines()) == 1
