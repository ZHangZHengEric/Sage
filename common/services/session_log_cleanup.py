from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Dict

from loguru import logger


LLM_REQUEST_DIR_NAME = "llm_request"
PROACTIVE_EVAL_SESSION_PREFIX = "proactive_eval_"


def _latest_tree_mtime(path: Path) -> float:
    latest = path.stat().st_mtime
    for child in path.rglob("*"):
        if child.is_symlink():
            continue
        try:
            latest = max(latest, child.stat().st_mtime)
        except OSError:
            continue
    return latest


def cleanup_old_llm_request_logs(
    sessions_root: str,
    *,
    retention_days: int = 7,
    proactive_eval_retention_days: int = 3,
) -> Dict[str, int]:
    root = Path(sessions_root)
    cutoff = time.time() - retention_days * 24 * 60 * 60
    proactive_eval_cutoff = time.time() - proactive_eval_retention_days * 24 * 60 * 60
    stats = {
        "scanned_proactive_eval_dirs": 0,
        "deleted_session_dirs": 0,
        "scanned_dirs": 0,
        "deleted_files": 0,
        "deleted_empty_dirs": 0,
        "errors": 0,
    }

    if not root.exists():
        logger.info(f"LLM request cleanup skipped, sessions root not found: {root}")
        return stats

    for session_dir in root.iterdir():
        if (
            session_dir.is_symlink()
            or not session_dir.is_dir()
            or not session_dir.name.startswith(PROACTIVE_EVAL_SESSION_PREFIX)
        ):
            continue
        stats["scanned_proactive_eval_dirs"] += 1
        try:
            if _latest_tree_mtime(session_dir) >= proactive_eval_cutoff:
                continue
            shutil.rmtree(session_dir)
            stats["deleted_session_dirs"] += 1
        except Exception as exc:
            stats["errors"] += 1
            logger.warning(
                f"Failed to delete old proactive eval session {session_dir}: {exc}"
            )

    for request_dir in root.glob(f"**/{LLM_REQUEST_DIR_NAME}"):
        if not request_dir.is_dir():
            continue
        stats["scanned_dirs"] += 1
        try:
            for path in request_dir.iterdir():
                if path.is_dir():
                    continue
                try:
                    if path.stat().st_mtime >= cutoff:
                        continue
                    path.unlink()
                    stats["deleted_files"] += 1
                except Exception as exc:
                    stats["errors"] += 1
                    logger.warning(
                        f"Failed to delete old LLM request log {path}: {exc}"
                    )

            try:
                if not any(request_dir.iterdir()):
                    os.rmdir(request_dir)
                    stats["deleted_empty_dirs"] += 1
            except OSError:
                pass
        except Exception as exc:
            stats["errors"] += 1
            logger.warning(f"Failed to scan LLM request log dir {request_dir}: {exc}")

    logger.info(
        "LLM request cleanup finished: "
        f"sessions_root={root}, retention_days={retention_days}, "
        f"proactive_eval_retention_days={proactive_eval_retention_days}, stats={stats}"
    )
    return stats
