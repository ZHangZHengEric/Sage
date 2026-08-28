"""Authoritative per-Session filesystem storage for SAgents v2.

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
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.runtime.session.ephemeral import (
    SESSION_AGGREGATE_FORMAT,
    EphemeralSessionStore,
)
from sagents.v2.runtime.session.journal import (
    FILESYSTEM_SESSION_STORE_FORMAT,
    SessionCommitEnvelope,
)

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows hosts need a dedicated lock adapter.
    fcntl = None  # type: ignore[assignment]


LOGGER = logging.getLogger(__name__)


class StoreInUseError(SageV2Error):
    """Raised when another writer already owns the same Store root."""


class SessionStoreCorruptionError(SageV2Error):
    """Raised when authoritative journal integrity cannot be established."""


class FilesystemSessionStore(EphemeralSessionStore):
    """Single-host durable SessionStore backed by one journal per Session.

    Runtime semantics live in :class:`EphemeralSessionStore`; this subclass
    implements only the durability hooks. This is the central invariant that
    prevents the file and in-memory implementations from acquiring different
    CAS, idempotency, checkpoint, or interaction behavior.
    """

    format_version = FILESYSTEM_SESSION_STORE_FORMAT

    def __init__(self, root: str | Path, **kwargs: Any) -> None:
        self.root = Path(root).expanduser().resolve()
        self.sessions_root = self.root / "sessions"
        self.idempotency_root = self.root / "idempotency" / "start"
        self.transactions_root = self.root / "transactions"
        self.trash_root = self.root / "trash"
        self._filesystem_lock = threading.RLock()
        self._journal_sequences: dict[str, int] = {}
        self._stored_session_revisions: dict[str, int] = {}
        self._loaded_session_ids: set[str] = set()
        self._load_lock = asyncio.Lock()
        self._closed = False
        self._prepare_root()
        self._writer_handle = (self.root / ".writer.lock").open("a+b")
        self._acquire_writer_lock()
        super().__init__(**kwargs)
        try:
            self._recover_transactions()
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
        # The journal remains authoritative. These entries are also materialized
        # under idempotency/start only as a lookup that can be rebuilt after a
        # crash; removing that directory never loses an acknowledged result.
        start_entries = list(state.get("start_idempotency", ()))
        await asyncio.to_thread(
            self._append_session_state, session_id, state, start_entries
        )
        self._loaded_session_ids.add(session_id)

    async def _delete_storage_locked(self, session_id: str) -> None:
        await asyncio.to_thread(self._delete_session_files, session_id)

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
        result = await super().delete_session(session_id)
        self._loaded_session_ids.discard(session_id)
        return result

    async def list_session_runs(self, session_id):
        await self._ensure_session_loaded(session_id)
        return await super().list_session_runs(session_id)

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
            self.idempotency_root,
            self.transactions_root,
            self.trash_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        metadata_path = self.root / "store.json"
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise self._corrupt(
                    "session_store.metadata_corrupt",
                    f"store metadata cannot be read: {exc}",
                ) from exc
            if metadata.get("format") != self.format_version:
                raise self._error(
                    "session_store.unsupported_format",
                    ErrorCategory.UNSUPPORTED_SCHEMA,
                    f"unsupported SessionStore format {metadata.get('format')!r}",
                )
            return
        self._atomic_json_write(
            metadata_path,
            {"format": self.format_version, "store_id": new_id("store")},
        )

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

    def _append_session_state(
        self,
        session_id: str,
        state: dict[str, Any],
        start_entries: list[dict[str, Any]],
    ) -> None:
        with self._filesystem_lock:
            session_dir = self._session_dir(session_id)
            journal = session_dir / "journal.jsonl"
            is_new = not journal.exists()
            transaction = None
            if is_new:
                transaction = self._write_transaction("create", session_id)
                session_dir.mkdir(parents=True, exist_ok=True)
                (session_dir / "derived").mkdir(exist_ok=True)
                (session_dir / "lock").touch(exist_ok=True)

            current_revision = int(state["sessions"][0]["revision"])
            previous_revision = self._stored_session_revisions.get(session_id, 0)
            journal_sequence = self._journal_sequences.get(session_id, 0) + 1
            unsigned = {
                "format": self.format_version,
                "transaction_id": new_id("session_tx"),
                "journal_sequence": journal_sequence,
                "previous_session_revision": previous_revision,
                "current_session_revision": current_revision,
                "state": state,
            }
            checksum = self._checksum(unsigned)
            envelope = SessionCommitEnvelope(**unsigned, checksum=checksum)
            encoded = self._canonical_json(envelope.model_dump(mode="json")) + b"\n"
            with journal.open("ab", buffering=0) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            self._fsync_directory(session_dir)

            for entry in start_entries:
                self._write_start_idempotency(entry, session_id)
            self._journal_sequences[session_id] = journal_sequence
            self._stored_session_revisions[session_id] = current_revision
            if transaction is not None:
                transaction.unlink(missing_ok=True)
                self._fsync_directory(self.transactions_root)

    async def _ensure_session_loaded(
        self, session_id: str, *, missing_ok: bool = False
    ) -> None:
        if session_id in self._loaded_session_ids:
            return
        async with self._load_lock:
            if session_id in self._loaded_session_ids:
                return
            journal = self._session_dir(session_id) / "journal.jsonl"
            if not journal.exists():
                if missing_ok:
                    return
                raise self._not_found("session.not_found", session_id)
            async with self._lock:
                await asyncio.to_thread(self._load_one_session, journal, session_id)

    async def _ensure_resource_loaded(
        self, collection: str, identity_key: str, identity: str
    ) -> None:
        if self._resource_is_loaded(collection, identity_key, identity):
            return
        async with self._load_lock:
            if self._resource_is_loaded(collection, identity_key, identity):
                return
            match = await asyncio.to_thread(
                self._locate_resource_journal, collection, identity_key, identity
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

    def _locate_resource_journal(
        self, collection: str, identity_key: str, identity: str
    ) -> Path | None:
        # This is a compatibility locator for APIs that carry only a Run or
        # checkpoint ID. It peeks at one final envelope at a time and loads only
        # the matching Session; it never constructs a Session catalog.
        for session_dir in self.sessions_root.iterdir():
            journal = session_dir / "journal.jsonl"
            if not journal.is_file():
                continue
            state = self._peek_latest_state(journal)
            if any(
                value.get(identity_key) == identity
                for value in state.get(collection, ())
            ):
                return journal
        return None

    def _peek_latest_state(self, journal: Path) -> dict[str, Any]:
        raw = journal.read_bytes()
        lines = raw.splitlines(keepends=True)
        if lines and not lines[-1].endswith(b"\n"):
            lines.pop()
        if not lines:
            return {}
        try:
            return dict(json.loads(lines[-1]).get("state", {}))
        except (TypeError, json.JSONDecodeError):
            # Full validation produces the typed corruption error if this is
            # the requested Session. Unrelated damaged Sessions do not prevent
            # a known healthy Session from being opened.
            return {}

    def _load_one_session(self, journal: Path, expected_session_id: str | None) -> None:
        envelope = self._read_latest_envelope(journal)
        session_rows = envelope.state.get("sessions", ())
        if len(session_rows) != 1:
            raise self._corrupt(
                "session_store.aggregate_corrupt",
                f"journal {journal} does not contain exactly one Session",
            )
        session_id = session_rows[0]["session_id"]
        if expected_session_id is not None and session_id != expected_session_id:
            raise self._corrupt(
                "session_store.path_mismatch",
                f"journal path for {expected_session_id!r} contains {session_id!r}",
            )
        if self._session_dir(session_id) != journal.parent:
            raise self._corrupt(
                "session_store.path_mismatch",
                f"Session {session_id!r} is stored under the wrong directory",
            )

        combined = self._dump_state_locked()
        try:
            self._merge_state(combined, envelope.state)
        except ValueError as exc:
            raise self._corrupt("session_store.aggregate_duplicate", str(exc)) from exc
        subscribers = self._subscribers
        derived = self._derived_state
        self._load_state_locked(combined)
        self._subscribers.update(subscribers)
        self._derived_state.update(derived)
        self._journal_sequences[session_id] = envelope.journal_sequence
        self._stored_session_revisions[session_id] = envelope.current_session_revision
        self._loaded_session_ids.add(session_id)
        for entry in envelope.state.get("start_idempotency", ()):
            self._write_start_idempotency(entry, session_id)

    def _read_start_lookup(self, command, context) -> dict[str, Any] | None:
        identity = {
            "tenant_id": context.actor.tenant_id,
            "principal_id": context.actor.principal_id,
            "idempotency_key": command.idempotency_key,
        }
        path = self._start_idempotency_path(identity)
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

    def _read_latest_envelope(self, journal: Path) -> SessionCommitEnvelope:
        raw = journal.read_bytes()
        lines = raw.splitlines(keepends=True)
        if lines and not lines[-1].endswith(b"\n"):
            # An interrupted final append never became an acknowledged commit.
            LOGGER.warning("ignoring incomplete Session journal tail: %s", journal)
            lines.pop()
        if not lines:
            raise self._corrupt(
                "session_store.empty_journal", f"journal {journal} has no commit"
            )
        latest: SessionCommitEnvelope | None = None
        previous_revision = 0
        for expected_sequence, line in enumerate(lines, start=1):
            try:
                raw_envelope = json.loads(line)
                envelope = SessionCommitEnvelope.model_validate(raw_envelope)
            except Exception as exc:
                raise self._corrupt(
                    "session_store.corrupt_envelope",
                    f"journal {journal} contains invalid JSON or schema: {exc}",
                ) from exc
            unsigned = envelope.model_dump(mode="json", exclude={"checksum"})
            if envelope.checksum != self._checksum(unsigned):
                raise self._corrupt(
                    "session_store.hash_mismatch",
                    f"journal {journal} checksum mismatch at record {expected_sequence}",
                )
            if envelope.journal_sequence != expected_sequence:
                raise self._corrupt(
                    "session_store.sequence_corrupt",
                    f"journal {journal} record sequence is not contiguous",
                )
            if envelope.previous_session_revision != previous_revision:
                raise self._corrupt(
                    "session_store.revision_corrupt",
                    f"journal {journal} Session revisions are not contiguous",
                )
            previous_revision = envelope.current_session_revision
            latest = envelope
        assert latest is not None
        return latest

    def _dump_session_state_locked(self, session_id: str) -> dict[str, Any]:
        payload = self._dump_state_locked()
        sessions = [
            value for value in payload["sessions"] if value["session_id"] == session_id
        ]
        if len(sessions) != 1:
            raise self._not_found("session.not_found", session_id)
        runs = [value for value in payload["runs"] if value["session_id"] == session_id]
        run_ids = {value["run_id"] for value in runs}
        interaction_ids = {
            value["interaction_id"]
            for value in payload["interactions"]
            if value["run_id"] in run_ids
        }
        proposals = [
            value
            for value in payload["session_commit_proposals"]
            if value["session_id"] == session_id
        ]
        proposal_ids = {value["proposal_id"] for value in proposals}
        return {
            "session_format_version": SESSION_AGGREGATE_FORMAT,
            "sessions": sessions,
            "runs": runs,
            "run_events": {
                key: value
                for key, value in payload["run_events"].items()
                if key in run_ids
            },
            "fork_base_events": {
                key: value
                for key, value in payload.get("fork_base_events", {}).items()
                if key in run_ids
            },
            "start_idempotency": [
                value
                for value in payload["start_idempotency"]
                if value["run_id"] in run_ids
            ],
            "command_results": [
                value
                for value in payload["command_results"]
                if value["run_id"] in run_ids
            ],
            "checkpoints": [
                value for value in payload["checkpoints"] if value["run_id"] in run_ids
            ],
            "suspensions": [
                value for value in payload["suspensions"] if value["run_id"] in run_ids
            ],
            "interactions": [
                value for value in payload["interactions"] if value["run_id"] in run_ids
            ],
            "interaction_resolutions": [
                value
                for value in payload["interaction_resolutions"]
                if value["interaction_id"] in interaction_ids
            ],
            "steer_inbox": {
                key: value
                for key, value in payload["steer_inbox"].items()
                if key in run_ids
            },
            "session_commit_proposals": proposals,
            "session_commit_command_results": [
                value
                for value in payload["session_commit_command_results"]
                if value["proposal"]["proposal_id"] in proposal_ids
            ],
        }

    def _write_start_idempotency(self, entry: dict[str, Any], session_id: str) -> None:
        payload = {
            "format": self.format_version,
            "tenant_id": entry.get("tenant_id"),
            "principal_id": entry["principal_id"],
            "idempotency_key": entry["idempotency_key"],
            "request_digest": entry["request_digest"],
            "session_id": session_id,
            "run_id": entry["run_id"],
        }
        self._atomic_json_write(self._start_idempotency_path(payload), payload)

    def _delete_session_files(self, session_id: str) -> None:
        with self._filesystem_lock:
            transaction = self._write_transaction("delete", session_id)
            source = self._session_dir(session_id)
            target = self.trash_root / f"{source.name}-{new_id('delete')}"
            if source.exists():
                source.replace(target)
                self._fsync_directory(self.sessions_root)
            self._remove_start_lookups(session_id)
            if target.exists():
                shutil.rmtree(target)
            transaction.unlink(missing_ok=True)
            self._journal_sequences.pop(session_id, None)
            self._stored_session_revisions.pop(session_id, None)

    def _write_transaction(self, operation: str, session_id: str) -> Path:
        path = self.transactions_root / f"{new_id('txn')}.json"
        self._atomic_json_write(
            path,
            {
                "format": self.format_version,
                "operation": operation,
                "session_id": session_id,
            },
        )
        return path

    def _recover_transactions(self) -> None:
        for path in sorted(self.transactions_root.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                session_id = str(value["session_id"])
                operation = value["operation"]
            except Exception as exc:
                raise self._corrupt(
                    "session_store.transaction_corrupt",
                    f"transaction intent {path} cannot be read: {exc}",
                ) from exc
            session_dir = self._session_dir(session_id)
            if operation == "create":
                journal = session_dir / "journal.jsonl"
                if not journal.exists() and session_dir.exists():
                    shutil.rmtree(session_dir)
            elif operation == "delete":
                if session_dir.exists():
                    shutil.rmtree(session_dir)
                for candidate in self.trash_root.glob(f"{session_dir.name}-*"):
                    if candidate.is_dir():
                        shutil.rmtree(candidate)
                self._remove_start_lookups(session_id)
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
        return self.sessions_root / self._safe_segment(session_id)

    @staticmethod
    def _safe_segment(value: str) -> str:
        encoded = quote(value, safe="")
        if not encoded or encoded in {".", ".."}:
            encoded = f"value-{hashlib.sha256(value.encode()).hexdigest()}"
        return encoded

    def _start_idempotency_path(self, payload: dict[str, Any]) -> Path:
        identity = "\0".join(
            (
                str(payload.get("tenant_id") or ""),
                str(payload["principal_id"]),
                str(payload["idempotency_key"]),
            )
        )
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
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{new_id('tmp')}")
        encoded = cls._canonical_json(payload)
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
