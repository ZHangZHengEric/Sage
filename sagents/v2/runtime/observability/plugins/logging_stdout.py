"""Official structured-log sink: one JSONL line per record on stdout or stderr."""

from __future__ import annotations

import sys
import threading
from typing import TextIO

from sagents.v2.runtime.observability.contracts import LogLevel, LogRecord
from sagents.v2.runtime.observability.logs import (
    encode_log_record,
    record_reaches_min_level,
)


class StdoutLogSink:
    """Write one redacted JSONL record per line to stdout or stderr."""

    plugin_id = "sage.logging.stdout"
    name = "Stdout structured log sink"
    description = "Writes one JSONL record per line to stdout or stderr."
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
        if not record_reaches_min_level(record.level, self.min_level):
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
