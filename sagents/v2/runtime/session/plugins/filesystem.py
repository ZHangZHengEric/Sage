"""Compact authoritative per-Session filesystem storage for SAgents v2.

There is deliberately no global Session catalog in this implementation. A
known ``session_id`` opens its directory directly and startup never materializes
all Sessions. Run-only compatibility calls locate and load only their matching
Session. Product-level indexes belong to the embedding application.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from sagents.v2.runtime.session.aggregate import SessionAggregate
from sagents.v2.runtime.session.journal import (
    FILESYSTEM_SESSION_STORE_FORMAT,
    FILESYSTEM_SESSION_STORE_FORMAT_V3,
    SessionMutationEnvelope,
    SessionAggregateSnapshotV2,
    SessionStateDeltaMutation,
    SessionSnapshotEnvelope,
)

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows hosts need a dedicated lock adapter.
    fcntl = None  # type: ignore[assignment]


LOGGER = logging.getLogger(__name__)
SESSION_LAYOUT_FORMAT = "sage.filesystem-session-layout/v1"
JOURNAL_COMPACT_COMMITS = 256
JOURNAL_COMPACT_BYTES = 8 * 1024 * 1024


class StoreInUseError(SageV2Error):
    """Raised when another writer already owns the same Store root."""


class SessionStoreCorruptionError(SageV2Error):
    """Raised when authoritative Session state integrity cannot be established."""


class _FilesystemSessionState(SessionStoreCoordinator):
    """Single-host persistence adapter around the state coordinator.

    Runtime semantics live in :class:`SessionStoreCoordinator`; this subclass
    implements only the durability hooks. This is the central invariant that
    prevents the file and in-memory implementations from acquiring different
    CAS, idempotency, checkpoint, or interaction behavior.  A checksummed
    ``state.json`` is a compact base. Revision-contiguous, checksummed deltas are
    appended to ``journal.jsonl`` and periodically compacted, keeping streaming
    writes proportional to the newly committed data.
    """

    format_version = FILESYSTEM_SESSION_STORE_FORMAT

    def __init__(
        self,
        root: str | Path,
        **kwargs: Any,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.sessions_root = self.root / "sessions"
        self.control_root = self.root / ".session-store"
        self.idempotency_root = self.control_root / "idempotency" / "start"
        self.locations_root = self.control_root / "locations"
        self.transactions_root = self.control_root / "transactions"
        self.trash_root = self.control_root / "trash"
        self._filesystem_lock = threading.RLock()
        self._loaded_session_ids: set[str] = set()
        self._persisted_states: dict[str, dict[str, Any]] = {}
        # A failed write may have reached any point between journal append and
        # the auxiliary indexes.  The next successful write must therefore
        # replace the compact snapshot instead of deriving a delta from an
        # uncertain baseline.
        self._storage_recovery_required: set[str] = set()
        self._journal_commits: dict[str, int] = {}
        self._storage_locks: dict[str, asyncio.Lock] = {}
        self._load_lock = asyncio.Lock()
        self._closed = False
        self._prepare_root()
        self._writer_handle = (self.control_root / ".writer.lock").open("a+b")
        self._acquire_writer_lock()
        try:
            self._recover_transactions()
            self._normalize_existing_session_locations()
            super().__init__(**kwargs)
        except Exception:
            self._release_writer_lock()
            raise

    @property
    def capabilities(self) -> dict[str, bool | str]:
        return {
            **super().capabilities,
            "durable_across_process_restart": True,
            "storage_format_version": self.format_version,
            "multi_process_writes": False,
            "global_session_index": False,
            "derived_state_authoritative": False,
        }

    async def _commit_storage_locked(self, session_id: str) -> None:
        state = self._dump_session_state_locked(session_id)
        state = SessionAggregate(
            SessionAggregateSnapshotV2.model_validate(state)
        ).snapshot.model_dump(mode="json")
        # These entries are also materialized as a lookup that can be rebuilt
        # from state.json after a crash; removing the lookup never loses data.
        start_entries = list(state.get("start_idempotency", ()))
        storage_lock = self._storage_locks.setdefault(session_id, asyncio.Lock())
        # The coordinator now owns a per-Session operation lock. Different
        # aggregates may persist concurrently while the same aggregate remains
        # serialized through this storage queue.
        async with storage_lock:
            previous = (
                None
                if session_id in self._storage_recovery_required
                else self._persisted_states.get(session_id)
            )
            try:
                await asyncio.to_thread(
                    self._write_session_state,
                    session_id,
                    state,
                    start_entries,
                    previous,
                )
            except BaseException:
                self._storage_recovery_required.add(session_id)
                if await asyncio.to_thread(
                    self._recover_and_matches_state, session_id, state
                ):
                    # The canonical snapshot/journal was committed and only a
                    # recoverable auxiliary write failed. Treat the operation
                    # as durable after rebuilding those indexes.
                    self._persisted_states[session_id] = deepcopy(state)
                    self._storage_recovery_required.discard(session_id)
                else:
                    # The coordinator operation guard restores only this
                    # Session snapshot; unrelated durable commits stay loaded.
                    raise
            else:
                # This cache describes durable state, not merely the most
                # recently frozen in-memory aggregate. Advancing it before the
                # write succeeds can make the next journal envelope skip a
                # revision after a transient I/O failure.
                self._persisted_states[session_id] = deepcopy(state)
                self._storage_recovery_required.discard(session_id)
        self._loaded_session_ids.add(session_id)

    def _recover_and_matches_state(
        self, session_id: str, expected: dict[str, Any]
    ) -> bool:
        """Return whether recovery proves the requested aggregate is durable."""

        try:
            self._recover_transactions()
            snapshot = self._session_dir(session_id) / "state.json"
            if not snapshot.is_file():
                return False
            actual, _journal_count = self._read_session_aggregate(snapshot)
        except BaseException:
            return False
        return actual == expected

    def _restore_durable_state_locked(self) -> None:
        """Replace tentative in-memory aggregates with confirmed disk state."""

        combined = self._dump_state_locked()
        for key in (
            "sessions",
            "runs",
            "start_idempotency",
            "command_results",
            "execution_resources",
            "execution_resource_command_results",
            "checkpoints",
            "suspensions",
            "interactions",
            "interaction_resolutions",
            "session_commit_proposals",
            "session_commit_command_results",
        ):
            combined[key] = []
        for key in ("run_events", "fork_base_events", "steer_inbox"):
            combined[key] = {}
        for state in self._persisted_states.values():
            self._merge_state(combined, state)

        subscribers = self._subscribers
        derived = self._derived_state
        self._load_state_locked(combined)
        self._subscribers.update(subscribers)
        self._derived_state.update(derived)
        self._loaded_session_ids.intersection_update(self._sessions)

    async def _delete_storage_locked(
        self, session_id: str, deleted_session_ids: frozenset[str]
    ) -> None:
        locks = [
            self._storage_locks.setdefault(value, asyncio.Lock())
            for value in sorted(deleted_session_ids)
        ]
        try:
            for lock in locks:
                await lock.acquire()
            await asyncio.to_thread(
                self._delete_session_files,
                session_id,
                deleted_session_ids,
            )
        finally:
            for lock in reversed(locks):
                if lock.locked():
                    lock.release()
        for value in deleted_session_ids:
            self._storage_locks.pop(value, None)
            self._persisted_states.pop(value, None)
            self._storage_recovery_required.discard(value)
            self._journal_commits.pop(value, None)

    async def get_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> Any | None:
        await self._ensure_session_loaded(session_id)
        await self.get_session(session_id)
        path = self._derived_path(session_id, namespace, key)
        if not path.exists():
            return None
        try:
            payload = json.loads(await asyncio.to_thread(path.read_text, "utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise self._corrupt(
                "session_store.derived_state_corrupt",
                f"derived state {namespace!r}/{key!r} cannot be read: {exc}",
            ) from exc
        if payload.get("namespace") != namespace or payload.get("key") != key:
            raise self._corrupt(
                "session_store.derived_state_mismatch",
                "derived-state identity does not match its path",
            )
        return payload.get("value")

    async def put_derived_state(
        self, session_id: str, namespace: str, key: str, value: Any
    ) -> None:
        await self._ensure_session_loaded(session_id)
        await super().put_derived_state(session_id, namespace, key, value)
        payload = {"namespace": namespace, "key": key, "value": value}
        await asyncio.to_thread(
            self._atomic_json_write,
            self._derived_path(session_id, namespace, key),
            payload,
        )

    async def delete_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> None:
        await self._ensure_session_loaded(session_id)
        await super().delete_derived_state(session_id, namespace, key)
        path = self._derived_path(session_id, namespace, key)
        await asyncio.to_thread(path.unlink, missing_ok=True)

    async def close(self) -> None:
        """Release the process writer lock. Calling close twice is safe."""

        if self._closed:
            return
        self._closed = True
        await asyncio.to_thread(self._release_writer_lock)

    async def create_run(self, command, context):
        """Load only the explicitly addressed parent/Session before mutation."""

        if command.session_id is not None:
            await self._ensure_session_loaded(command.session_id, missing_ok=True)
        else:
            lookup = self._read_start_lookup(command, context)
            if lookup is not None:
                await self._ensure_session_loaded(lookup["session_id"])
        return await super().create_run(command, context)

    async def get_session(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().get_session(session_id)

    async def delete_session(self, session_id):
        await self._ensure_session_loaded(session_id)
        await self._ensure_descendants_loaded(session_id)
        result = await super().delete_session(session_id)
        self._loaded_session_ids.intersection_update(self._sessions)
        return result

    async def list_session_runs(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().list_session_runs(session_id)

    async def list_dispatchable_runs(self):
        """Load only snapshots advertising an active root execution intent."""

        active = {"queued", "running", "suspend_requested", "resuming"}
        for snapshot in self.sessions_root.rglob("state.json"):
            state = self._peek_snapshot_state(snapshot)
            should_load = False
            for run in state.get("runs", ()):
                command = run.get("start_command") or {}
                if (
                    run.get("state") in active
                    and command.get("parent_run_id") is None
                    and run.get("request_context") is not None
                ):
                    should_load = True
                    break
            if should_load:
                rows = state.get("sessions", ())
                if len(rows) == 1 and rows[0].get("session_id"):
                    await self._ensure_session_loaded(str(rows[0]["session_id"]))
        return await super().list_dispatchable_runs()

    async def list_descendant_sessions(self, session_id):
        await self._ensure_session_loaded(session_id)
        await self._ensure_descendants_loaded(session_id)
        return await super().list_descendant_sessions(session_id)

    async def read_session_events(self, session_id, **kwargs):
        await self._ensure_session_loaded(session_id)
        return await super().read_session_events(session_id, **kwargs)

    async def list_session_commit_proposals(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().list_session_commit_proposals(session_id)

    async def get_run(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_run(run_id)

    async def get_run_result(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_run_result(run_id)

    async def get_start_command(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_start_command(run_id)

    async def get_latest_checkpoint(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().get_latest_checkpoint(run_id)

    async def read_events(self, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().read_events(run_id, **kwargs)

    async def read_fork_base_events(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().read_fork_base_events(run_id)

    async def commit_run(self, *, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().commit_run(run_id=run_id, **kwargs)

    async def propose_session_commit(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().propose_session_commit(command, context)

    async def publish_session_commit(self, command, context):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", command.proposal_id
        )
        return await super().publish_session_commit(command, context)

    async def reject_session_commit(self, command, context):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", command.proposal_id
        )
        return await super().reject_session_commit(command, context)

    async def get_session_commit_proposal(self, proposal_id):
        await self._ensure_resource_loaded(
            "session_commit_proposals", "proposal_id", proposal_id
        )
        return await super().get_session_commit_proposal(proposal_id)

    async def get_checkpoint(self, checkpoint_id):
        await self._ensure_resource_loaded(
            "checkpoints", "checkpoint_id", checkpoint_id
        )
        return await super().get_checkpoint(checkpoint_id)

    async def get_suspension(self, suspension_id):
        await self._ensure_resource_loaded(
            "suspensions", "suspension_id", suspension_id
        )
        return await super().get_suspension(suspension_id)

    async def get_interaction(self, interaction_id):
        await self._ensure_resource_loaded(
            "interactions", "interaction_id", interaction_id
        )
        return await super().get_interaction(interaction_id)

    async def get_interaction_resolution(self, interaction_id):
        await self._ensure_resource_loaded(
            "interactions", "interaction_id", interaction_id
        )
        return await super().get_interaction_resolution(interaction_id)

    async def enqueue_steer(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().enqueue_steer(command, context)

    async def claim_steers(self, *, run_id, **kwargs):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().claim_steers(run_id=run_id, **kwargs)

    async def list_steers(self, run_id):
        await self._ensure_resource_loaded("runs", "run_id", run_id)
        return await super().list_steers(run_id)

    async def resolve_interaction(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().resolve_interaction(command, context)

    async def request_resume(self, command, context):
        await self._ensure_resource_loaded("runs", "run_id", command.run_id)
        return await super().request_resume(command, context)

    async def subscribe_events(self, cursor):
        await self._ensure_resource_loaded("runs", "run_id", cursor.run_id)
        async for event in super().subscribe_events(cursor):
            yield event

    def _prepare_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for path in (
            self.sessions_root,
            self.control_root,
            self.idempotency_root,
            self.locations_root,
            self.transactions_root,
            self.trash_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        metadata_path = self.control_root / "store.json"
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise self._corrupt(
                    "session_store.metadata_corrupt",
                    f"store metadata cannot be read: {exc}",
                ) from exc
            stored_format = metadata.get("format")
            if stored_format != self.format_version:
                if stored_format == FILESYSTEM_SESSION_STORE_FORMAT_V3:
                    raise self._error(
                        "session_store.migration_required",
                        ErrorCategory.UNSUPPORTED_SCHEMA,
                        "SessionStore v3 requires explicit migration: "
                        f"sage v2 migrate --runtime-root {self.root}",
                    )
                raise self._error(
                    "session_store.unsupported_format",
                    ErrorCategory.UNSUPPORTED_SCHEMA,
                    f"unsupported SessionStore format {stored_format!r}",
                )
            return
        self._atomic_json_write(
            metadata_path,
            {"format": self.format_version, "store_id": new_id("store")},
        )

    def _normalize_existing_session_locations(self) -> None:
        """Re-home early-v2 sibling children into the nested Session tree.

        The operation only examines snapshots already using the current v2
        schema. It never reads or imports Desktop v1 storage. Location files
        are disposable plugin metadata and are rebuilt from the physical tree.
        """

        records: dict[str, tuple[str | None, Path]] = {}
        for snapshot in sorted(self.sessions_root.rglob("state.json")):
            state = self._peek_snapshot_state(snapshot)
            rows = state.get("sessions", ())
            if len(rows) != 1 or not rows[0].get("session_id"):
                continue
            session_id = str(rows[0]["session_id"])
            if session_id in records:
                raise self._corrupt(
                    "session_store.duplicate_session",
                    f"Session {session_id!r} has more than one snapshot",
                )
            parent_id = rows[0].get("parent_session_id")
            records[session_id] = (
                str(parent_id) if parent_id is not None else None,
                snapshot.parent,
            )

        for location in self.locations_root.glob("*.json"):
            location.unlink(missing_ok=True)

        desired: dict[str, Path] = {}
        resolving: set[str] = set()

        def desired_path(session_id: str) -> Path:
            cached = desired.get(session_id)
            if cached is not None:
                return cached
            if session_id in resolving:
                raise self._corrupt(
                    "session_store.parent_cycle",
                    f"Session lineage contains a cycle at {session_id!r}",
                )
            resolving.add(session_id)
            parent_id, _current = records[session_id]
            if parent_id in records:
                target = (
                    desired_path(parent_id)
                    / "sub_sessions"
                    / self._safe_segment(session_id)
                )
            else:
                target = self.sessions_root / self._safe_segment(session_id)
            resolving.remove(session_id)
            desired[session_id] = target.resolve()
            return desired[session_id]

        for session_id in records:
            desired_path(session_id)

        def current_path(session_id: str) -> Path:
            target = desired[session_id]
            if self._snapshot_belongs_to(target / "state.json", session_id):
                return target
            original = records[session_id][1]
            if self._snapshot_belongs_to(original / "state.json", session_id):
                return original
            for candidate in self.sessions_root.rglob("state.json"):
                if self._snapshot_belongs_to(candidate, session_id):
                    return candidate.parent
            raise self._corrupt(
                "session_store.session_missing",
                f"Session {session_id!r} disappeared while normalizing its layout",
            )

        for session_id in sorted(desired, key=lambda key: len(desired[key].parts)):
            source = current_path(session_id)
            target = desired[session_id]
            if source != target:
                if target.exists():
                    raise self._corrupt(
                        "session_store.path_conflict",
                        f"cannot move Session {session_id!r} into occupied path {target}",
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                source.replace(target)
                self._fsync_directory(source.parent)
                self._fsync_directory(target.parent)
            self._write_location(session_id, target)

    def _snapshot_belongs_to(self, snapshot: Path, session_id: str) -> bool:
        if not snapshot.is_file():
            return False
        rows = self._peek_snapshot_state(snapshot).get("sessions", ())
        return len(rows) == 1 and rows[0].get("session_id") == session_id

    def _acquire_writer_lock(self) -> None:
        if fcntl is None:
            raise self._error(
                "session_store.lock_unsupported",
                ErrorCategory.UNSUPPORTED_SCHEMA,
                "the filesystem SessionStore requires an advisory-lock adapter",
            )
        try:
            fcntl.flock(self._writer_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._writer_handle.close()
            raise StoreInUseError(
                RuntimeErrorInfo(
                    code="session_store.in_use",
                    category=ErrorCategory.CONFLICT,
                    message=f"SessionStore root is already owned: {self.root}",
                    safe_to_resume=True,
                )
            ) from exc

    def _release_writer_lock(self) -> None:
        handle = getattr(self, "_writer_handle", None)
        if handle is None or handle.closed:
            return
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

    def _write_snapshot(self, path: Path, state: dict[str, Any]) -> None:
        current_revision = int(state["sessions"][0]["revision"])
        typed_state = SessionAggregateSnapshotV2.model_validate(state)
        unsigned = {
            "format": self.format_version,
            "write_id": new_id("session_write"),
            "current_session_revision": current_revision,
            "state": typed_state.model_dump(mode="json"),
        }
        envelope = SessionSnapshotEnvelope(
            **unsigned,
            checksum=self._checksum(unsigned),
        )
        self._atomic_json_write(path, envelope.model_dump(mode="json"))

    def _refresh_session_views(self, session_id: str, state: dict[str, Any]) -> None:
        """Best-effort human-readable projection of the SessionStore contract.

        ``state.json`` remains the only recovery input.  These files mirror the
        standard Session/Run/Event/Checkpoint interfaces and can therefore be
        regenerated after an interrupted projection write without changing
        runtime semantics.
        """

        try:
            self._materialize_session_views(session_id, state)
        except Exception:
            LOGGER.exception("failed to refresh Session file views for %s", session_id)

    def _materialize_session_views(
        self, session_id: str, state: dict[str, Any]
    ) -> None:
        session_rows = state.get("sessions", ())
        if len(session_rows) != 1 or session_rows[0].get("session_id") != session_id:
            raise ValueError("Session view state must contain exactly its owner")
        session = dict(session_rows[0])
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        runs_dir = session_dir / "runs"
        commits_dir = session_dir / "commits"
        sub_sessions_dir = session_dir / "sub_sessions"
        for path in (
            runs_dir,
            commits_dir,
            sub_sessions_dir,
            session_dir / "derived",
        ):
            path.mkdir(parents=True, exist_ok=True)

        runs = [dict(value) for value in state.get("runs", ())]
        self._atomic_json_write(
            session_dir / "session.json",
            {
                "format": SESSION_LAYOUT_FORMAT,
                "authoritative_state": "state.json",
                "session": session,
                "run_ids": [value["run_id"] for value in runs],
            },
        )
        session_events = sorted(
            (
                event
                for events in state.get("run_events", {}).values()
                for event in events
                if event.get("session_sequence") is not None
            ),
            key=lambda event: int(event["session_sequence"]),
        )
        self._atomic_jsonl_write(session_dir / "events.jsonl", session_events)

        checkpoints = self._group_by_run(state.get("checkpoints", ()))
        suspensions = self._group_by_run(state.get("suspensions", ()))
        interactions = self._group_by_run(state.get("interactions", ()))
        resolutions = {
            value["interaction_id"]: value
            for value in state.get("interaction_resolutions", ())
        }
        for run in runs:
            run_id = str(run["run_id"])
            run_dir = runs_dir / self._safe_segment(run_id)
            run_dir.mkdir(parents=True, exist_ok=True)
            command = run.pop("start_command", None)
            self._atomic_json_write(
                run_dir / "run.json",
                {"format": SESSION_LAYOUT_FORMAT, "run": run},
            )
            self._write_optional_json(
                run_dir / "command.json",
                {"format": SESSION_LAYOUT_FORMAT, "command": command}
                if command is not None
                else None,
            )
            self._atomic_jsonl_write(
                run_dir / "events.jsonl",
                state.get("run_events", {}).get(run_id, ()),
            )
            self._write_optional_jsonl(
                run_dir / "fork-base-events.jsonl",
                state.get("fork_base_events", {}).get(run_id, ()),
            )
            self._write_entity_directory(
                run_dir / "checkpoints",
                checkpoints.get(run_id, ()),
                "checkpoint_id",
            )
            self._write_entity_directory(
                run_dir / "suspensions",
                suspensions.get(run_id, ()),
                "suspension_id",
            )
            interaction_dir = run_dir / "interactions"
            interaction_dir.mkdir(parents=True, exist_ok=True)
            for interaction in interactions.get(run_id, ()):
                interaction_id = str(interaction["interaction_id"])
                self._atomic_json_write(
                    interaction_dir / f"{self._safe_segment(interaction_id)}.json",
                    {
                        "format": SESSION_LAYOUT_FORMAT,
                        "request": interaction,
                        "resolution": resolutions.get(interaction_id),
                    },
                )
            self._write_optional_json(
                run_dir / "steers.json",
                {
                    "format": SESSION_LAYOUT_FORMAT,
                    "entries": state.get("steer_inbox", {}).get(run_id, ()),
                }
                if state.get("steer_inbox", {}).get(run_id)
                else None,
            )

        for proposal in state.get("session_commit_proposals", ()):
            proposal_id = str(proposal["proposal_id"])
            self._atomic_json_write(
                commits_dir / f"{self._safe_segment(proposal_id)}.json",
                {"format": SESSION_LAYOUT_FORMAT, "proposal": proposal},
            )

    @staticmethod
    def _group_by_run(values) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for value in values:
            grouped.setdefault(str(value["run_id"]), []).append(value)
        return grouped

    def _write_entity_directory(
        self,
        root: Path,
        values,
        identity_key: str,
    ) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for value in values:
            identity = str(value[identity_key])
            self._atomic_json_write(
                root / f"{self._safe_segment(identity)}.json",
                {"format": SESSION_LAYOUT_FORMAT, "value": value},
            )

    def _write_optional_json(self, path: Path, payload: dict[str, Any] | None) -> None:
        if payload is None:
            path.unlink(missing_ok=True)
            return
        self._atomic_json_write(path, payload)

    def _write_optional_jsonl(self, path: Path, rows) -> None:
        rows = tuple(rows)
        if not rows:
            path.unlink(missing_ok=True)
            return
        self._atomic_jsonl_write(path, rows)

    @classmethod
    def _atomic_jsonl_write(cls, path: Path, rows) -> None:
        encoded = b"".join(cls._canonical_json(dict(row)) + b"\n" for row in rows)
        cls._atomic_bytes_write(path, encoded)

    def _write_session_state(
        self,
        session_id: str,
        state: dict[str, Any],
        start_entries: list[dict[str, Any]],
        previous: dict[str, Any] | None,
    ) -> None:
        with self._filesystem_lock:
            session_dir = self._session_dir_for_state(session_id, state)
            snapshot = session_dir / "state.json"
            is_new = not snapshot.exists()
            transaction = None
            if is_new:
                transaction = self._write_transaction("create", session_id)
                session_dir.mkdir(parents=True, exist_ok=True)
                (session_dir / "derived").mkdir(exist_ok=True)

            journal = session_dir / "journal.jsonl"
            compacted = is_new or previous is None
            if compacted:
                self._write_snapshot(snapshot, state)
                self._atomic_bytes_write(journal, b"")
                self._journal_commits[session_id] = 0
            else:
                delta = self._state_delta(previous, state)
                mutation = SessionStateDeltaMutation(kind="state_delta", **delta)
                previous_revision = int(previous["sessions"][0]["revision"])
                current_revision = int(state["sessions"][0]["revision"])
                unsigned = {
                    "format": "sage.filesystem-session-journal/v4",
                    "mutation_id": new_id("session_mutation"),
                    "previous_session_revision": previous_revision,
                    "current_session_revision": current_revision,
                    "mutation": mutation.model_dump(mode="json"),
                }
                envelope = SessionMutationEnvelope(
                    **unsigned,
                    checksum=self._checksum(unsigned),
                )
                self._append_journal_line(journal, envelope.model_dump(mode="json"))
                count = self._journal_commits.get(session_id, 0) + 1
                self._journal_commits[session_id] = count
                if (
                    count >= JOURNAL_COMPACT_COMMITS
                    or journal.stat().st_size >= JOURNAL_COMPACT_BYTES
                ):
                    # Snapshot replacement precedes journal trimming. Recovery
                    # skips already-included envelopes if a crash lands between.
                    self._write_snapshot(snapshot, state)
                    self._atomic_bytes_write(journal, b"")
                    self._journal_commits[session_id] = 0
                    compacted = True

            if compacted:
                self._refresh_session_views(session_id, state)

            for entry in start_entries:
                self._write_start_idempotency(entry, session_id)
            if transaction is not None:
                transaction.unlink(missing_ok=True)
                self._fsync_directory(self.transactions_root)

    @classmethod
    def _append_journal_line(cls, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = cls._canonical_json(payload) + b"\n"
        with path.open("ab") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

    @classmethod
    def _state_delta(
        cls, previous: dict[str, Any], current: dict[str, Any]
    ) -> dict[str, Any]:
        identities = {
            "sessions": ("session_id",),
            "runs": ("run_id",),
            "start_idempotency": (
                "tenant_id",
                "principal_id",
                "idempotency_key",
            ),
            "command_results": ("run_id", "idempotency_key"),
            "execution_resources": ("run_id",),
            "execution_resource_command_results": ("run_id", "idempotency_key"),
            "checkpoints": ("checkpoint_id",),
            "suspensions": ("suspension_id",),
            "interactions": ("interaction_id",),
            "interaction_resolutions": ("interaction_id",),
            "session_commit_proposals": ("proposal_id",),
            "session_commit_command_results": ("target_id", "idempotency_key"),
        }
        upserts: dict[str, list[dict[str, Any]]] = {}
        deletes: dict[str, list[list[Any]]] = {}
        for collection, keys in identities.items():
            old_rows = {
                tuple(value.get(key) for key in keys): value
                for value in previous.get(collection, ())
            }
            new_rows = {
                tuple(value.get(key) for key in keys): value
                for value in current.get(collection, ())
            }
            changed = [
                value
                for identity, value in new_rows.items()
                if old_rows.get(identity) != value
            ]
            removed = [list(identity) for identity in old_rows.keys() - new_rows.keys()]
            if changed:
                upserts[collection] = changed
            if removed:
                deletes[collection] = removed

        appends: dict[str, dict[str, list[dict[str, Any]]]] = {}
        replacements: dict[str, dict[str, list[dict[str, Any]]]] = {}
        map_deletes: dict[str, list[str]] = {}
        for collection in ("run_events",):
            old_map = previous.get(collection, {})
            new_map = current.get(collection, {})
            for key, rows in new_map.items():
                old_rows = old_map.get(key, ())
                if len(rows) < len(old_rows) or rows[: len(old_rows)] != old_rows:
                    replacements.setdefault(collection, {})[key] = rows
                elif len(rows) > len(old_rows):
                    appends.setdefault(collection, {})[key] = rows[len(old_rows) :]
            removed = sorted(set(old_map) - set(new_map))
            if removed:
                map_deletes[collection] = removed
        for collection in ("fork_base_events", "steer_inbox"):
            old_map = previous.get(collection, {})
            new_map = current.get(collection, {})
            changed = {
                key: rows for key, rows in new_map.items() if old_map.get(key) != rows
            }
            if changed:
                replacements[collection] = changed
            removed = sorted(set(old_map) - set(new_map))
            if removed:
                map_deletes[collection] = removed
        return {
            "upserts": upserts,
            "deletes": deletes,
            "appends": appends,
            "replacements": replacements,
            "map_deletes": map_deletes,
        }

    @staticmethod
    def _apply_state_delta(state: dict[str, Any], delta: dict[str, Any]) -> None:
        identities = {
            "sessions": ("session_id",),
            "runs": ("run_id",),
            "start_idempotency": (
                "tenant_id",
                "principal_type",
                "principal_id",
                "idempotency_key",
            ),
            "command_results": ("run_id", "idempotency_key"),
            "execution_resources": ("run_id",),
            "execution_resource_command_results": ("run_id", "idempotency_key"),
            "checkpoints": ("checkpoint_id",),
            "suspensions": ("suspension_id",),
            "interactions": ("interaction_id",),
            "interaction_resolutions": ("interaction_id",),
            "session_commit_proposals": ("proposal_id",),
            "session_commit_command_results": ("target_id", "idempotency_key"),
        }
        for collection, rows in delta.get("upserts", {}).items():
            keys = identities[collection]
            current = {
                tuple(value.get(key) for key in keys): value
                for value in state.get(collection, ())
            }
            for value in rows:
                current[tuple(value.get(key) for key in keys)] = value
            state[collection] = list(current.values())
        for collection, rows in delta.get("deletes", {}).items():
            keys = identities[collection]
            removed = {tuple(value) for value in rows}
            state[collection] = [
                value
                for value in state.get(collection, ())
                if tuple(value.get(key) for key in keys) not in removed
            ]
        for collection, values in delta.get("appends", {}).items():
            target = state.setdefault(collection, {})
            for key, rows in values.items():
                target.setdefault(key, []).extend(rows)
        for collection, values in delta.get("replacements", {}).items():
            state.setdefault(collection, {}).update(values)
        for collection, keys in delta.get("map_deletes", {}).items():
            for key in keys:
                state.setdefault(collection, {}).pop(key, None)

    async def _ensure_session_loaded(
        self, session_id: str, *, missing_ok: bool = False
    ) -> None:
        if session_id in self._loaded_session_ids:
            return
        async with self._load_lock:
            if session_id in self._loaded_session_ids:
                return
            snapshot = self._session_dir(session_id) / "state.json"
            if not snapshot.exists():
                if missing_ok:
                    return
                raise self._not_found("session.not_found", session_id)
            async with self._lock:
                await asyncio.to_thread(self._load_one_session, snapshot, session_id)

    async def _ensure_descendants_loaded(self, session_id: str) -> None:
        """Load the physical child tree before applying standard cascade delete."""

        root = self._session_dir(session_id)
        snapshots = sorted(
            (
                path
                for path in root.rglob("state.json")
                if path.parent != root
                and "sub_sessions" in path.relative_to(root).parts
            ),
            key=lambda path: len(path.parts),
        )
        if not snapshots:
            return
        async with self._load_lock:
            async with self._lock:
                for snapshot in snapshots:
                    state = await asyncio.to_thread(self._peek_snapshot_state, snapshot)
                    rows = state.get("sessions", ())
                    if len(rows) != 1:
                        await asyncio.to_thread(
                            self._load_one_session, snapshot, expected_session_id=None
                        )
                        continue
                    child_session_id = str(rows[0].get("session_id", ""))
                    if child_session_id in self._loaded_session_ids:
                        continue
                    await asyncio.to_thread(
                        self._load_one_session,
                        snapshot,
                        expected_session_id=child_session_id,
                    )

    async def _ensure_resource_loaded(
        self, collection: str, identity_key: str, identity: str
    ) -> None:
        if self._resource_is_loaded(collection, identity_key, identity):
            return
        async with self._load_lock:
            if self._resource_is_loaded(collection, identity_key, identity):
                return
            match = await asyncio.to_thread(
                self._locate_resource_snapshot, collection, identity_key, identity
            )
            if match is None:
                raise self._not_found(f"{identity_key}.not_found", identity)
            async with self._lock:
                await asyncio.to_thread(
                    self._load_one_session, match, expected_session_id=None
                )

    def _resource_is_loaded(
        self, collection: str, identity_key: str, identity: str
    ) -> bool:
        mappings = {
            "runs": self._runs,
            "checkpoints": self._checkpoints,
            "suspensions": self._suspensions,
            "interactions": self._interactions,
            "session_commit_proposals": self._session_commit_proposals,
        }
        mapping: Any = mappings[collection]
        if identity_key in {
            "run_id",
            "checkpoint_id",
            "suspension_id",
            "interaction_id",
            "proposal_id",
        }:
            return identity in mapping
        return False

    def _locate_resource_snapshot(
        self, collection: str, identity_key: str, identity: str
    ) -> Path | None:
        # This is a compatibility locator for APIs that carry only a Run or
        # checkpoint ID. It peeks at one snapshot at a time and loads only
        # the matching Session; it never constructs a Session catalog.
        for snapshot in self.sessions_root.rglob("state.json"):
            state = self._peek_snapshot_state(snapshot)
            if any(
                value.get(identity_key) == identity
                for value in state.get(collection, ())
            ):
                rows = state.get("sessions", ())
                if len(rows) == 1 and rows[0].get("session_id"):
                    self._write_location(str(rows[0]["session_id"]), snapshot.parent)
                return snapshot
        return None

    def _peek_snapshot_state(self, snapshot: Path) -> dict[str, Any]:
        try:
            state, _count = self._read_session_aggregate(snapshot)
            return state
        except Exception:
            # Full validation produces the typed corruption error if this is
            # the requested Session. Unrelated damaged Sessions do not prevent
            # a known healthy Session from being opened.
            return {}

    def _load_one_session(
        self, snapshot: Path, expected_session_id: str | None
    ) -> None:
        aggregate_state, journal_count = self._read_session_aggregate(snapshot)
        session_rows = aggregate_state.get("sessions", ())
        if len(session_rows) != 1:
            raise self._corrupt(
                "session_store.aggregate_corrupt",
                f"snapshot {snapshot} does not contain exactly one Session",
            )
        session_id = session_rows[0]["session_id"]
        if expected_session_id is not None and session_id != expected_session_id:
            raise self._corrupt(
                "session_store.path_mismatch",
                f"snapshot path for {expected_session_id!r} contains {session_id!r}",
            )
        if self._session_dir(session_id) != snapshot.parent:
            raise self._corrupt(
                "session_store.path_mismatch",
                f"Session {session_id!r} is stored under the wrong directory",
            )

        combined = self._dump_state_locked()
        try:
            self._merge_state(combined, aggregate_state)
        except ValueError as exc:
            raise self._corrupt("session_store.aggregate_duplicate", str(exc)) from exc
        subscribers = self._subscribers
        derived = self._derived_state
        self._load_state_locked(combined)
        self._subscribers.update(subscribers)
        self._derived_state.update(derived)
        self._loaded_session_ids.add(session_id)
        self._persisted_states[session_id] = deepcopy(aggregate_state)
        self._journal_commits[session_id] = journal_count
        for entry in aggregate_state.get("start_idempotency", ()):
            self._write_start_idempotency(entry, session_id)
        self._refresh_session_views(session_id, aggregate_state)

    def _read_start_lookup(self, command, context) -> dict[str, Any] | None:
        identity = {
            "tenant_id": context.actor.tenant_id,
            "principal_type": context.actor.principal_type.value,
            "principal_id": context.actor.principal_id,
            "idempotency_key": command.idempotency_key,
        }
        path = self._start_idempotency_path(identity)
        if not path.exists():
            # v4 lookups created before principal_type was part of the scope.
            # Loading that aggregate is safe: the coordinator derives the old
            # type from its trusted Run context before deciding idempotency.
            legacy_identity = dict(identity)
            legacy_identity.pop("principal_type")
            path = self._start_idempotency_path(legacy_identity)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise self._corrupt(
                "session_store.idempotency_corrupt",
                f"idempotency lookup {path} cannot be read: {exc}",
            ) from exc
        if value.get("format") != self.format_version:
            raise self._corrupt(
                "session_store.idempotency_format",
                f"idempotency lookup {path} uses an unsupported format",
            )
        return value

    def _read_snapshot(self, snapshot: Path) -> SessionSnapshotEnvelope:
        try:
            payload = json.loads(snapshot.read_bytes())
        except Exception as exc:
            raise self._corrupt(
                "session_store.corrupt_snapshot",
                f"snapshot {snapshot} contains invalid JSON: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise self._corrupt(
                "session_store.corrupt_snapshot",
                f"snapshot {snapshot} must contain a JSON object",
            )
        stored_checksum = payload.get("checksum")
        unsigned = {key: value for key, value in payload.items() if key != "checksum"}
        if stored_checksum != self._checksum(unsigned):
            raise self._corrupt(
                "session_store.hash_mismatch",
                f"snapshot {snapshot} checksum mismatch",
            )
        try:
            envelope = SessionSnapshotEnvelope.model_validate(payload)
        except Exception as exc:
            raise self._corrupt(
                "session_store.corrupt_snapshot",
                f"snapshot {snapshot} contains an invalid schema: {exc}",
            ) from exc
        return envelope

    def _read_session_aggregate(self, snapshot: Path) -> tuple[dict[str, Any], int]:
        envelope = self._read_snapshot(snapshot)
        state = envelope.state.model_dump(mode="json")
        revision = envelope.current_session_revision
        journal = snapshot.parent / "journal.jsonl"
        if not journal.exists():
            return state, 0
        try:
            encoded = journal.read_bytes()
        except OSError as exc:
            raise self._corrupt(
                "session_store.journal_unreadable",
                f"journal {journal} cannot be read: {exc}",
            ) from exc
        lines = encoded.splitlines(keepends=True)
        complete_count = 0
        for index, line in enumerate(lines):
            if not line.endswith(b"\n"):
                if index != len(lines) - 1:
                    raise self._corrupt(
                        "session_store.journal_corrupt",
                        f"journal {journal} contains an incomplete middle record",
                    )
                LOGGER.warning("ignoring incomplete Session journal tail: %s", journal)
                break
            complete_count += 1
            try:
                payload = json.loads(line)
            except Exception as exc:
                raise self._corrupt(
                    "session_store.journal_corrupt",
                    f"journal {journal} record {index + 1} contains invalid JSON: {exc}",
                ) from exc
            if not isinstance(payload, dict):
                raise self._corrupt(
                    "session_store.journal_corrupt",
                    f"journal {journal} record {index + 1} must contain a JSON object",
                )
            stored_checksum = payload.get("checksum")
            unsigned = {
                key: value for key, value in payload.items() if key != "checksum"
            }
            if stored_checksum != self._checksum(unsigned):
                raise self._corrupt(
                    "session_store.hash_mismatch",
                    f"journal {journal} record {index + 1} checksum mismatch",
                )
            try:
                mutation = SessionMutationEnvelope.model_validate(payload)
            except Exception as exc:
                raise self._corrupt(
                    "session_store.journal_corrupt",
                    f"journal {journal} record {index + 1} contains an invalid schema: {exc}",
                ) from exc
            if mutation.current_session_revision <= revision:
                continue
            if mutation.previous_session_revision != revision:
                raise self._corrupt(
                    "session_store.revision_gap",
                    f"journal {journal} is not revision-contiguous at record {index + 1}",
                )
            self._apply_state_delta(
                state, mutation.mutation.model_dump(mode="json", exclude={"kind"})
            )
            applied_revision = int(state["sessions"][0]["revision"])
            if applied_revision != mutation.current_session_revision:
                raise self._corrupt(
                    "session_store.revision_mismatch",
                    f"journal {journal} record {index + 1} produced revision {applied_revision}",
                )
            revision = mutation.current_session_revision
        return state, complete_count

    def _write_start_idempotency(self, entry: dict[str, Any], session_id: str) -> None:
        payload = {
            "format": self.format_version,
            "tenant_id": entry.get("tenant_id"),
            "principal_type": entry.get("principal_type"),
            "principal_id": entry["principal_id"],
            "idempotency_key": entry["idempotency_key"],
            "request_digest": entry["request_digest"],
            "session_id": session_id,
            "run_id": entry["run_id"],
        }
        self._atomic_json_write(self._start_idempotency_path(payload), payload)

    def _delete_session_files(
        self, session_id: str, deleted_session_ids: frozenset[str]
    ) -> None:
        with self._filesystem_lock:
            transaction = self._write_transaction(
                "delete", session_id, session_ids=deleted_session_ids
            )
            source = self._session_dir(session_id)
            target = self.trash_root / f"{source.name}-{new_id('delete')}"
            if source.exists():
                source.replace(target)
                self._fsync_directory(source.parent)
            for deleted_session_id in deleted_session_ids:
                self._remove_start_lookups(deleted_session_id)
                self._location_path(deleted_session_id).unlink(missing_ok=True)
            if target.exists():
                shutil.rmtree(target)
            transaction.unlink(missing_ok=True)
            self._fsync_directory(self.transactions_root)

    def _write_transaction(
        self,
        operation: str,
        session_id: str,
        *,
        session_ids: frozenset[str] | None = None,
    ) -> Path:
        path = self.transactions_root / f"{new_id('txn')}.json"
        payload: dict[str, Any] = {
            "format": self.format_version,
            "operation": operation,
            "session_id": session_id,
        }
        if session_ids is not None:
            payload["session_ids"] = sorted(session_ids)
        self._atomic_json_write(path, payload)
        return path

    def _recover_transactions(self) -> None:
        for path in sorted(self.transactions_root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                session_id = str(value["session_id"])
                session_ids = {
                    str(candidate)
                    for candidate in value.get("session_ids", (session_id,))
                }
                operation = value["operation"]
            except Exception as exc:
                raise self._corrupt(
                    "session_store.transaction_corrupt",
                    f"transaction intent {path} cannot be read: {exc}",
                ) from exc
            session_dir = self._session_dir(session_id)
            if operation == "create":
                snapshot = session_dir / "state.json"
                if not snapshot.exists() and session_dir.exists():
                    shutil.rmtree(session_dir)
                if not snapshot.exists():
                    self._location_path(session_id).unlink(missing_ok=True)
                else:
                    # The snapshot/journal is the canonical create record.  A
                    # crash can occur before its lookup files are materialized;
                    # rebuild them before retiring the transaction intent so a
                    # retry with the same idempotency key remains exactly-once.
                    state, _journal_count = self._read_session_aggregate(snapshot)
                    for entry in state.get("start_idempotency", ()):
                        self._write_start_idempotency(entry, session_id)
                    self._write_location(session_id, session_dir)
            elif operation == "delete":
                if session_dir.exists():
                    shutil.rmtree(session_dir)
                for candidate in self.trash_root.glob(f"{session_dir.name}-*"):
                    if candidate.is_dir():
                        shutil.rmtree(candidate)
                for deleted_session_id in session_ids:
                    self._remove_start_lookups(deleted_session_id)
                    self._location_path(deleted_session_id).unlink(missing_ok=True)
            else:
                raise self._corrupt(
                    "session_store.transaction_operation",
                    f"unknown transaction operation {operation!r}",
                )
            path.unlink(missing_ok=True)

    def _remove_start_lookups(self, session_id: str) -> None:
        for path in self.idempotency_root.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("session_id") == session_id:
                path.unlink(missing_ok=True)

    def _derived_path(self, session_id: str, namespace: str, key: str) -> Path:
        return (
            self._session_dir(session_id)
            / "derived"
            / self._safe_segment(namespace)
            / f"{self._safe_segment(key)}.json"
        )

    def _session_dir(self, session_id: str) -> Path:
        location = self._location_path(session_id)
        if location.is_file():
            try:
                payload = json.loads(location.read_text(encoding="utf-8"))
                if (
                    payload.get("format") != SESSION_LAYOUT_FORMAT
                    or payload.get("session_id") != session_id
                ):
                    raise ValueError("location identity does not match")
                candidate = (
                    self.sessions_root / str(payload["relative_path"])
                ).resolve()
                candidate.relative_to(self.sessions_root)
                return candidate
            except (
                OSError,
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                raise self._corrupt(
                    "session_store.location_corrupt",
                    f"Session location {location} is invalid: {exc}",
                ) from exc
        return self.sessions_root / self._safe_segment(session_id)

    def _session_dir_for_state(self, session_id: str, state: dict[str, Any]) -> Path:
        current = self._session_dir(session_id)
        if (current / "state.json").is_file():
            return current
        rows = state.get("sessions", ())
        if len(rows) != 1 or rows[0].get("session_id") != session_id:
            raise self._corrupt(
                "session_store.aggregate_corrupt",
                f"state for {session_id!r} does not contain exactly its Session",
            )
        parent_session_id = rows[0].get("parent_session_id")
        if parent_session_id:
            parent_dir = self._session_dir(str(parent_session_id))
            target = (
                parent_dir / "sub_sessions" / self._safe_segment(session_id)
            ).resolve()
        else:
            target = (self.sessions_root / self._safe_segment(session_id)).resolve()
        target.relative_to(self.sessions_root)
        self._write_location(session_id, target)
        return target

    def _location_path(self, session_id: str) -> Path:
        return self.locations_root / f"{self._safe_segment(session_id)}.json"

    def _write_location(self, session_id: str, session_dir: Path) -> None:
        resolved = session_dir.resolve()
        relative = resolved.relative_to(self.sessions_root)
        self._atomic_json_write(
            self._location_path(session_id),
            {
                "format": SESSION_LAYOUT_FORMAT,
                "session_id": session_id,
                "relative_path": relative.as_posix(),
            },
        )

    @staticmethod
    def _safe_segment(value: str) -> str:
        encoded = quote(value, safe="")
        if not encoded or encoded in {".", ".."}:
            encoded = f"value-{hashlib.sha256(value.encode()).hexdigest()}"
        return encoded

    def _start_idempotency_path(self, payload: dict[str, Any]) -> Path:
        parts = [str(payload.get("tenant_id") or "")]
        if "principal_type" in payload:
            parts.append(str(payload.get("principal_type") or ""))
        parts.extend(
            (str(payload["principal_id"]), str(payload["idempotency_key"]))
        )
        identity = "\0".join(parts)
        return (
            self.idempotency_root
            / f"{hashlib.sha256(identity.encode()).hexdigest()}.json"
        )

    @staticmethod
    def _merge_state(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key in (
            "sessions",
            "runs",
            "start_idempotency",
            "command_results",
            "execution_resources",
            "execution_resource_command_results",
            "checkpoints",
            "suspensions",
            "interactions",
            "interaction_resolutions",
            "session_commit_proposals",
            "session_commit_command_results",
        ):
            target[key].extend(source.get(key, ()))
        for key in ("run_events", "fork_base_events", "steer_inbox"):
            overlap = set(target[key]) & set(source.get(key, {}))
            if overlap:
                raise ValueError(f"duplicate aggregate identities: {sorted(overlap)}")
            target[key].update(source.get(key, {}))

    @classmethod
    def _atomic_json_write(cls, path: Path, payload: dict[str, Any]) -> None:
        cls._atomic_bytes_write(path, cls._canonical_json(payload))

    @classmethod
    def _atomic_bytes_write(cls, path: Path, encoded: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.read_bytes() == encoded:
                return
        except FileNotFoundError:
            pass
        temporary = path.with_name(f".{path.name}.{new_id('tmp')}")
        with temporary.open("wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        cls._fsync_directory(path.parent)

    @staticmethod
    def _canonical_json(payload: dict[str, Any]) -> bytes:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @classmethod
    def _checksum(cls, payload: dict[str, Any]) -> str:
        return f"sha256:{hashlib.sha256(cls._canonical_json(payload)).hexdigest()}"

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _error(code: str, category: ErrorCategory, message: str) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=category,
                message=message,
                safe_to_resume=True,
            )
        )

    @staticmethod
    def _corrupt(code: str, message: str) -> SessionStoreCorruptionError:
        return SessionStoreCorruptionError(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.CORRUPT_STATE,
                message=message,
                safe_to_resume=False,
            )
        )


class _FilesystemSessionStoreMeta(type):
    def __getattr__(cls, name):
        return getattr(_FilesystemSessionState, name)


class FilesystemSessionStore(metaclass=_FilesystemSessionStoreMeta):
    """Composed durable SessionStore facade.

    Persistence and transactional behavior are owned components rather than a
    public inheritance contract. Private compatibility access is delegated only
    so migration and corruption tooling can inspect the storage adapter.
    """

    def __init__(self, *args, **kwargs) -> None:
        object.__setattr__(
            self, "_coordinator", _FilesystemSessionState(*args, **kwargs)
        )

    def __getattr__(self, name):
        return getattr(self._coordinator, name)

    def __setattr__(self, name, value) -> None:
        if name == "_coordinator":
            object.__setattr__(self, name, value)
        else:
            setattr(self._coordinator, name, value)
