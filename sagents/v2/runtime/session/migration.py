# pyright: strict
"""Explicit, source-preserving SessionStore migrations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, cast
from collections.abc import Iterable


from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore, StoreInUseError
from sagents.v2.runtime.session.journal import (
    FILESYSTEM_SESSION_STORE_FORMAT,
    FILESYSTEM_SESSION_STORE_FORMAT_V2,
    FILESYSTEM_SESSION_STORE_FORMAT_V3,
    SESSION_AGGREGATE_SNAPSHOT_FORMAT,
    SessionAggregateSnapshotV2,
)

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


@dataclass(frozen=True)
class MigrationReport:
    source: Path
    target_format: str
    sessions: int
    runs: int
    events: int
    dry_run: bool
    backup: Path | None = None


@dataclass(frozen=True)
class OwnerAdoptionReport:
    runtime_root: Path
    adopted_sessions: int
    principal_id: str


def adopt_unowned_sessions(
    runtime_root: str | Path,
    *,
    principal_id: str,
    principal_type: str = "user",
    tenant_id: str | None = None,
) -> OwnerAdoptionReport:
    """Assign an explicit owner to legacy snapshots that never stored one.

    This is intentionally opt-in and only fills missing owners. Existing
    ownership facts are never changed. Desktop uses it during startup to bind
    its pre-ownership, single-user history to the authenticated local user.
    """

    if not principal_id.strip():
        raise ValueError("principal_id must not be empty")
    source = Path(runtime_root).expanduser().resolve()
    if not (source / "sessions").is_dir() or not (source / ".session-store").is_dir():
        return OwnerAdoptionReport(
            runtime_root=source,
            adopted_sessions=0,
            principal_id=principal_id,
        )
    lock = _lock_source(source)
    adopted = 0
    try:
        for snapshot in sorted((source / "sessions").rglob("state.json")):
            payload = _read_json(snapshot)
            if payload.get("format") not in {
                FILESYSTEM_SESSION_STORE_FORMAT_V3,
                FILESYSTEM_SESSION_STORE_FORMAT,
                FILESYSTEM_SESSION_STORE_FORMAT_V2,
            }:
                continue
            state = payload.get("state")
            if not isinstance(state, dict):
                continue
            state = cast(dict[str, Any], state)
            sessions = state.get("sessions")
            if not isinstance(sessions, list):
                continue
            if len(cast(list[Any], sessions)) != 1:
                continue
            sessions = cast(list[Any], sessions)
            session = sessions[0]
            if not isinstance(session, dict):
                continue
            session = cast(dict[str, Any], session)
            if session.get("owner") is not None:
                continue

            # Owner adoption is a one-time compatibility migration. An already
            # owned aggregate is outside its scope, so leave integrity handling
            # to the SessionStore's per-Session isolation instead of preventing
            # every healthy Session (and the Desktop itself) from opening.
            # Snapshots that still require mutation must remain fully trusted.
            _verify_checksum(payload, snapshot)

            owner: dict[str, Any] = {
                "principal_id": principal_id,
                "principal_type": principal_type,
                "tenant_id": tenant_id,
                "delegated_by": None,
                "scopes": [],
            }
            session["owner"] = owner
            for entry in cast(list[Any], state.get("start_idempotency", ())):
                if not isinstance(entry, dict):
                    continue
                entry = cast(dict[str, Any], entry)
                if entry.get("principal_type") is None:
                    entry["tenant_id"] = tenant_id
                    entry["principal_id"] = principal_id
                    entry["principal_type"] = principal_type

            unsigned = {
                key: value for key, value in payload.items() if key != "checksum"
            }
            payload["checksum"] = FilesystemSessionStore._checksum(unsigned)
            _atomic_json_replace(snapshot, payload)
            _adopt_projected_session_owner(snapshot.parent / "session.json", owner)
            adopted += 1
    finally:
        _unlock_source(lock)
    return OwnerAdoptionReport(
        runtime_root=source,
        adopted_sessions=adopted,
        principal_id=principal_id,
    )


def migrate_runtime_root(runtime_root: str | Path, *, dry_run: bool = False) -> MigrationReport:
    """Validate v3, build and reopen v4, then atomically retain v3 as backup."""

    source = Path(runtime_root).expanduser().resolve()
    metadata = _read_json(source / ".session-store" / "store.json")
    source_format = metadata.get("format")
    if source_format == FILESYSTEM_SESSION_STORE_FORMAT:
        raise ValueError(f"SessionStore is already {FILESYSTEM_SESSION_STORE_FORMAT}")
    if source_format != FILESYSTEM_SESSION_STORE_FORMAT_V3:
        raise ValueError(f"expected a v3 SessionStore, got {source_format!r}")
    _validate_no_pending_transactions(source)
    lock = _lock_source(source)
    temporary = source.with_name(f".{source.name}.sage-v4-migration")
    if temporary.exists():
        shutil.rmtree(temporary)
    aggregates: list[tuple[Path, dict[str, Any]]] = []
    try:
        for snapshot in sorted((source / "sessions").rglob("state.json")):
            state = _read_v3_aggregate(snapshot)
            state["session_format_version"] = SESSION_AGGREGATE_SNAPSHOT_FORMAT
            FilesystemSessionStore._restore_legacy_principal_types(state)
            # Compare the semantic v4 aggregate, not incidental omissions in
            # old JSON. Typed normalization may add default empty collections
            # or optional null fields while preserving every durable fact.
            normalized = SessionAggregateSnapshotV2.model_validate(state).model_dump(
                mode="json"
            )
            aggregates.append((snapshot.parent, normalized))
        aggregates.sort(
            key=lambda value: (
                _lineage_depth(value[1], aggregates),
                _session_id(value[1]),
            )
        )
        source_summary = _summary(state for _, state in aggregates)

        target = FilesystemSessionStore(temporary)
        try:
            for source_dir, state in aggregates:
                session_id = _session_id(state)
                target_dir = target._session_dir_for_state(session_id, state)
                target_dir.mkdir(parents=True, exist_ok=True)
                derived = source_dir / "derived"
                if derived.is_dir():
                    shutil.copytree(
                        derived,
                        target_dir / "derived",
                        symlinks=True,
                        dirs_exist_ok=True,
                    )
                else:
                    (target_dir / "derived").mkdir(exist_ok=True)
                target._write_snapshot(target_dir / "state.json", state)
                target._atomic_bytes_write(target_dir / "journal.jsonl", b"")
                for entry in cast(list[Any], state.get("start_idempotency", ())):
                    target._write_start_idempotency(entry, session_id)
                target._refresh_session_views(session_id, state)
        finally:
            target._closed = True
            target._release_writer_lock()

        verified = FilesystemSessionStore(temporary)
        try:
            reopened = [
                verified._read_session_aggregate(snapshot)[0]
                for snapshot in sorted((temporary / "sessions").rglob("state.json"))
            ]
            target_summary = _summary(reopened)
        finally:
            verified._closed = True
            verified._release_writer_lock()
        if target_summary != source_summary:
            raise ValueError("v4 verification does not match the v3 source")
        _copy_runtime_ancillary_files(source, temporary)
        if _ancillary_manifest(source) != _ancillary_manifest(temporary):
            raise ValueError("v4 ancillary-file verification does not match the source")

        report = MigrationReport(
            source=source,
            target_format=FILESYSTEM_SESSION_STORE_FORMAT,
            sessions=source_summary["sessions"],
            runs=source_summary["runs"],
            events=source_summary["events"],
            dry_run=dry_run,
        )
        if dry_run:
            shutil.rmtree(temporary)
            return report

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = source.with_name(f"{source.name}.v3-backup-{timestamp}")
        if backup.exists():
            raise FileExistsError(f"migration backup already exists: {backup}")
        source.replace(backup)
        try:
            _make_read_only(backup)
            temporary.replace(source)
        except BaseException:
            _make_writable(backup)
            backup.replace(source)
            raise
        _fsync_directory(source.parent)
        return replace(report, backup=backup)
    finally:
        _unlock_source(lock)
        if temporary.exists():
            shutil.rmtree(temporary)


def _read_v3_aggregate(snapshot: Path) -> dict[str, Any]:
    payload = _read_json(snapshot)
    if payload.get("format") != FILESYSTEM_SESSION_STORE_FORMAT_V3:
        raise ValueError(f"snapshot is not v3: {snapshot}")
    _verify_checksum(payload, snapshot)
    state = json.loads(json.dumps(payload["state"]))
    revision = int(payload["current_session_revision"])
    journal = snapshot.parent / "journal.jsonl"
    if journal.exists():
        encoded = journal.read_bytes()
        if encoded and not encoded.endswith(b"\n"):
            raise ValueError(f"incomplete v3 journal tail: {journal}")
        for index, line in enumerate(encoded.splitlines(), start=1):
            if not line.strip():
                continue
            mutation = json.loads(line)
            if mutation.get("format") != "sage.filesystem-session-journal/v3":
                raise ValueError(f"invalid v3 journal format at {journal}:{index}")
            _verify_checksum(mutation, journal)
            if int(mutation["previous_session_revision"]) != revision:
                raise ValueError(f"revision gap at {journal}:{index}")
            FilesystemSessionStore._apply_state_delta(state, mutation["delta"])
            revision = int(mutation["current_session_revision"])
            if int(state["sessions"][0]["revision"]) != revision:
                raise ValueError(f"revision mismatch at {journal}:{index}")
    if state.get("session_format_version") != "sage.session-aggregate/v1":
        raise ValueError(f"unsupported v3 aggregate schema in {snapshot}")
    for events in state.get("run_events", {}).values():
        for event in events:
            RuntimeEvent.model_validate(event)
    return state


def _summary(states: Iterable[dict[str, Any]]) -> dict[str, Any]:
    sessions = runs = events = 0
    digest = hashlib.sha256()
    for state in sorted(states, key=_session_id):
        sessions += len(state.get("sessions", ()))
        runs += len(state.get("runs", ()))
        events += sum(len(values) for values in state.get("run_events", {}).values())
        selected = {
            "sessions": state.get("sessions", ()),
            "runs": state.get("runs", ()),
            "run_events": state.get("run_events", {}),
            "checkpoints": state.get("checkpoints", ()),
            "start_idempotency": state.get("start_idempotency", ()),
        }
        digest.update(FilesystemSessionStore._canonical_json(selected))
    return {"sessions": sessions, "runs": runs, "events": events, "hash": digest.hexdigest()}


def _lineage_depth(state: dict[str, Any], aggregates: list[tuple[Path, dict[str, Any]]]) -> int:
    parents = {_session_id(value): value for _, value in aggregates}
    depth = 0
    current = state["sessions"][0].get("parent_session_id")
    seen: set[str] = set()
    while current in parents:
        if current in seen:
            raise ValueError("Session parent lineage contains a cycle")
        seen.add(current)
        depth += 1
        current = parents[current]["sessions"][0].get("parent_session_id")
    return depth


def _session_id(state: dict[str, Any]) -> str:
    rows = state.get("sessions", ())
    if len(rows) != 1:
        raise ValueError("Session aggregate must contain exactly one Session")
    return str(rows[0]["session_id"])


def _verify_checksum(payload: dict[str, Any], source: Path) -> None:
    unsigned = {key: value for key, value in payload.items() if key != "checksum"}
    if (
        payload.get("checksum") != FilesystemSessionStore._checksum(unsigned)
        and not FilesystemSessionStore._matches_legacy_unordered_checksum(payload)
    ):
        raise ValueError(f"checksum mismatch: {source}")


def _copy_runtime_ancillary_files(source: Path, target: Path) -> None:
    """Preserve Desktop/application data colocated with the SessionStore."""

    excluded = {".session-store", "sessions", "desktop-v2-sidecar.json"}
    for entry in source.iterdir():
        if entry.name in excluded:
            continue
        destination = target / entry.name
        if entry.is_dir() and not entry.is_symlink():
            shutil.copytree(entry, destination, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, destination, follow_symlinks=False)


def _ancillary_manifest(root: Path) -> tuple[tuple[str, str, str], ...]:
    excluded = {".session-store", "sessions", "desktop-v2-sidecar.json"}
    values: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in excluded:
            continue
        if path.is_symlink():
            values.append((str(relative), "symlink", os.readlink(path)))
        elif path.is_dir():
            values.append((str(relative), "directory", ""))
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            values.append((str(relative), "file", digest.hexdigest()))
    return tuple(values)


def _validate_no_pending_transactions(source: Path) -> None:
    for path in (
        source / ".session-store" / "transactions",
        source / ".session-store" / "trash",
    ):
        if path.is_dir() and any(path.iterdir()):
            raise ValueError(f"pending recovery data must be resolved before migration: {path}")


def _lock_source(source: Path) -> BinaryIO:
    if fcntl is None:
        raise RuntimeError("SessionStore migration requires advisory file locks")
    path = source / ".session-store" / ".writer.lock"
    handle = path.open("a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise StoreInUseError(
            RuntimeErrorInfo(
                code="session_store.in_use",
                category=ErrorCategory.CONFLICT,
                message=f"SessionStore is in use: {source}",
                safe_to_resume=True,
            )
        ) from exc
    return handle


def _unlock_source(handle: BinaryIO | None) -> None:
    if handle is None or handle.closed:
        return
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        if path.is_symlink():
            continue
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _make_writable(root: Path) -> None:
    root.chmod(0o755)
    for path in sorted(root.rglob("*"), key=lambda value: len(value.parts)):
        if path.is_symlink():
            continue
        path.chmod(0o755 if path.is_dir() else 0o644)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read migration input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"migration input must be a JSON object: {path}")
    return cast(dict[str, Any], value)


def _adopt_projected_session_owner(path: Path, owner: dict[str, Any]) -> None:
    if not path.is_file():
        return
    payload = _read_json(path)
    session = payload.get("session")
    if not isinstance(session, dict):
        return
    session = cast(dict[str, Any], session)
    if session.get("owner") is not None:
        return
    session["owner"] = dict(owner)
    _atomic_json_replace(path, payload)


def _atomic_json_replace(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.owner-{os.getpid()}.tmp")
    try:
        encoded = FilesystemSessionStore._canonical_json(payload)
        with temporary.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    # Windows CRT cannot open directories; file data is fsynced before replace.
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
