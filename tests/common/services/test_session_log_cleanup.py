import os
import time

from common.services.session_log_cleanup import cleanup_old_llm_request_logs


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
