"""Lossless, Session-local content-addressed media for diagnostic records."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

_MARKER = "$sage_diagnostic_media"
_HASH = re.compile(r"[0-9a-f]{64}")


class DiagnosticMediaStore:
    """Externalize inline media only; model inputs and canonical history stay intact."""

    def __init__(self, session_directory: Path) -> None:
        self.root = session_directory / "diagnostics" / "media"

    def externalize(self, value: Any, *, media_data: bool = False) -> Any:
        if isinstance(value, str):
            if (value.startswith("data:") and ";base64," in value) or (
                media_data and len(value) >= 256
            ):
                data = value.encode("utf-8")
                digest = hashlib.sha256(data).hexdigest()
                path = self.root / f"{digest}.txt"
                if not path.exists():
                    self._atomic_write(path, data)
                return {
                    _MARKER: {"sha256": digest, "bytes": len(data), "encoding": "utf-8"}
                }
            return value
        if isinstance(value, list):
            return [self.externalize(item) for item in value]
        if isinstance(value, dict):
            # Anthropic/Gemini inline media and OpenAI input audio/file data.
            inline = (
                value.get("type") == "base64"
                or "mime_type" in value
                or "mimeType" in value
                or value.get("format") in ("wav", "mp3", "flac", "ogg", "pcm16")
            )
            return {
                key: self.externalize(
                    item,
                    media_data=(key == "data" and inline)
                    or key in {"file_data", "b64_json"},
                )
                for key, item in value.items()
            }
        return value

    def restore(self, value: Any) -> Any:
        if isinstance(value, list):
            return [self.restore(item) for item in value]
        if isinstance(value, dict):
            if set(value) == {_MARKER}:
                ref = value[_MARKER]
                if (
                    not isinstance(ref, dict)
                    or ref.get("encoding") != "utf-8"
                    or not isinstance(ref.get("sha256"), str)
                    or not _HASH.fullmatch(ref["sha256"])
                ):
                    raise ValueError("invalid diagnostic media reference")
                path = (self.root / f"{ref['sha256']}.txt").resolve()
                path.relative_to(self.root.resolve())
                data = path.read_bytes()
                if (
                    len(data) != ref.get("bytes")
                    or hashlib.sha256(data).hexdigest() != ref["sha256"]
                ):
                    raise ValueError("diagnostic media integrity check failed")
                return data.decode("utf-8")
            return {key: self.restore(item) for key, item in value.items()}
        return value

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".media-", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
