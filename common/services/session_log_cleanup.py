from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict

from loguru import logger


LLM_REQUEST_DIR_NAME = "llm_request"


def cleanup_old_llm_request_logs(
    sessions_root: str,
    *,
    retention_days: int = 7,
) -> Dict[str, int]:
    root = Path(sessions_root)
    cutoff = time.time() - retention_days * 24 * 60 * 60
    stats = {
        "scanned_dirs": 0,
        "deleted_files": 0,
        "deleted_empty_dirs": 0,
        "errors": 0,
    }

    if not root.exists():
        logger.info(f"LLM request cleanup skipped, sessions root not found: {root}")
        return stats

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
        f"sessions_root={root}, retention_days={retention_days}, stats={stats}"
    )
    return stats
