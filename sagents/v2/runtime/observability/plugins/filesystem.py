"""Redacted filesystem diagnostics that are never a Session data source."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sagents.v2.contracts.common import utc_now
from sagents.v2.model.contracts import ModelRequest, ModelResponse
from sagents.v2.runtime.observability.timing import elapsed_ms


class FilesystemDiagnosticSink:
    """Store redacted model requests beside their owning Session and Run."""

    plugin_id = "sage.observability.filesystem"
    name = "Filesystem diagnostic sink"
    description = "Writes model diagnostics under a filesystem root."
    format_version = "sage.model-diagnostics/v2"
    _kind_aliases = {
        "continuation_judge": "completion_judge",
        "task_complete_judge": "completion_judge",
    }
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

    def __init__(
        self,
        root: str | Path,
        *,
        legacy_root: str | Path | None = None,
    ) -> None:
        # ``root`` is the Session directory itself, not a second diagnostics
        # hierarchy. Records remain non-authoritative even though they are
        # physically colocated with the Run they describe.
        self.root = Path(root).expanduser().resolve()
        self.legacy_root = (
            Path(legacy_root).expanduser().resolve()
            if legacy_root is not None
            else None
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self._migrate_legacy_records()

    async def begin_model_request(
        self,
        *,
        session_id: str,
        request: ModelRequest,
        provider: Mapping[str, Any],
        wire_request: Mapping[str, Any] | None = None,
    ) -> None:
        started_at = utc_now()
        request_payload = self._request_payload(request, wire_request)
        kind = self._request_kind(request, provider)
        record = {
            "format_version": self.format_version,
            "status": "started",
            "kind": kind,
            "session_id": session_id,
            "run_id": request.run_id,
            "request_id": request.request_id,
            "started_at": started_at.isoformat(),
            "request": self._redact(request_payload),
            "metadata": self._redact(
                self._request_metadata(request, provider, request_payload)
            ),
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
            request,
            "completed",
            {
                "response": self._redact(
                    response.model_dump(mode="json", exclude={"provider_metadata"})
                )
            },
        )

    async def record_model_first_token(
        self,
        *,
        session_id: str,
        request: ModelRequest,
        observed_at: datetime,
    ) -> None:
        await asyncio.to_thread(
            self._record_model_first_token,
            session_id,
            request,
            observed_at,
        )

    async def fail_model_request(
        self,
        *,
        session_id: str,
        request: ModelRequest,
        error: Exception,
    ) -> None:
        error_record: dict[str, Any] = {
            "type": type(error).__name__,
            "message": str(error),
        }
        info = getattr(error, "info", None)
        if info is not None:
            error_record.update(
                {
                    "code": getattr(info, "code", None),
                    "category": getattr(
                        getattr(info, "category", None),
                        "value",
                        getattr(info, "category", None),
                    ),
                    "retryable": bool(getattr(info, "retryable", False)),
                    "metadata": dict(getattr(info, "metadata", {}) or {}),
                }
            )
        await asyncio.to_thread(
            self._finish_model_record,
            session_id,
            request,
            "failed",
            {"error": error_record},
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
            path, index = self._new_model_record_path(
                record["session_id"],
                record["run_id"],
                record["kind"],
                record["started_at"],
            )
            record["index"] = index
            self._atomic_json(path, record)

    def _finish_model_record(
        self,
        session_id: str,
        request: ModelRequest,
        status: str,
        update: dict[str, Any],
    ) -> None:
        with self._write_lock:
            path = self._find_model_record_path(
                session_id, request.run_id, request.request_id
            )
            if path is not None:
                record = json.loads(path.read_text(encoding="utf-8"))
            else:
                started_at = utc_now().isoformat()
                kind = self._request_kind(request, {})
                path, index = self._new_model_record_path(
                    session_id,
                    request.run_id,
                    kind,
                    started_at,
                )
                record = {
                    "format_version": self.format_version,
                    "index": index,
                    "kind": kind,
                    "session_id": session_id,
                    "run_id": request.run_id,
                    "request_id": request.request_id,
                    "started_at": started_at,
                    "request": {},
                    "metadata": self._redact(
                        self._request_metadata(request, {}, {})
                    ),
                }
            safe_update = self._redact(update)
            record.update(safe_update)
            record["status"] = status
            record["completed_at"] = utc_now().isoformat()
            duration_ms = elapsed_ms(record.get("started_at"), record["completed_at"])
            ttfb_ms = elapsed_ms(record.get("started_at"), record.get("first_token_at"))
            if duration_ms is not None:
                record["duration_ms"] = duration_ms
            if ttfb_ms is not None:
                record["ttfb_ms"] = ttfb_ms
            self._atomic_json(path, record)

    def _record_model_first_token(
        self,
        session_id: str,
        request: ModelRequest,
        observed_at: datetime,
    ) -> None:
        with self._write_lock:
            path = self._find_model_record_path(
                session_id, request.run_id, request.request_id
            )
            if path is None:
                return
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("first_token_at"):
                return
            record["first_token_at"] = observed_at.isoformat()
            self._atomic_json(path, record)

    def _list_model_requests_sync(
        self, session_id: str, run_id: str | None
    ) -> tuple[dict[str, Any], ...]:
        request_dirs = list(
            self._request_directories(self.root, session_id, run_id, "llm_requests")
        )
        if self.legacy_root is not None:
            request_dirs.extend(
                self._request_directories(
                    self.legacy_root / "sessions", session_id, run_id, "requests"
                )
            )
        records: dict[tuple[str, str], dict[str, Any]] = {}
        # Legacy records are added after current records and must not replace a
        # current colocated copy with the same Run/request identity.
        for request_dir in request_dirs:
            if not request_dir.is_dir():
                continue
            for path in request_dir.glob("*.json"):
                value = json.loads(path.read_text(encoding="utf-8"))
                key = (str(value.get("run_id") or ""), str(value["request_id"]))
                records.setdefault(key, value)
        values = list(records.values())
        values.sort(
            key=lambda value: (
                value.get("started_at", ""),
                value.get("index", -1),
                value["request_id"],
            )
        )
        return tuple(values)

    def _get_model_request_sync(
        self, session_id: str, run_id: str, request_id: str
    ) -> dict[str, Any]:
        path = self._find_model_record_path(session_id, run_id, request_id)
        if path is None and self.legacy_root is not None:
            path = self._find_record_in_directory(
                self.legacy_root
                / "sessions"
                / self._safe_segment(session_id)
                / "runs"
                / self._safe_segment(run_id)
                / "requests",
                request_id,
            )
        if path is None:
            raise FileNotFoundError(f"model request not found: {request_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _request_directory(self, session_id: str, run_id: str) -> Path:
        return (
            self.root
            / self._safe_segment(session_id)
            / "runs"
            / self._safe_segment(run_id)
            / "llm_requests"
        )

    def _request_directories(
        self,
        sessions_root: Path,
        session_id: str,
        run_id: str | None,
        directory_name: str,
    ) -> tuple[Path, ...]:
        session_root = sessions_root / self._safe_segment(session_id)
        if run_id is not None:
            return (
                session_root
                / "runs"
                / self._safe_segment(run_id)
                / directory_name,
            )
        return tuple(session_root.glob(f"runs/*/{directory_name}"))

    def _new_model_record_path(
        self,
        session_id: str,
        run_id: str,
        kind: str,
        started_at: str,
    ) -> tuple[Path, int]:
        directory = self._request_directory(session_id, run_id)
        directory.mkdir(parents=True, exist_ok=True)
        indexes = [
            int(prefix)
            for path in directory.glob("*.json")
            for prefix in (path.name.split("_", 1)[0],)
            if prefix.isdigit()
        ]
        index = max(indexes, default=-1) + 1
        timestamp = self._filename_timestamp(started_at)
        filename = f"{index:08d}_{self._safe_segment(kind)}_{timestamp}.json"
        return directory / filename, index

    def _find_model_record_path(
        self, session_id: str, run_id: str, request_id: str
    ) -> Path | None:
        directory = self._request_directory(session_id, run_id)
        return self._find_record_in_directory(directory, request_id)

    def _find_record_in_directory(
        self, directory: Path, request_id: str
    ) -> Path | None:
        if not directory.is_dir():
            return None
        safe_request_id = self._safe_segment(request_id)
        legacy = directory / f"{safe_request_id}.json"
        if legacy.is_file():
            return legacy
        for path in directory.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("request_id") == request_id:
                return path
        return None

    def _migrate_legacy_records(self) -> None:
        """Move the former parallel diagnostics tree into Session Run folders."""

        if self.legacy_root is None:
            return
        legacy_sessions = self.legacy_root / "sessions"
        if not legacy_sessions.is_dir():
            return
        with self._write_lock:
            sources = sorted(
                legacy_sessions.glob("*/runs/*/requests/*.json"),
                key=lambda path: (
                    self._record_started_at(path),
                    path.name,
                ),
            )
            for source in sources:
                try:
                    record = json.loads(source.read_text(encoding="utf-8"))
                    session_id = str(record["session_id"])
                    run_id = str(record["run_id"])
                    started_at = str(
                        record.get("started_at")
                        or datetime.fromtimestamp(
                            source.stat().st_mtime, tz=timezone.utc
                        ).isoformat()
                    )
                    destination, _ = self._new_model_record_path(
                        session_id,
                        run_id,
                        self._stored_request_kind(record, source.name),
                        started_at,
                    )
                    os.replace(source, destination)
                except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                    # Diagnostics are optional. A malformed legacy record remains
                    # in place instead of blocking SessionStore startup.
                    continue
            if not any(legacy_sessions.glob("*/runs/*/requests/*.json")):
                (self.legacy_root / "journal.jsonl").unlink(missing_ok=True)
                self._remove_empty_directories(self.legacy_root)

    @staticmethod
    def _record_started_at(path: Path) -> str:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            return str(record.get("started_at") or "")
        except (OSError, json.JSONDecodeError):
            return ""

    @classmethod
    def _stored_request_kind(cls, record: Mapping[str, Any], filename: str) -> str:
        raw_kind = record.get("kind")
        if not raw_kind:
            request = record.get("request")
            request = request if isinstance(request, Mapping) else {}
            request_metadata = request.get("metadata")
            request_metadata = (
                request_metadata if isinstance(request_metadata, Mapping) else {}
            )
            metadata = record.get("metadata")
            metadata = metadata if isinstance(metadata, Mapping) else {}
            raw_kind = request_metadata.get("purpose") or metadata.get("purpose")
        if not raw_kind:
            request_id = str(record.get("request_id") or filename)
            if request_id.startswith("continuation_judge"):
                raw_kind = "completion_judge"
            elif request_id.startswith("summary_request"):
                raw_kind = "conversation_summary"
            else:
                raw_kind = "agent"
        normalized = "_".join(
            part
            for part in str(raw_kind).strip().lower().replace("-", "_").split("_")
            if part
        )
        return cls._kind_aliases.get(normalized, normalized or "agent")

    @staticmethod
    def _remove_empty_directories(root: Path) -> None:
        directories = sorted(
            (path for path in root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            try:
                directory.rmdir()
            except OSError:
                continue
        try:
            root.rmdir()
        except OSError:
            return

    @classmethod
    def _request_kind(
        cls, request: ModelRequest, provider: Mapping[str, Any]
    ) -> str:
        purpose = request.metadata.get("purpose") or provider.get("purpose") or "agent"
        normalized = "_".join(
            part
            for part in str(purpose).strip().lower().replace("-", "_").split("_")
            if part
        )
        return cls._kind_aliases.get(normalized, normalized or "agent")

    @staticmethod
    def _request_payload(
        request: ModelRequest, wire_request: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        if wire_request is not None:
            return dict(wire_request)
        return request.model_dump(
            mode="json",
            exclude={"request_id", "run_id", "metadata"},
            exclude_none=True,
        )

    @staticmethod
    def _request_metadata(
        request: ModelRequest,
        provider: Mapping[str, Any],
        request_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        metadata = {
            **dict(provider),
            **dict(request.metadata),
            "model_binding": request.model_binding,
        }
        metadata.pop("purpose", None)
        if request_payload.get("model") == metadata.get("model"):
            metadata.pop("model", None)
        if request_payload.get("model_binding") == metadata.get("model_binding"):
            metadata.pop("model_binding", None)
        if metadata.get("model_type") == metadata.get("model_binding"):
            metadata.pop("model_type", None)
        return {key: value for key, value in metadata.items() if value is not None}

    @staticmethod
    def _filename_timestamp(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return "unknown_time"
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%Y%m%dT%H%M%S%fZ")

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
