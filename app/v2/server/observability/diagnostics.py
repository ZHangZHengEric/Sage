"""Private, best-effort diagnostic evidence; never a recovery data source."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from contextlib import closing
from datetime import datetime
from functools import lru_cache
import json
from pathlib import Path
import re
import sqlite3
from threading import BoundedSemaphore, Lock
from typing import Any

from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.observability.plugins.filesystem import FilesystemDiagnosticSink

REDACTED = "[REDACTED]"
_SECRET_KEY = re.compile(
    r"authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|"
    r"secret|credential|cookie|private[_-]?key|^(?:token|headers|env|environment)$",
    re.I,
)
_SECRET_TEXT = re.compile(
    r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+|\bsk-[A-Za-z0-9_-]{6,}|"
    r"\b(?:[A-Za-z0-9]+_)*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|token)"
    r"\s*[=:]\s*[\"']?[^\s\"'&,;}]+"
)
_URL_QUERY_SECRET = re.compile(
    r"([?&](?:key|sig|signature|auth|credential)=)[^&\s]+", re.I
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----.*?-----END (?:[A-Z ]*PRIVATE KEY)-----",
    re.S,
)
_URL_AUTH = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^\s/@]+(?::[^\s/@]*)?@", re.I)


def redact(value: Any) -> Any:
    """Redact structured credentials, embedded JSON and common inline secrets.

    Also remove secret values from sibling free-text fields in this snapshot.
    Arbitrary unlabelled secrets in prose cannot be recognized reliably.
    """
    secrets: set[str] = set()

    def collect(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if _SECRET_KEY.search(str(key)):
                    if isinstance(child, str) and len(child) >= 4:
                        secrets.add(child)
                else:
                    collect(child)
        elif isinstance(item, (tuple, list)):
            for child in item:
                collect(child)
        elif isinstance(item, str) and item.lstrip().startswith(("{", "[")):
            try:
                collect(json.loads(item))
            except (ValueError, RecursionError):
                pass

    collect(value)
    ordered_secrets = sorted(secrets, key=len, reverse=True)

    @lru_cache(maxsize=32)
    def clean_text(item: str) -> str:
        # Wire and normalized streams often contain the same multi-MiB text.
        # Reuse its sanitized value within this snapshot only: another snapshot
        # may discover a different set of sibling secrets. Keep the cache bounded.
        if item.lstrip().startswith(("{", "[")):
            try:
                return json.dumps(clean(json.loads(item)), ensure_ascii=False)
            except (ValueError, RecursionError):
                pass
        for secret in ordered_secrets:
            item = item.replace(secret, REDACTED)
        item = _PRIVATE_KEY.sub(REDACTED, _SECRET_TEXT.sub(REDACTED, item))
        item = _URL_QUERY_SECRET.sub(r"\1[REDACTED]", item)
        return _URL_AUTH.sub(r"\1[REDACTED]@", item)

    def clean(item):
        if isinstance(item, dict):
            return {
                str(k): REDACTED if _SECRET_KEY.search(str(k)) else clean(v)
                for k, v in item.items()
            }
        if isinstance(item, (tuple, list)):
            return [clean(v) for v in item]
        if isinstance(item, str):
            return clean_text(item)
        return item

    try:
        return clean(value)
    finally:
        # The recursive closures form a cycle; release large cached strings now
        # rather than waiting for cyclic garbage collection.
        clean_text.cache_clear()


class SessionDiagnostics:
    """SQLite in a host-only directory, outside all Agent workspaces.

    Records are keyed by both Session and Run; export additionally checks the
    authoritative Run allowlist. No filesystem paths supplied by a caller are read.
    """

    format_version = "sage.session-diagnostics/v1"
    # A model record combines request/response with two independently bounded
    # 8 MiB streams (provider wire and normalized events). The old 8 MiB row
    # limit discarded otherwise complete captures from ordinary long outputs.
    max_record_bytes = 32 * 1024 * 1024
    max_logs_per_run = 10000
    max_pending_writes = 64

    def __init__(self, root: Path):
        self.path = root / "evidence.sqlite3"
        self.capture_failures = 0
        self.available = True
        self.closed = False
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sage-diagnostics")
        self._write_slots = BoundedSemaphore(self.max_pending_writes)
        self._writer_lock = Lock()
        self._last_write = None
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            root.chmod(0o700)
            if self.path.is_symlink():
                raise ValueError("diagnostic database cannot be a symlink")
            with closing(self._connect()) as db, db:
                db.executescript("""
                    PRAGMA journal_mode=WAL;
                    CREATE TABLE IF NOT EXISTS models (
                        session_id TEXT NOT NULL, run_id TEXT NOT NULL,
                        request_id TEXT NOT NULL, payload TEXT NOT NULL,
                        PRIMARY KEY (session_id, run_id, request_id));
                    CREATE TABLE IF NOT EXISTS logs (
                        id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
                        run_id TEXT NOT NULL, payload TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS log_scope ON logs(session_id, run_id, id);
                    CREATE TABLE IF NOT EXISTS dropped (
                        session_id TEXT NOT NULL, run_id TEXT NOT NULL, count INTEGER NOT NULL,
                        PRIMARY KEY(session_id, run_id));
                """)
            self.path.chmod(0o600)
        except (OSError, ValueError, sqlite3.Error):
            self.available = False
            self.capture_failures += 1

    def _enqueue(self, operation, *args):
        """Diagnostics are ordered, bounded and never hold up execution."""
        with self._writer_lock:
            if self.closed or not self.available or not self._write_slots.acquire(blocking=False):
                self.capture_failures += 1
                return
            try:
                future = self._writer.submit(operation, *args)
            except RuntimeError:
                self._write_slots.release()
                self.capture_failures += 1
                return
            self._last_write = future
            def finished(done):
                self._write_slots.release()
                if done.cancelled():
                    self.capture_failures += 1
            future.add_done_callback(finished)

    def _flush(self):
        with self._writer_lock:
            pending = self._last_write
        if pending is not None:
            try:
                pending.result(timeout=3)
            except FutureTimeoutError:
                self.capture_failures += 1
                return False
            except Exception:
                # Individual writes already account for capture failures.
                pass
        return True

    async def close(self):
        with self._writer_lock:
            if self.closed:
                return
            self.closed = True
        try:
            await asyncio.to_thread(self._flush)
        finally:
            self._writer.shutdown(wait=False, cancel_futures=True)

    def _connect(self):
        if not self.available:
            raise sqlite3.OperationalError("diagnostic storage unavailable")
        return sqlite3.connect(self.path, timeout=1)

    def _encode(self, value):
        encoded = json.dumps(redact(value), ensure_ascii=False)
        if len(encoded.encode()) > self.max_record_bytes:
            return json.dumps(
                {
                    "truncated": True,
                    "reason": "record_size_limit",
                    "original_bytes": len(encoded.encode()),
                    **{
                        key: value[key]
                        for key in ("session_id", "run_id", "request_id", "status")
                        if key in value
                    },
                }
            )
        return encoded

    def _update(self, session_id, request, update):
        try:
            with closing(self._connect()) as db, db:
                row = db.execute(
                    "SELECT payload FROM models WHERE session_id=? AND run_id=? AND request_id=?",
                    (session_id, request.run_id, request.request_id),
                ).fetchone()
                record = json.loads(row[0]) if row else {}
                record.update(update)
                record.update(
                    session_id=session_id,
                    run_id=request.run_id,
                    request_id=request.request_id,
                )
                db.execute(
                    "INSERT OR REPLACE INTO models VALUES(?,?,?,?)",
                    (
                        session_id,
                        request.run_id,
                        request.request_id,
                        self._encode(record),
                    ),
                )
        except Exception:
            self.capture_failures += 1
            raise

    async def begin_model_request(
        self, *, session_id, request, provider, wire_request=None
    ):
        self._enqueue(
            self._update,
            session_id,
            request,
            {
                "format_version": self.format_version,
                "status": "started",
                "started_at": utc_now().isoformat(),
                "request_format": "provider_wire"
                if wire_request is not None
                else "normalized",
                "request": FilesystemDiagnosticSink._request_payload(
                    request, wire_request
                ),
                "metadata": dict(provider),
                "request_metadata": dict(request.metadata),
                "step_id": request.metadata.get("step_id"),
                "turn_id": request.metadata.get("turn_id"),
                "model_binding": getattr(request, "model_binding", None),
                "purpose": request.metadata.get("purpose", "agent"),
            },
        )

    async def complete_model_request(self, *, session_id, request, response):
        self._enqueue(
            self._update,
            session_id,
            request,
            {
                "status": "completed",
                "completed_at": utc_now().isoformat(),
                "response_format": "normalized",
                "response": response.model_dump(mode="json"),
            },
        )

    async def fail_model_request(self, *, session_id, request, error):
        self._enqueue(
            self._update,
            session_id,
            request,
            {
                "status": "failed",
                "completed_at": utc_now().isoformat(),
                "error": {"type": type(error).__name__, "message": str(error),
                          "info": error.info.model_dump(mode="json") if hasattr(error, "info") else None},
            },
        )

    async def record_model_stream(self, *, session_id, request, evidence):
        self._enqueue(self._update, session_id, request, {"stream": evidence})

    async def record_model_first_token(
        self, *, session_id, request, observed_at: datetime
    ):
        self._enqueue(
            self._update,
            session_id,
            request,
            {"first_token_at": observed_at.isoformat()},
        )

    def write(self, record):
        # Process-wide/HTTP records without a trusted Run association are excluded.
        if not self.available or not record.session_id or not record.run_id:
            return
        self._enqueue(self._write_log, record)

    def _write_log(self, record):
        try:
            with closing(self._connect()) as db, db:
                scope = (record.session_id, record.run_id)
                db.execute(
                    "INSERT INTO logs(session_id, run_id, payload) VALUES(?,?,?)",
                    (*scope, self._encode(record.model_dump(mode="json"))),
                )
                deleted = db.execute(
                    """DELETE FROM logs WHERE session_id=? AND run_id=? AND id <=
                    (SELECT id FROM logs WHERE session_id=? AND run_id=? ORDER BY id DESC LIMIT 1 OFFSET ?)""",
                    (*scope, *scope, self.max_logs_per_run),
                ).rowcount
                if deleted:
                    db.execute(
                        """INSERT INTO dropped VALUES(?,?,?) ON CONFLICT(session_id,run_id)
                        DO UPDATE SET count=count+excluded.count""",
                        (*scope, deleted),
                    )
        except Exception:
            self.capture_failures += 1

    def snapshot(self, session_id: str, run_ids: set[str]):
        try:
            flushed = self._flush()
            snapshot = self._snapshot(session_id, run_ids)
            if not flushed:
                snapshot["pending_writes"] = True
            return snapshot
        except (OSError, ValueError, sqlite3.Error):
            return {
                "models": [],
                "logs": [],
                "unavailable": True,
                "capture_failures_since_start": self.capture_failures,
            }

    def _snapshot(self, session_id: str, run_ids: set[str]):
        models, logs, dropped = [], [], 0
        with closing(self._connect()) as db, db:
            db.execute("BEGIN")
            for run_id in sorted(run_ids):
                scope = (session_id, run_id)
                models.extend(
                    json.loads(row[0])
                    for row in db.execute(
                        "SELECT payload FROM models WHERE session_id=? AND run_id=? ORDER BY request_id",
                        scope,
                    )
                )
                logs.extend(
                    json.loads(row[0])
                    for row in db.execute(
                        "SELECT payload FROM logs WHERE session_id=? AND run_id=? ORDER BY id",
                        scope,
                    )
                )
                row = db.execute(
                    "SELECT count FROM dropped WHERE session_id=? AND run_id=?", scope
                ).fetchone()
                dropped += row[0] if row else 0
        models.sort(key=lambda row: (row.get("started_at", ""), row.get("request_id", "")))
        for index, row in enumerate(models, 1):
            row["sequence"] = index
        return {
            "models": models,
            "logs": logs,
            "dropped_logs": dropped,
            "capture_failures_since_start": self.capture_failures,
        }
