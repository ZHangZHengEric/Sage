from __future__ import annotations

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.artifact import InMemoryArtifactStore


async def chunks(*values: bytes):
    for value in values:
        yield value


@pytest.mark.asyncio
async def test_in_memory_artifacts_are_immutable_and_idempotent():
    store = InMemoryArtifactStore()
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
async def test_in_memory_artifact_missing_is_typed():
    store = InMemoryArtifactStore()

    with pytest.raises(SageV2Error) as missing:
        await store.get("missing")

    assert missing.value.info.code == "artifact.not_found"
