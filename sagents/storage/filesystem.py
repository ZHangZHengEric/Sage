"""Filesystem implementation preserving Sage's historical file contract."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Optional

from sagents.session_registry import SessionRegistry
from sagents.storage.base import MessageLedger, SessionStore, StorageError


MESSAGE_SNAPSHOT_FILE = "messages.json"
MESSAGE_JOURNAL_FILE = "messages.journal.jsonl"
SESSION_SNAPSHOT_FILE = "session_context.json"


class _FilesystemSessionStore(SessionStore):
    """SQLite catalog plus JSON/JSONL session payloads on local disk."""

    def __init__(self, root: str, *, auto_initialize: bool = True):
        self._root = os.path.abspath(str(root))
        self._registry: Optional[SessionRegistry] = None
        self._workspace_hints: dict[str, str] = {}
        self._llm_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        if auto_initialize:
            self.initialize()

    @property
    def root(self) -> str:
        return self._root

    @property
    def registry_path(self) -> str:
        return os.path.join(self._root, "sessions_index.sqlite")

    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        value = str(session_id or "")
        if (
            not value
            or value != value.strip()
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or "\x00" in value
        ):
            raise StorageError("invalid session_id")
        return value

    def initialize(self) -> None:
        os.makedirs(self._root, exist_ok=True)
        if self._registry is None:
            self._registry = SessionRegistry(self.registry_path, root_dir=self._root)

    def close(self) -> None:
        if self._registry is not None:
            self._registry.close()
            self._registry = None

    def healthcheck(self) -> Mapping[str, Any]:
        root_exists = os.path.isdir(self._root)
        writable = os.access(self._root, os.W_OK) if root_exists else os.access(
            os.path.dirname(self._root) or ".", os.W_OK
        )
        return {
            "backend": "filesystem",
            "initialized": self._registry is not None,
            "healthy": root_exists and writable,
            "available": root_exists,
            "writable": writable,
            "catalog_ready": os.path.isfile(self.registry_path),
        }

    def _catalog(self) -> SessionRegistry:
        self.initialize()
        assert self._registry is not None
        return self._registry

    def register_session(self, session_id, workspace, parent_session_id=None) -> None:
        safe_session_id = self._validate_session_id(session_id)
        safe_parent_id = (
            self._validate_session_id(parent_session_id)
            if parent_session_id is not None
            else None
        )
        self._catalog().register(safe_session_id, workspace, safe_parent_id)

    def register_sessions(self, entries) -> None:
        normalized = []
        for session_id, workspace, parent_session_id in entries:
            safe_session_id = self._validate_session_id(session_id)
            safe_parent_id = (
                self._validate_session_id(parent_session_id)
                if parent_session_id is not None
                else None
            )
            normalized.append((safe_session_id, workspace, safe_parent_id))
        self._catalog().register_batch(normalized)

    def get_session_workspace(self, session_id: str) -> Optional[str]:
        return self._catalog().get_workspace(self._validate_session_id(session_id))

    def session_exists(self, session_id: str) -> bool:
        return self._catalog().exists(self._validate_session_id(session_id))

    def get_parent_session_id(self, session_id: str) -> Optional[str]:
        return self._catalog().get_parent_session_id(
            self._validate_session_id(session_id)
        )

    def remove_session(self, session_id: str) -> None:
        self._catalog().remove(self._validate_session_id(session_id))

    def delete_session(self, session_id: str) -> None:
        safe_session_id = self._validate_session_id(session_id)
        catalog = self._catalog()
        workspace = catalog.get_workspace(safe_session_id) or os.path.join(
            self._root, safe_session_id
        )

        session_ids = {safe_session_id}
        registered_ids = set(catalog.list_all())
        while True:
            descendants = {
                candidate
                for candidate in registered_ids - session_ids
                if catalog.get_parent_session_id(candidate) in session_ids
            }
            if not descendants:
                break
            session_ids.update(descendants)

        storage_root = Path(self._root).resolve()
        target = Path(workspace)
        resolved_target = target.resolve()
        try:
            resolved_target.relative_to(storage_root)
        except ValueError as exc:
            raise StorageError("session workspace escapes storage root") from exc
        if resolved_target == storage_root:
            raise StorageError("refusing to delete session storage root")
        if target.is_symlink():
            raise StorageError("refusing to delete symlinked session workspace")
        if target.exists():
            if not target.is_dir():
                raise StorageError("session workspace is not a directory")
            shutil.rmtree(target)

        catalog.remove_many(list(session_ids))
        for deleted_session_id in session_ids:
            self._workspace_hints.pop(deleted_session_id, None)
            self._llm_locks.pop(deleted_session_id, None)

    def list_sessions(self) -> Mapping[str, str]:
        return self._catalog().list_all()

    def migrate_legacy_sessions(self) -> int:
        entries = self._discover_legacy_sessions()
        if entries:
            self.register_sessions(entries)
        return len(entries)

    def _discover_legacy_sessions(self):
        entries: list[tuple[str, str, Optional[str]]] = []
        if not os.path.isdir(self._root):
            return entries
        with os.scandir(self._root) as roots:
            for entry in roots:
                if not entry.is_dir():
                    continue
                if self._has_session_payload(entry.path):
                    entries.append((entry.name, entry.path, None))
                children = os.path.join(entry.path, "sub_sessions")
                if not os.path.isdir(children):
                    continue
                with os.scandir(children) as child_entries:
                    for child in child_entries:
                        if child.is_dir() and self._has_session_payload(child.path):
                            entries.append((child.name, child.path, entry.name))
        return entries

    @staticmethod
    def _has_session_payload(workspace: str) -> bool:
        return any(
            os.path.exists(os.path.join(workspace, filename))
            for filename in (SESSION_SNAPSHOT_FILE, MESSAGE_SNAPSHOT_FILE)
        )

    def create_session_workspace(self, session_id, *, parent_workspace=None) -> str:
        safe_session_id = self._validate_session_id(session_id)
        if parent_workspace:
            workspace = os.path.join(parent_workspace, "sub_sessions", safe_session_id)
        else:
            workspace = os.path.join(self._root, safe_session_id)
        os.makedirs(workspace, exist_ok=True)
        self.bind_session_workspace(safe_session_id, workspace)
        return workspace

    def bind_session_workspace(self, session_id: str, workspace: str) -> None:
        safe_session_id = self._validate_session_id(session_id)
        self._workspace_hints[safe_session_id] = os.path.abspath(str(workspace))

    def _workspace(self, session_id: str) -> str:
        safe_session_id = self._validate_session_id(session_id)
        hinted = self._workspace_hints.get(safe_session_id)
        if hinted:
            return hinted
        workspace = self.get_session_workspace(safe_session_id)
        if workspace:
            return workspace
        return os.path.join(self._root, safe_session_id)

    @staticmethod
    def _read_json(path: str) -> Optional[Any]:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as stream:
            return json.load(stream)

    @staticmethod
    def _write_json(path: str, value: Any, *, indent: int) -> str:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=indent)
        return path

    def load_session_snapshot(self, session_id):
        value = self._read_json(
            os.path.join(self._workspace(session_id), SESSION_SNAPSHOT_FILE)
        )
        return value if isinstance(value, dict) else None

    def save_session_snapshot(self, session_id, snapshot):
        return self._write_json(
            os.path.join(self._workspace(session_id), SESSION_SNAPSHOT_FILE),
            dict(snapshot),
            indent=4,
        )

    def load_message_ledger(self, session_id):
        workspace = self._workspace(session_id)
        try:
            raw_messages = self._read_json(
                os.path.join(workspace, MESSAGE_SNAPSHOT_FILE)
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            # The append-only journal remains recoverable when a snapshot is
            # truncated or uses an unreadable legacy encoding.
            raw_messages = []
        messages = [dict(item) for item in raw_messages or [] if isinstance(item, dict)]
        max_sequence = 0
        count = 0
        journal = os.path.join(workspace, MESSAGE_JOURNAL_FILE)
        if os.path.exists(journal):
            with open(journal, "r", encoding="utf-8") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (
                        not isinstance(record, dict)
                        or record.get("op") != "put_message"
                    ):
                        continue
                    owner = record.get("session_id")
                    if owner and owner != session_id:
                        continue
                    sequence = record.get("seq")
                    if isinstance(sequence, int):
                        max_sequence = max(max_sequence, sequence)
                    message = record.get("message")
                    if not isinstance(message, dict):
                        continue
                    message_id = message.get("message_id")
                    replaced = False
                    if message_id:
                        for index, existing in enumerate(messages):
                            if existing.get("message_id") == message_id:
                                messages[index] = message
                                replaced = True
                                break
                    if not replaced:
                        messages.append(message)
                    count += 1
        return MessageLedger(messages, max_sequence, count)

    def append_message_event(self, session_id, event):
        path = os.path.join(self._workspace(session_id), MESSAGE_JOURNAL_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(dict(event), ensure_ascii=False) + "\n")
            stream.flush()
        return path

    def save_message_snapshot(self, session_id, messages):
        path = os.path.join(self._workspace(session_id), MESSAGE_SNAPSHOT_FILE)
        temporary = f"{path}.tmp"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(temporary, "w", encoding="utf-8") as stream:
                json.dump(list(messages), stream, ensure_ascii=False, indent=4)
            os.replace(temporary, path)
        except Exception:
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except Exception:
                pass
            raise
        return path

    def clear_message_events(self, session_id):
        path = os.path.join(self._workspace(session_id), MESSAGE_JOURNAL_FILE)
        if os.path.exists(path):
            open(path, "w", encoding="utf-8").close()

    def message_events_have_records(self, session_id):
        try:
            path = os.path.join(
                self._workspace(session_id), MESSAGE_JOURNAL_FILE
            )
            return os.path.getsize(path) > 0
        except OSError:
            return False

    def save_compact_manifest(self, session_id, manifest):
        return self._write_json(
            os.path.join(self._workspace(session_id), "compact_manifest.json"),
            dict(manifest),
            indent=4,
        )

    def save_tools_usage(self, session_id, usage):
        return self._write_json(
            os.path.join(self._workspace(session_id), "tools_usage.json"),
            dict(usage),
            indent=4,
        )

    def load_tools_usage(self, session_id):
        value = self._read_json(
            os.path.join(self._workspace(session_id), "tools_usage.json")
        )
        return value if isinstance(value, dict) else {}

    def append_session_log(self, session_id: str, text: str) -> str:
        path = os.path.join(self._workspace(session_id), f"session_{session_id}.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(text)
        return path

    def read_session_log_tail(self, session_id: str, *, max_bytes: int) -> str:
        if max_bytes <= 0:
            return ""
        path = os.path.join(self._workspace(session_id), f"session_{session_id}.log")
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - max_bytes))
                return handle.read().decode("utf-8", errors="ignore")
        except FileNotFoundError:
            return ""

    def append_llm_request(self, session_id, record):
        directory = os.path.join(self._workspace(session_id), "llm_request")
        os.makedirs(directory, exist_ok=True)
        with self._llm_locks[session_id]:
            maximum = -1
            for filename in os.listdir(directory):
                if filename.endswith(".json"):
                    try:
                        maximum = max(maximum, int(filename.split("_", 1)[0]))
                    except ValueError:
                        pass
            timestamp = float(record["timestamp"])
            step = record.get("request", {}).get("step_name", "unknown")
            date = time.strftime(
                "%Y%m%d%H%M%S", time.localtime(timestamp)
            )
            filename = f"{maximum + 1}_{step}_{date}.json"
            payload = dict(record)
            payload["timestamp"] = timestamp
            return self._write_json(
                os.path.join(directory, filename), payload, indent=4
            )

    def save_request_usage(self, session_id, request_id, usage):
        return self._write_json(
            os.path.join(
                self._workspace(session_id),
                "tokens_usage",
                f"{request_id}.json",
            ),
            dict(usage),
            indent=2,
        )

    def save_mcp_calls(self, session_id, request_id, payload):
        return self._write_json(
            os.path.join(
                self._workspace(session_id),
                "mcp_calls",
                f"{request_id}.json",
            ),
            dict(payload),
            indent=2,
        )

    def purge_llm_requests(self, *, before):
        stats = {
            "scanned_dirs": 0,
            "deleted_files": 0,
            "deleted_empty_dirs": 0,
            "errors": 0,
        }
        for directory in Path(self._root).glob("**/llm_request"):
            if not directory.is_dir():
                continue
            stats["scanned_dirs"] += 1
            try:
                for path in directory.iterdir():
                    if path.is_dir():
                        continue
                    try:
                        if path.stat().st_mtime < before:
                            path.unlink()
                            stats["deleted_files"] += 1
                    except Exception:
                        stats["errors"] += 1
                try:
                    if not any(directory.iterdir()):
                        os.rmdir(directory)
                        stats["deleted_empty_dirs"] += 1
                except OSError:
                    pass
            except Exception:
                stats["errors"] += 1
        return stats

    def purge_sessions(self, *, before, session_id_prefix):
        stats = {"scanned_dirs": 0, "deleted_session_dirs": 0, "errors": 0}
        root = Path(self._root)
        if not root.exists():
            return stats
        for session_dir in root.iterdir():
            if (
                session_dir.is_symlink()
                or not session_dir.is_dir()
                or not session_dir.name.startswith(session_id_prefix)
            ):
                continue
            stats["scanned_dirs"] += 1
            try:
                latest = session_dir.stat().st_mtime
                for child in session_dir.rglob("*"):
                    if child.is_symlink():
                        continue
                    try:
                        latest = max(latest, child.stat().st_mtime)
                    except OSError:
                        continue
                if latest >= before:
                    continue
                shutil.rmtree(session_dir)
                self.remove_session(session_dir.name)
                stats["deleted_session_dirs"] += 1
            except Exception:
                stats["errors"] += 1
        return stats

    def export_session_archive(self, session_id: str) -> str:
        safe_session_id = self._validate_session_id(session_id)
        if not self.session_exists(safe_session_id):
            raise FileNotFoundError(session_id)
        registered_workspace = self.get_session_workspace(safe_session_id)
        if not registered_workspace:
            raise FileNotFoundError(session_id)
        session_dir = Path(registered_workspace).resolve()
        storage_root = Path(self._root).resolve()
        try:
            session_dir.relative_to(storage_root)
        except ValueError as exc:
            raise StorageError("session workspace escapes storage root") from exc
        if not session_dir.is_dir():
            raise FileNotFoundError(session_id)
        tmp_file = tempfile.NamedTemporaryFile(
            prefix=f"sage-session-{safe_session_id}-",
            suffix=".zip",
            delete=False,
        )
        tmp_file.close()
        try:
            with zipfile.ZipFile(
                tmp_file.name, "w", zipfile.ZIP_DEFLATED
            ) as archive:
                for root, dirs, files in os.walk(
                    session_dir, followlinks=False
                ):
                    root_path = Path(root)
                    dirs[:] = [
                        name
                        for name in dirs
                        if not (root_path / name).is_symlink()
                    ]
                    for filename in files:
                        path = root_path / filename
                        if path.is_symlink() or not path.is_file():
                            continue
                        arcname = Path(safe_session_id) / path.relative_to(session_dir)
                        archive.write(path, arcname.as_posix())
            return tmp_file.name
        except Exception:
            try:
                os.unlink(tmp_file.name)
            except OSError:
                pass
            raise
