import json
import os
import pytest
import time
import zipfile

from sagents.session_runtime import SessionManager
from sagents.storage import SessionStore, StorageError, create_session_store


def test_filesystem_store_implements_session_store_contract(tmp_path):
    store = create_session_store(session_root=str(tmp_path))
    assert isinstance(store, SessionStore)

    workspace = store.create_session_workspace("root-session")
    store.register_session("root-session", workspace)
    child_workspace = store.create_session_workspace(
        "child-session", parent_workspace=workspace
    )
    store.register_session(
        "child-session", child_workspace, parent_session_id="root-session"
    )

    assert store.get_session_workspace("root-session") == workspace
    assert store.get_session_workspace("child-session") == child_workspace
    assert store.get_parent_session_id("child-session") == "root-session"
    assert store.session_exists("child-session")

    store.save_session_snapshot("root-session", {"session_id": "root-session"})
    assert store.load_session_snapshot("root-session") == {
        "session_id": "root-session"
    }

    health = store.healthcheck()
    assert health["backend"] == "filesystem"
    assert health["healthy"] is True
    assert health["available"] is True
    assert health["writable"] is True
    assert health["catalog_ready"] is True


def test_filesystem_store_message_and_telemetry_operations_keep_legacy_layout(
    tmp_path,
):
    store = create_session_store(session_root=str(tmp_path))
    workspace = store.create_session_workspace("session-a")
    store.register_session("session-a", workspace)

    store.save_message_snapshot(
        "session-a", [{"message_id": "m1", "role": "user", "content": "old"}]
    )
    store.append_message_event(
        "session-a",
        {
            "op": "put_message",
            "session_id": "session-a",
            "message_id": "m1",
            "seq": 1,
            "message": {"message_id": "m1", "role": "user", "content": "new"},
        },
    )
    ledger = store.load_message_ledger("session-a")
    assert ledger.messages[0]["content"] == "new"
    assert ledger.max_sequence == 1
    assert ledger.journal_records == 1

    store.save_compact_manifest("session-a", {"version": 1})
    store.save_tools_usage("session-a", {"search": 2})
    store.append_session_log("session-a", "first line\n")
    store.append_session_log("session-a", "second line\n")
    store.save_request_usage("session-a", "request-1", {"total_tokens": 3})
    store.save_mcp_calls("session-a", "request-1", {"calls": []})

    assert json.loads(
        open(os.path.join(workspace, "tools_usage.json"), encoding="utf-8").read()
    ) == {"search": 2}
    assert os.path.isfile(
        os.path.join(workspace, "tokens_usage", "request-1.json")
    )
    assert os.path.isfile(os.path.join(workspace, "mcp_calls", "request-1.json"))
    assert open(
        os.path.join(workspace, "session_session-a.log"), encoding="utf-8"
    ).read() == "first line\nsecond line\n"
    assert store.read_session_log_tail("session-a", max_bytes=12) == "second line\n"
    assert store.read_session_log_tail("missing", max_bytes=100) == ""


def test_session_manager_uses_injected_store_and_migrates_legacy_sessions(tmp_path):
    legacy_workspace = tmp_path / "legacy-session"
    legacy_workspace.mkdir()
    (legacy_workspace / "messages.json").write_text("[]", encoding="utf-8")
    manager = SessionManager(
        str(tmp_path),
        enable_obs=False,
        storage_config={"backend": "filesystem"},
    )

    assert manager.get_session_workspace("legacy-session") == str(legacy_workspace)


def test_filesystem_store_exports_session_without_exposing_directory_walk(tmp_path):
    store = create_session_store(session_root=str(tmp_path))
    workspace = store.create_session_workspace("session-a")
    store.register_session("session-a", workspace)
    store.save_session_snapshot("session-a", {"session_id": "session-a"})

    archive_path = store.export_session_archive("session-a")

    with zipfile.ZipFile(archive_path) as archive:
        assert "session-a/session_context.json" in archive.namelist()


def test_purge_sessions_removes_expired_directory_and_registry_entry(tmp_path):
    store = create_session_store(session_root=str(tmp_path))
    session_id = "proactive_eval_expired"
    workspace = store.create_session_workspace(session_id)
    store.register_session(session_id, workspace)

    expired_at = time.time() - 10 * 24 * 60 * 60
    os.utime(workspace, (expired_at, expired_at))

    stats = store.purge_sessions(
        before=time.time() - 3 * 24 * 60 * 60,
        session_id_prefix="proactive_eval_",
    )

    assert stats["deleted_session_dirs"] == 1
    assert not os.path.exists(workspace)
    assert not store.session_exists(session_id)
    assert session_id not in store.list_sessions()


@pytest.mark.parametrize("session_id", ["..", "../outside", "nested/session", "nested\\session"])
def test_filesystem_store_rejects_path_traversal_session_ids(tmp_path, session_id):
    store = create_session_store(session_root=str(tmp_path))

    with pytest.raises(StorageError, match="invalid session_id"):
        store.create_session_workspace(session_id)


def test_export_session_archive_rejects_workspace_outside_storage_root(tmp_path):
    store = create_session_store(session_root=str(tmp_path))
    session_id = "safe-session"
    outside_workspace = tmp_path.parent / "sage-outside-session"
    outside_workspace.mkdir()
    store.register_session(session_id, str(outside_workspace))

    with pytest.raises(StorageError, match="escapes storage root"):
        store.export_session_archive(session_id)


def test_delete_session_removes_workspace_and_descendant_catalog_entries(tmp_path):
    store = create_session_store(session_root=str(tmp_path))
    parent_id = "parent-session"
    child_id = "child-session"
    parent_workspace = store.create_session_workspace(parent_id)
    store.register_session(parent_id, parent_workspace)
    child_workspace = store.create_session_workspace(
        child_id, parent_workspace=parent_workspace
    )
    store.register_session(child_id, child_workspace, parent_session_id=parent_id)
    store.save_message_snapshot(parent_id, [{"role": "user", "content": "hello"}])
    store.save_message_snapshot(child_id, [{"role": "assistant", "content": "hi"}])

    store.delete_session(parent_id)

    assert not (tmp_path / parent_id).exists()
    assert not store.session_exists(parent_id)
    assert not store.session_exists(child_id)


def test_delete_session_removes_unregistered_legacy_workspace(tmp_path):
    store = create_session_store(session_root=str(tmp_path))
    session_id = "legacy-session"
    workspace = tmp_path / session_id
    workspace.mkdir()
    (workspace / "messages.json").write_text("[]", encoding="utf-8")

    store.delete_session(session_id)

    assert not workspace.exists()
