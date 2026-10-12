"""Opt-in append-only audit log; never resumes or replays model/tool effects."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from sagents.v2.contracts.common import utc_now


class OptimizationJournal:
    """Exclusive new JSONL file, flushed and fsynced after every event.

    A started call without a completed event has an unknown outcome. Callers must
    reconcile it rather than replaying it. Reports may contain sensitive evidence;
    storage is explicitly caller-selected. No automatic resume is provided.
    """

    def __init__(self, path: str | Path | None, on_event=None):
        self.path = Path(path) if path is not None else None
        self.file = None
        self.sequence = 0
        self.on_event = on_event

    def __enter__(self):
        if self.path is not None:
            # O_EXCL refuses existing paths and symlinks; mode 0600 protects new logs.
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self.file = os.fdopen(fd, "w", encoding="utf-8")
        return self

    def emit(self, event: str, **data):
        if self.file is None and self.on_event is None:
            return
        self.sequence += 1
        record = {
            "sequence": self.sequence,
            "time": utc_now().isoformat(),
            "event": event,
            "data": data,
        }
        if self.file is not None:
            self.file.write(
                json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
            )
            self.file.flush()
            os.fsync(self.file.fileno())
        if self.on_event is not None:
            self.on_event(record)

    def __exit__(self, kind, error, traceback):
        try:
            self.emit(
                "operation_finished",
                status="completed"
                if kind is None
                else (
                    "cancelled"
                    if issubclass(kind, asyncio.CancelledError)
                    else "failed"
                ),
                # Exception messages may contain credentials from host providers.
                error_type=kind.__name__ if kind is not None else None,
            )
        finally:
            if self.file is not None:
                self.file.close()
