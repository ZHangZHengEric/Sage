from datetime import datetime, timezone

import pytest

from sagents.v2.runtime.session import (
    EphemeralSessionStore,
    FilesystemSessionStore,
    SessionAggregate,
    SessionStoreCoordinator,
)
from sagents.v2.runtime.session.journal import (
    SessionAggregateSnapshotV2,
    SessionRowSnapshot,
    SessionStateDeltaMutation,
)


def aggregate(revision: int = 1) -> SessionAggregate:
    now = datetime.now(timezone.utc)
    return SessionAggregate(
        SessionAggregateSnapshotV2(
            sessions=(
                SessionRowSnapshot(
                    session_id="session_1",
                    revision=revision,
                    last_sequence=0,
                    created_at=now,
                    updated_at=now,
                    revision_sequences={"0": 0, str(revision): 0},
                ),
            )
        )
    )


@pytest.mark.asyncio
async def test_public_session_stores_use_composition_not_state_store_inheritance(tmp_path):
    ephemeral = EphemeralSessionStore()
    filesystem = FilesystemSessionStore(tmp_path / "sessions")
    assert not isinstance(ephemeral, SessionStoreCoordinator)
    assert not isinstance(filesystem, SessionStoreCoordinator)
    assert isinstance(ephemeral._coordinator, SessionStoreCoordinator)
    assert isinstance(filesystem._coordinator, SessionStoreCoordinator)
    await ephemeral.close()
    await filesystem.close()


def test_session_aggregate_applies_typed_mutation_without_io():
    current = aggregate()
    mutation = SessionStateDeltaMutation(
        upserts={
            "sessions": [
                {
                    **aggregate().snapshot.sessions[0].model_dump(mode="json"),
                    "revision": 2,
                }
            ]
        }
    )

    updated = current.apply(mutation)

    assert current.revision == 1
    assert updated.revision == 2
