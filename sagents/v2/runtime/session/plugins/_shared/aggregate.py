"""Backend-neutral aggregate replay, installation and eviction."""

from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from typing import Any
from weakref import WeakValueDictionary

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.session.aggregate import SessionAggregate
from sagents.v2.runtime.session.journal import (
    SessionAggregateSnapshotV2,
    SessionRowSnapshot,
    SessionStateDeltaMutation,
)
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from .cache import IdleSessionCache


def _principal_lookup_key(principal_type: str, principal_id: str) -> str:
    identity = f"{principal_type}\0{principal_id}".encode("utf-8")
    return f"typed:{hashlib.sha256(identity).hexdigest()}"


class SessionStoreCorruptionError(SageV2Error):
    """Raised when a stored Session aggregate cannot be trusted."""


_COMPACT_LISTS = (
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
)

_COMPACT_MAPS = ("fork_base_events", "steer_inbox")

_LOCATION_KINDS = (
    ("runs", "run_id"),
    ("checkpoints", "checkpoint_id"),
    ("suspensions", "suspension_id"),
    ("interactions", "interaction_id"),
    ("session_commit_proposals", "proposal_id"),
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    return value


class DurableAggregateCache:
    def __init__(
        self,
        *,
        max_cached_sessions=256,
        max_cached_bytes=256 * 1024**2,
        cache_idle_seconds=300,
        **kwargs,
    ):
        self._load_locks = WeakValueDictionary()
        self._loaded_session_ids = set()
        self._persisted_run_sequences = {}
        self._persisted_session_runs = {}
        self._persisted_session_revisions = {}
        self._persisted_mutation_counts = {}
        self._persisted_locations = {}
        self._persisted_start_keys = {}
        super().__init__(**kwargs)
        self._session_cache = IdleSessionCache(
            self,
            max_sessions=max_cached_sessions,
            max_bytes=max_cached_bytes,
            idle_seconds=cache_idle_seconds,
        )

    async def _reload_session_from_storage_locked(self, session_id: str) -> None:
        # Keep the aggregate installed during I/O. Otherwise lazy readers can
        # install it in the eviction gap and recovery installs it a second time.
        # The caller holds the Session operation lock; replacement of the shared
        # state must also be atomic with respect to other Session loaders.
        payload = await self._fetch_session(session_id)
        prepared = (
            await asyncio.to_thread(self._prepare_session, payload)
            if payload is not None
            else None
        )
        async with self._lock:
            if session_id in self._sessions:
                self._evict_session_locked(session_id)
            if payload is not None:
                self._install_session_locked(payload, prepared=prepared)

    def _evict_session_locked(self, session_id: str) -> None:
        run_ids = self._session_run_ids_locked(session_id)
        self._drop_session_objects_locked(session_id)
        self._forget_persisted_session(session_id)
        # SQL owns the durable projection. Releasing its redundant process
        # copy must not call forget_session(), which deletes the durable row.
        self._derived_state = {
            key: value
            for key, value in self._derived_state.items()
            if key[0] != session_id
        }
        lock = self._session_locks.get(session_id)
        if (
            not self._session_cache.users.get(session_id)
            and lock is not None
            and not lock.locked()
        ):
            self._session_locks.pop(session_id, None)
        for run_id in run_ids:
            if not self._subscribers.get(run_id):
                self._subscribers.pop(run_id, None)

    def _forget_persisted_session(self, session_id: str) -> None:
        self._session_cache.forget(session_id)
        self._loaded_session_ids.discard(session_id)
        self._persisted_session_revisions.pop(session_id, None)
        self._persisted_mutation_counts.pop(session_id, None)
        self._persisted_locations.pop(session_id, None)
        self._persisted_start_keys.pop(session_id, None)
        for run_id in self._persisted_session_runs.pop(session_id, set()):
            self._persisted_run_sequences.pop(run_id, None)

    def _remember_persisted_session(
        self,
        session_id: str,
        revision: int,
        run_sequences: dict[str, int],
        location_rows: set[tuple[str, str, str]],
        start_rows: set[tuple[str, ...]],
        mutation_count: int,
    ) -> None:
        previous = self._persisted_session_runs.get(session_id, set())
        for run_id in previous - set(run_sequences):
            self._persisted_run_sequences.pop(run_id, None)
        self._loaded_session_ids.add(session_id)
        self._persisted_session_revisions[session_id] = revision
        self._persisted_mutation_counts[session_id] = mutation_count
        self._persisted_session_runs[session_id] = set(run_sequences)
        self._persisted_run_sequences.update(run_sequences)
        self._persisted_locations[session_id] = location_rows
        self._persisted_start_keys[session_id] = start_rows
        self._session_cache.pin(session_id)
        self._session_cache.evicted_suspended.discard(session_id)

    @staticmethod
    def _prepare_session(
        payload: dict[str, Any],
    ) -> tuple[SessionStoreCoordinator, int]:
        """Validate one isolated aggregate without touching live coordinator rows."""
        session_rows = payload.get("sessions", ())
        if len(session_rows) != 1:
            raise SessionStoreCorruptionError(
                RuntimeErrorInfo(
                    code="session_store.aggregate_corrupt",
                    category=ErrorCategory.CORRUPT_STATE,
                    message="SQL snapshot does not contain exactly one Session",
                    safe_to_resume=False,
                )
            )
        prepared = SessionStoreCoordinator()
        prepared._load_state_locked(payload)
        return prepared, 4 * len(_json(payload).encode())

    def _install_session_locked(
        self, payload: dict[str, Any], *, prepared=None
    ) -> None:
        prepared, cache_bytes = (
            prepared if prepared is not None else self._prepare_session(payload)
        )
        session_id = payload["sessions"][0]["session_id"]
        # Publish only this Session. Replacing the complete coordinator would
        # invalidate unrelated writers' row references across their DB awaits.
        names = (
            "_sessions",
            "_runs",
            "_run_events",
            "_session_events",
            "_fork_base_events",
            "_start_idempotency",
            "_start_idempotency_digests",
            "_command_results",
            "_command_digests",
            "_execution_resources",
            "_execution_resource_command_results",
            "_execution_resource_command_digests",
            "_checkpoints",
            "_suspensions",
            "_interactions",
            "_interaction_resolutions",
            "_steer_inbox",
            "_session_commit_proposals",
            "_session_commit_command_results",
            "_session_commit_command_digests",
        )
        for name in names:
            if getattr(self, name).keys() & getattr(prepared, name).keys():
                # All collision checks precede publication, leaving live state
                # intact if a stored identity belongs to another Session.
                raise SessionStoreCorruptionError(
                    RuntimeErrorInfo(
                        code="session_store.aggregate_duplicate",
                        category=ErrorCategory.CORRUPT_STATE,
                        message=f"duplicate aggregate identities in {name}",
                        safe_to_resume=False,
                    )
                )
        for name in names:
            getattr(self, name).update(getattr(prepared, name))
        self._remember_persisted_session(
            session_id,
            int(payload["sessions"][0]["revision"]),
            {
                run_id: len(events)
                for run_id, events in payload.get("run_events", {}).items()
            },
            self._location_rows(session_id, payload),
            self._start_key_rows(session_id, payload),
            int(payload.get("_mutation_count", 0)),
        )
        self._session_cache.touch(session_id, size=cache_bytes)

    @staticmethod
    def _compact_state(state: dict[str, Any]) -> dict[str, Any]:
        compact = {"session_format_version": state["session_format_version"]}
        for key in _COMPACT_LISTS:
            compact[key] = deepcopy(state.get(key, []))
        for key in _COMPACT_MAPS:
            compact[key] = deepcopy(state.get(key, {}))
        return compact

    @staticmethod
    def _location_rows(session_id, compact) -> set[tuple[str, str, str]]:
        return {
            (key, str(value.get(key)), session_id)
            for collection, key in _LOCATION_KINDS
            for value in compact.get(collection, ())
            if value.get(key)
        }

    def _location_rows_after_mutation(self, session_id, mutation):
        current = {
            (kind, identity): (kind, identity, session_id)
            for kind, identity, _ in self._persisted_locations.get(session_id, set())
        }
        for collection, key in _LOCATION_KINDS:
            for identity in mutation["deletes"].get(collection, ()):
                current.pop((key, str(identity[0])), None)
            for row in mutation["upserts"].get(collection, ()):
                if row.get(key):
                    identity = str(row[key])
                    current[(key, identity)] = (key, identity, session_id)
        return set(current.values())

    @staticmethod
    def _start_key_rows(session_id, compact) -> set[tuple[str, ...]]:
        return {
            (
                str(entry.get("tenant_id") or ""),
                _principal_lookup_key(
                    str(entry.get("principal_type") or ""),
                    str(entry["principal_id"]),
                ),
                str(entry["idempotency_key"]),
                session_id,
                str(entry["run_id"]),
                str(entry["request_digest"]),
            )
            for entry in compact.get("start_idempotency", ())
        }

    def _start_rows_after_mutation(self, session_id, mutation):
        current = {
            row[:3]: row for row in self._persisted_start_keys.get(session_id, set())
        }
        for tenant_id, principal_type, principal_id, key in mutation["deletes"].get(
            "start_idempotency", ()
        ):
            lookup = (
                str(tenant_id or ""),
                _principal_lookup_key(str(principal_type or ""), str(principal_id)),
                str(key),
            )
            current.pop(lookup, None)
        for row in self._start_key_rows(
            session_id,
            {"start_idempotency": mutation["upserts"].get("start_idempotency", ())},
        ):
            current[row[:3]] = row
        return set(current.values())

    @staticmethod
    def _replay_mutations(compact, mutation_rows, revision, last_sequence):
        try:
            aggregate = SessionAggregate(
                SessionAggregateSnapshotV2.model_validate(compact)
            )
            current_revision = aggregate.revision
            revision_sequences = dict(aggregate.snapshot.sessions[0].revision_sequences)

            def mutations():
                nonlocal current_revision
                for next_revision, encoded in mutation_rows:
                    if int(next_revision) != current_revision + 1:
                        raise ValueError("non-contiguous Session mutation revisions")
                    delta = dict(_decode_json(encoded))
                    session_rows = delta.get("upserts", {}).get("sessions", ())
                    if len(session_rows) != 1 or int(
                        session_rows[0]["revision"]
                    ) != int(next_revision):
                        raise ValueError("Session mutation has an invalid head")
                    head = SessionRowSnapshot.model_validate(session_rows[0])
                    revision_sequences.update(head.revision_sequences)
                    current_revision = int(next_revision)
                    yield SessionStateDeltaMutation(**delta)

            aggregate = aggregate.apply_many(mutations())
            state = aggregate.snapshot.model_dump(mode="json")
            state["sessions"][0]["revision_sequences"] = revision_sequences
            if (
                current_revision != revision
                or state["sessions"][0]["last_sequence"] != last_sequence
            ):
                raise ValueError("Session head disagrees with its mutations")
            return state
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionStoreCorruptionError(
                RuntimeErrorInfo(
                    code="session_store.aggregate_corrupt",
                    category=ErrorCategory.CORRUPT_STATE,
                    message=f"SQL Session mutations are invalid: {exc}",
                    safe_to_resume=False,
                )
            ) from exc

    def _decode_session_rows(self, row, mutation_rows, event_rows):
        payload = self._replay_mutations(
            dict(_decode_json(row[0])), mutation_rows, int(row[1]), int(row[2])
        )
        payload["_mutation_count"] = len(mutation_rows)
        run_events: dict[str, list[dict[str, Any]]] = {}
        for run_id, event in event_rows:
            run_events.setdefault(run_id, []).append(_decode_json(event))
        payload["run_events"] = run_events
        return payload
