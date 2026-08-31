from datetime import datetime, timezone

import pytest

from sagents.v2.runtime.session import (
    EphemeralSessionRepository,
    EphemeralSessionStore,
    FilesystemSessionStore,
    SessionAggregate,
    SessionStateStore,
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
    assert not isinstance(ephemeral, SessionStateStore)
    assert not isinstance(filesystem, SessionStateStore)
    await ephemeral.close()
    await filesystem.close()


@pytest.mark.asyncio
async def test_coordinator_owns_per_session_cas_and_idempotency():
    repository = EphemeralSessionRepository()
    await repository.commit(aggregate())
    coordinator = SessionStoreCoordinator(repository)
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

    updated = await coordinator.commit(
        "session_1",
        expected_revision=1,
        idempotency_key="commit-1",
        mutation=mutation,
    )
    duplicate = await coordinator.commit(
        "session_1",
        expected_revision=1,
        idempotency_key="commit-1",
        mutation=mutation,
    )

    assert updated.revision == 2
    assert duplicate is updated
    restarted = SessionStoreCoordinator(repository)
    after_restart = await restarted.commit(
        "session_1",
        expected_revision=1,
        idempotency_key="commit-1",
        mutation=mutation,
    )
    assert after_restart.revision == 2
    conflicting_mutation = mutation.model_copy(
        update={"map_deletes": {"run_events": ["run-other"]}}
    )
    with pytest.raises(ValueError, match="different mutation"):
        await restarted.commit(
            "session_1",
            expected_revision=1,
            idempotency_key="commit-1",
            mutation=conflicting_mutation,
        )
    with pytest.raises(ValueError, match="revision conflict"):
        await coordinator.commit(
            "session_1",
            expected_revision=1,
            idempotency_key="commit-2",
            mutation=mutation,
        )
