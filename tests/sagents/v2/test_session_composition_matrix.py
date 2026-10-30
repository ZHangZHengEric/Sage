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
from sagents.v2.runtime.session.plugins.mysql import MysqlSessionStore
from sagents.v2.runtime.session.plugins.mysql.redis import RedisMysqlSessionStore


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


@pytest.mark.parametrize("kind", ["memory", "filesystem", "mysql", "redis-mysql"])
@pytest.mark.parametrize(
    "attribute",
    ["read_events", "export_session_state", "_persistence_can_fail", "temporary_probe"],
)
async def test_store_facades_restore_temporary_attribute_overrides(tmp_path, kind, attribute):
    # SQL/Redis constructors are lazy; exercising real facades needs no servers.
    if kind == "memory":
        store = EphemeralSessionStore()
    elif kind == "filesystem":
        store = FilesystemSessionStore(tmp_path / "sessions")
    elif kind == "mysql":
        store = MysqlSessionStore("mysql://test:test@localhost/test")
    else:
        store = RedisMysqlSessionStore("mysql://test:test@localhost/test", redis_url="redis://localhost/0")
    original = getattr(store, attribute, None)
    try:
        with pytest.MonkeyPatch.context() as patch:
            for replacement in (object(), object()):
                patch.setattr(store, attribute, replacement, raising=original is not None)
                assert getattr(store, attribute) is replacement
                assert getattr(store._coordinator, attribute) is replacement
        assert getattr(store, attribute, None) == original
        assert getattr(store._coordinator, attribute, None) == original
    finally:
        await store.close()


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
