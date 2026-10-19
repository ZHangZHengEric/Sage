# pyright: strict
"""Pure Session aggregate state machine with no I/O or asyncio dependency."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from collections.abc import Iterable
from typing import Any, get_args

from pydantic import BaseModel, TypeAdapter

from sagents.v2.runtime.session.journal import (
    SessionAggregateSnapshotV2,
    SessionStateDeltaMutation,
)


_IDENTITIES = {
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
    "coordinator_command_results": ("idempotency_key",),
}

_ROW_TYPES: dict[str, type[BaseModel]] = {
    name: get_args(SessionAggregateSnapshotV2.model_fields[name].annotation)[0]
    for name in _IDENTITIES
}
_MAP_TYPES: dict[str, TypeAdapter[Any]] = {
    name: TypeAdapter(SessionAggregateSnapshotV2.model_fields[name].annotation)
    for name in ("run_events", "fork_base_events", "steer_inbox")
}


@dataclass(frozen=True)
class SessionAggregate:
    """Validated aggregate that returns a new value for every mutation."""

    snapshot: SessionAggregateSnapshotV2

    @property
    def session_id(self) -> str:
        if len(self.snapshot.sessions) != 1:
            raise ValueError("SessionAggregate must contain exactly one Session")
        return self.snapshot.sessions[0].session_id

    @property
    def revision(self) -> int:
        return self.snapshot.sessions[0].revision

    def apply(self, mutation: SessionStateDeltaMutation) -> "SessionAggregate":
        state = self.snapshot.model_dump(mode="json")
        delta = mutation.model_dump(mode="json", exclude={"kind"})
        for collection, rows in delta["upserts"].items():
            keys = _IDENTITIES[collection]
            current = {
                tuple(value.get(key) for key in keys): value
                for value in state.get(collection, ())
            }
            for row in rows:
                current[tuple(row.get(key) for key in keys)] = row
            state[collection] = list(current.values())
        for collection, rows in delta["patches"].items():
            keys = _IDENTITIES[collection]
            current = {
                tuple(value.get(key) for key in keys): value
                for value in state.get(collection, ())
            }
            for row in rows:
                identity = tuple(row.get(key) for key in keys)
                if identity not in current:
                    raise ValueError(f"cannot patch missing {collection} row: {identity}")
                current[identity] = {**current[identity], **row}
            state[collection] = list(current.values())
        for collection, identities in delta["deletes"].items():
            keys = _IDENTITIES[collection]
            removed = {tuple(value) for value in identities}
            state[collection] = [
                value
                for value in state.get(collection, ())
                if tuple(value.get(key) for key in keys) not in removed
            ]
        for collection, values in delta["appends"].items():
            target = state.setdefault(collection, {})
            for key, rows in values.items():
                target.setdefault(key, []).extend(deepcopy(rows))
        for collection, values in delta["replacements"].items():
            state.setdefault(collection, {}).update(deepcopy(values))
        for collection, keys in delta["map_deletes"].items():
            for key in keys:
                state.setdefault(collection, {}).pop(key, None)
        return SessionAggregate(SessionAggregateSnapshotV2.model_validate(state))

    def apply_many(self, mutations: Iterable[SessionStateDeltaMutation]) -> "SessionAggregate":
        """Replay a journal without copying and validating its entire prefix per row.

        Changed rows are still validated at every revision, so a later overwrite
        cannot hide corrupt intermediate state. The complete aggregate is built once.
        """
        state = self.snapshot.model_dump(mode="json")
        indexes: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {}

        def index(collection: str) -> dict[tuple[Any, ...], dict[str, Any]]:
            if collection not in indexes:
                keys = _IDENTITIES[collection]
                indexes[collection] = {
                    tuple(row.get(key) for key in keys): row
                    for row in state.get(collection, ())
                }
            return indexes[collection]

        for mutation in mutations:
            delta = mutation.model_dump(mode="json", exclude={"kind"})
            for operation in ("upserts", "patches"):
                for collection, rows in delta[operation].items():
                    current, keys = index(collection), _IDENTITIES[collection]
                    for row in rows:
                        identity = tuple(row.get(key) for key in keys)
                        if operation == "patches":
                            if identity not in current:
                                raise ValueError(f"cannot patch missing {collection} row: {identity}")
                            row = {**current[identity], **row}
                        current[identity] = _ROW_TYPES[collection].model_validate(row).model_dump(mode="json")
            for collection, identities in delta["deletes"].items():
                current = index(collection)
                for identity in identities:
                    current.pop(tuple(identity), None)
            for operation in ("appends", "replacements"):
                for collection, values in delta[operation].items():
                    validated = _MAP_TYPES[collection].dump_python(
                        _MAP_TYPES[collection].validate_python(values), mode="json")
                    target = state.setdefault(collection, {})
                    for key, rows in validated.items():
                        if operation == "appends":
                            target.setdefault(key, []).extend(rows)
                        else:
                            target[key] = rows
            for collection, keys in delta["map_deletes"].items():
                if collection not in _MAP_TYPES:
                    raise ValueError(f"unknown aggregate map: {collection}")
                for key in keys:
                    state.setdefault(collection, {}).pop(key, None)
        for collection, current in indexes.items():
            state[collection] = list(current.values())
        return SessionAggregate(SessionAggregateSnapshotV2.model_validate(state))
