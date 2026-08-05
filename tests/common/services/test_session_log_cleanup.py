import os
import time

from common.services.session_log_cleanup import cleanup_old_llm_request_logs


def _set_tree_mtime(path, mtime):
    for child in path.rglob("*"):
        os.utime(child, (mtime, mtime))
    os.utime(path, (mtime, mtime))


def test_cleanup_old_llm_request_logs_removes_only_expired_files(tmp_path):
    session_dir = tmp_path / "session_a"
    old_dir = session_dir / "llm_request"
    old_dir.mkdir(parents=True)

    old_file = old_dir / "old.json"
    recent_file = old_dir / "recent.json"

    old_file.write_text("old", encoding="utf-8")
    recent_file.write_text("recent", encoding="utf-8")

    old_mtime = time.time() - 8 * 24 * 60 * 60
    os.utime(old_file, (old_mtime, old_mtime))

    stats = cleanup_old_llm_request_logs(str(tmp_path), retention_days=7)

    assert not old_file.exists()
    assert recent_file.exists()
    assert stats["deleted_files"] == 1


def test_cleanup_removes_expired_proactive_eval_session_directory(tmp_path):
    session_dir = tmp_path / "proactive_eval_expired"
    llm_request_dir = session_dir / "llm_request"
    llm_request_dir.mkdir(parents=True)
    (llm_request_dir / "request.json").write_text("request", encoding="utf-8")
    (session_dir / "result.json").write_text("result", encoding="utf-8")

    old_mtime = time.time() - 4 * 24 * 60 * 60
    _set_tree_mtime(session_dir, old_mtime)

    stats = cleanup_old_llm_request_logs(str(tmp_path), retention_days=7)

    assert not session_dir.exists()
    assert stats["deleted_session_dirs"] == 1


def test_cleanup_keeps_proactive_eval_session_with_recent_activity(tmp_path):
    session_dir = tmp_path / "proactive_eval_active"
    session_dir.mkdir()
    old_file = session_dir / "result.json"
    old_file.write_text("old", encoding="utf-8")

    old_mtime = time.time() - 4 * 24 * 60 * 60
    _set_tree_mtime(session_dir, old_mtime)

    recent_file = session_dir / "heartbeat"
    recent_file.write_text("active", encoding="utf-8")

    stats = cleanup_old_llm_request_logs(str(tmp_path), retention_days=7)

    assert session_dir.exists()
    assert stats["deleted_session_dirs"] == 0
