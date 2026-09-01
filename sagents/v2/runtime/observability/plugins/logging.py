"""Official structured-log sink implementations."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import TextIO

from sagents.v2.runtime.observability.contracts import LogLevel, LogRecord
from sagents.v2.runtime.observability.logs import encode_log_record


_LEVEL_ORDER = {
    LogLevel.DEBUG: 10,
    LogLevel.INFO: 20,
    LogLevel.WARNING: 30,
    LogLevel.ERROR: 40,
    LogLevel.CRITICAL: 50,
}


class FilesystemLogSink:
    """Append redacted JSONL records with bounded local file rotation."""

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
        if _LEVEL_ORDER[record.level] < _LEVEL_ORDER[self.min_level]:
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


class StdoutLogSink:
    """Write one redacted JSONL record per line to stdout or stderr."""

    format_version = "sage.log/v1"

    def __init__(
        self,
        *,
        stream: str = "stdout",
        min_level: LogLevel | str = LogLevel.INFO,
        output: TextIO | None = None,
    ) -> None:
        target = str(stream).strip().lower()
        if target not in {"stdout", "stderr"}:
            raise ValueError("stream must be 'stdout' or 'stderr'")
        self.stream = target
        self.min_level = LogLevel(min_level)
        self._output = output
        self._write_lock = threading.Lock()

    def write(self, record: LogRecord) -> None:
        if _LEVEL_ORDER[record.level] < _LEVEL_ORDER[self.min_level]:
            return
        line = encode_log_record(record)
        with self._write_lock:
            handle = self._output or (
                sys.stderr if self.stream == "stderr" else sys.stdout
            )
            handle.write(line)
            handle.flush()

    def close(self) -> None:
        return None
