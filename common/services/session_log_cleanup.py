from __future__ import annotations

import time
from pathlib import Path
from typing import Dict

from loguru import logger
from sagents.storage import create_session_store

PROACTIVE_EVAL_SESSION_PREFIX = "proactive_eval_"


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

    store = create_session_store(session_root=str(root), initialize=False)
    proactive_stats = store.purge_sessions(
        before=proactive_eval_cutoff,
        session_id_prefix=PROACTIVE_EVAL_SESSION_PREFIX,
    )
    stats["scanned_proactive_eval_dirs"] = proactive_stats["scanned_dirs"]
    stats["deleted_session_dirs"] = proactive_stats["deleted_session_dirs"]
    request_stats = store.purge_llm_requests(before=cutoff)
    for key in ("scanned_dirs", "deleted_files", "deleted_empty_dirs"):
        stats[key] = request_stats[key]
    stats["errors"] = proactive_stats["errors"] + request_stats["errors"]

    logger.info(
        "LLM request cleanup finished: "
        f"sessions_root={root}, retention_days={retention_days}, "
        f"proactive_eval_retention_days={proactive_eval_retention_days}, stats={stats}"
    )
    return stats
