# pyright: strict
"""Pure Session aggregate state machine with no I/O or asyncio dependency."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from sagents.v2.runtime.session.journal import (
    SessionAggregateSnapshotV2,
    SessionStateDeltaMutation,
)


_IDENTITIES = {
    "sessions": ("session_id",),
    "runs": ("run_id",),
    "start_idempotency": ("tenant_id", "principal_id", "idempotency_key"),
    "command_results": ("run_id", "idempotency_key"),
    "checkpoints": ("checkpoint_id",),
    "suspensions": ("suspension_id",),
    "interactions": ("interaction_id",),
    "interaction_resolutions": ("interaction_id",),
    "session_commit_proposals": ("proposal_id",),
    "session_commit_command_results": ("target_id", "idempotency_key"),
    "coordinator_command_results": ("idempotency_key",),
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
