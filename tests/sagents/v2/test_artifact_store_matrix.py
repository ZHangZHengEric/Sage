from __future__ import annotations

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.artifact import InMemoryArtifactStore
from sagents.v2.runtime.artifact import SqliteArtifactStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    return InMemoryArtifactStore() if request.param == "memory" else SqliteArtifactStore(tmp_path)


async def chunks(*values: bytes):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_artifacts_are_immutable_and_idempotent(store):
    metadata = {"nested": {"value": 1}}
    created = await store.put(
        artifact_id="artifact_1",
        content=chunks(b"one", b"two"),
        media_type="text/plain",
        metadata=metadata,
    )
    metadata["nested"]["value"] = 2
    created.metadata["nested"]["value"] = 3

    replayed = await store.put(
        artifact_id="artifact_1",
        content=chunks(b"onetwo"),
        media_type="text/plain",
        metadata={"nested": {"value": 1}},
    )
    loaded, content = await store.get("artifact_1")

    assert replayed == loaded
    assert loaded.metadata == {"nested": {"value": 1}}
    assert b"".join([value async for value in content]) == b"onetwo"

    with pytest.raises(SageV2Error) as conflict:
        await store.put(
            artifact_id="artifact_1",
            content=chunks(b"different"),
            media_type="text/plain",
        )
    assert conflict.value.info.code == "artifact.id_conflict"


@pytest.mark.asyncio
async def test_artifact_missing_is_typed(store):

    with pytest.raises(SageV2Error) as missing:
        await store.get("missing")

    assert missing.value.info.code == "artifact.not_found"


@pytest.mark.asyncio
async def test_sqlite_snapshot_survives_restart_and_rejects_concurrent_overwrite(tmp_path):
    import asyncio

    first = SqliteArtifactStore(tmp_path)
    second = SqliteArtifactStore(tmp_path)
    outcomes = await asyncio.gather(
        first.put(artifact_id="same", media_type="image/jpeg", content=chunks(b"one")),
        second.put(artifact_id="same", media_type="image/jpeg", content=chunks(b"two")),
        return_exceptions=True,
    )
    assert sum(isinstance(value, SageV2Error) for value in outcomes) == 1
    assert next(value for value in outcomes if isinstance(value, SageV2Error)).info.code == "artifact.id_conflict"
    _, content = await SqliteArtifactStore(tmp_path).get("same")
    assert b"".join([value async for value in content]) in {b"one", b"two"}


@pytest.mark.asyncio
async def test_sqlite_snapshot_detects_corruption(tmp_path):
    import sqlite3

    store = SqliteArtifactStore(tmp_path)
    await store.put(artifact_id="image", media_type="image/jpeg", content=chunks(b"original"))
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE artifacts SET payload = ? WHERE id = ?", (b"corrupted", "image"))
    with pytest.raises(SageV2Error) as corrupted:
        await SqliteArtifactStore(tmp_path).get("image")
    assert corrupted.value.info.code == "artifact.integrity_failed"
