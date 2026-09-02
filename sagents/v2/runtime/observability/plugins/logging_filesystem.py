"""Official structured-log sink: rotating local JSONL files."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from sagents.v2.runtime.observability.contracts import LogLevel, LogRecord
from sagents.v2.runtime.observability.logs import (
    encode_log_record,
    record_reaches_min_level,
)


class FilesystemLogSink:
    """Append redacted JSONL records with bounded local file rotation."""

    plugin_id = "sage.logging.filesystem"
    name = "Rotating filesystem structured log sink"
    description = "Writes rotating JSONL operational logs to disk."
    format_version = "sage.log/v1"

    def __init__(
        self,
        root: str | Path,
        *,
        filename: str = "sage.jsonl",
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
        min_level: LogLevel | str = LogLevel.INFO,
    ) -> None:
        if max_bytes < 1024:
            raise ValueError("max_bytes must be at least 1024")
        if backup_count < 1:
            raise ValueError("backup_count must be positive")
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.path = self.root / Path(filename).name
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.min_level = LogLevel(min_level)
        self._write_lock = threading.Lock()

    def write(self, record: LogRecord) -> None:
        if not record_reaches_min_level(record.level, self.min_level):
            return
        encoded = encode_log_record(record).encode("utf-8")
        with self._write_lock:
            self._rotate_if_needed(len(encoded))
            descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "ab", buffering=0) as stream:
                stream.write(encoded)
            self.path.chmod(0o600)

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        current_size = self.path.stat().st_size if self.path.exists() else 0
        if current_size == 0 or current_size + incoming_bytes <= self.max_bytes:
            return
        oldest = self.path.with_name(f"{self.path.name}.{self.backup_count}")
        oldest.unlink(missing_ok=True)
        for index in range(self.backup_count - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                source.replace(self.path.with_name(f"{self.path.name}.{index + 1}"))
        self.path.replace(self.path.with_name(f"{self.path.name}.1"))

    def close(self) -> None:
        return None
