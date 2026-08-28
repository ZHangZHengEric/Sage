"""Redacted filesystem diagnostics that are never a Session data source."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sagents.v2.contracts.common import utc_now
from sagents.v2.model.contracts import ModelRequest, ModelResponse


class FilesystemDiagnosticSink:
    """Store redacted model requests under a host-selected diagnostics root."""

    format_version = "sage.model-diagnostics/v1"
    _sensitive_fragments = (
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "credential",
        "cookie",
    )

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()

    async def begin_model_request(
        self,
        *,
        session_id: str,
        request: ModelRequest,
        provider: Mapping[str, Any],
        wire_request: Mapping[str, Any] | None = None,
    ) -> None:
        record = {
            "format_version": self.format_version,
            "status": "started",
            "session_id": session_id,
            "run_id": request.run_id,
            "request_id": request.request_id,
            "started_at": utc_now().isoformat(),
            "provider": self._redact(dict(provider)),
            "request": self._redact(request.model_dump(mode="json")),
            "wire_request": self._redact(dict(wire_request or {})),
        }
        await asyncio.to_thread(self._write_model_record, record)

    async def complete_model_request(
        self,
        *,
        session_id: str,
        request: ModelRequest,
        response: ModelResponse,
    ) -> None:
        await asyncio.to_thread(
            self._finish_model_record,
            session_id,
            request.run_id,
            request.request_id,
            "completed",
            {"response": self._redact(response.model_dump(mode="json"))},
        )

    async def fail_model_request(
        self,
        *,
        session_id: str,
        request: ModelRequest,
        error: Exception,
    ) -> None:
        await asyncio.to_thread(
            self._finish_model_record,
            session_id,
            request.run_id,
            request.request_id,
            "failed",
            {"error": {"type": type(error).__name__, "message": str(error)}},
        )

    async def list_model_requests(
        self, *, session_id: str, run_id: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        return await asyncio.to_thread(
            self._list_model_requests_sync, session_id, run_id
        )

    async def get_model_request(
        self, *, session_id: str, run_id: str, request_id: str
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._get_model_request_sync, session_id, run_id, request_id
        )

    def _write_model_record(self, record: dict[str, Any]) -> None:
        with self._write_lock:
            path = self._model_record_path(
                record["session_id"], record["run_id"], record["request_id"]
            )
            self._atomic_json(path, record)
            self._append_journal(record)

    def _finish_model_record(
        self,
        session_id: str,
        run_id: str,
        request_id: str,
        status: str,
        update: dict[str, Any],
    ) -> None:
        with self._write_lock:
            path = self._model_record_path(session_id, run_id, request_id)
            record = (
                json.loads(path.read_text(encoding="utf-8"))
                if path.exists()
                else {
                    "format_version": self.format_version,
                    "session_id": session_id,
                    "run_id": run_id,
                    "request_id": request_id,
                }
            )
            safe_update = self._redact(update)
            record.update(safe_update)
            record["status"] = status
            record["completed_at"] = utc_now().isoformat()
            self._atomic_json(path, record)
            self._append_journal(
                {
                    "format_version": self.format_version,
                    "status": status,
                    "session_id": session_id,
                    "run_id": run_id,
                    "request_id": request_id,
                    "completed_at": record["completed_at"],
                    **safe_update,
                }
            )

    def _append_journal(self, record: dict[str, Any]) -> None:
        path = self.root / "journal.jsonl"
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _list_model_requests_sync(
        self, session_id: str, run_id: str | None
    ) -> tuple[dict[str, Any], ...]:
        session_root = self.root / "sessions" / self._safe_segment(session_id)
        request_dirs = (
            (session_root / "runs" / self._safe_segment(run_id) / "requests",)
            if run_id is not None
            else tuple(session_root.glob("runs/*/requests"))
        )
        values = [
            json.loads(path.read_text(encoding="utf-8"))
            for request_dir in request_dirs
            if request_dir.is_dir()
            for path in request_dir.glob("*.json")
        ]
        values.sort(
            key=lambda value: (value.get("started_at", ""), value["request_id"])
        )
        return tuple(values)

    def _get_model_request_sync(
        self, session_id: str, run_id: str, request_id: str
    ) -> dict[str, Any]:
        path = self._model_record_path(session_id, run_id, request_id)
        if not path.is_file():
            raise FileNotFoundError(f"model request not found: {request_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _model_record_path(self, session_id: str, run_id: str, request_id: str) -> Path:
        return (
            self.root
            / "sessions"
            / self._safe_segment(session_id)
            / "runs"
            / self._safe_segment(run_id)
            / "requests"
            / f"{self._safe_segment(request_id)}.json"
        )

    @staticmethod
    def _safe_segment(value: str) -> str:
        if not value or value in {".", ".."} or "\\" in value:
            raise ValueError(f"unsafe diagnostic identifier: {value!r}")
        return quote(value, safe="._-@:")

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    "[REDACTED]"
                    if any(
                        fragment in str(key).lower().replace("-", "_")
                        for fragment in cls._sensitive_fragments
                    )
                    else cls._redact(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [cls._redact(item) for item in value]
        if isinstance(value, str) and (
            value.lower().startswith("bearer ")
            or (value.startswith("sk-") and len(value) > 6)
        ):
            return "[REDACTED]"
        return value

    @staticmethod
    def _atomic_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
