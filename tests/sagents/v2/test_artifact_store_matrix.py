from __future__ import annotations

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.artifact import InMemoryArtifactStore
from sagents.v2.runtime.artifact import FilesystemArtifactStore


@pytest.fixture(params=["memory", "filesystem"])
def store(request, tmp_path):
    return InMemoryArtifactStore() if request.param == "memory" else FilesystemArtifactStore(tmp_path)


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
async def test_filesystem_snapshot_survives_restart_and_rejects_concurrent_overwrite(tmp_path):
    import asyncio

    first = FilesystemArtifactStore(tmp_path)
    second = FilesystemArtifactStore(tmp_path)
    outcomes = await asyncio.gather(
        first.put(artifact_id="same", media_type="image/jpeg", content=chunks(b"one")),
        second.put(artifact_id="same", media_type="image/jpeg", content=chunks(b"two")),
        return_exceptions=True,
    )
    assert sum(isinstance(value, SageV2Error) for value in outcomes) == 1
    assert next(value for value in outcomes if isinstance(value, SageV2Error)).info.code == "artifact.id_conflict"
    _, content = await FilesystemArtifactStore(tmp_path).get("same")
    assert b"".join([value async for value in content]) in {b"one", b"two"}


@pytest.mark.asyncio
async def test_filesystem_snapshot_detects_corruption(tmp_path):
    store = FilesystemArtifactStore(tmp_path)
    await store.put(artifact_id="image", media_type="image/jpeg", content=chunks(b"original"))
    path = store._path("image")
    header, _, _ = path.read_bytes().partition(b"\n")
    path.write_bytes(header + b"\ncorrupted")
    with pytest.raises(SageV2Error) as corrupted:
        await FilesystemArtifactStore(tmp_path).get("image")
    assert corrupted.value.info.code == "artifact.integrity_failed"


@pytest.mark.asyncio
async def test_filesystem_artifacts_store_binary_bytes_without_database(tmp_path):
    store = FilesystemArtifactStore(tmp_path)
    payload = b"\x00\xffbinary\nimage\x00"
    await store.put(artifact_id="../../image", media_type="image/jpeg", content=chunks(payload))
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].suffix == ".artifact"
    assert files[0].read_bytes().partition(b"\n")[2] == payload
    assert not list(tmp_path.glob("*.sqlite*"))
    assert not list(tmp_path.glob(".pending-*"))


@pytest.mark.asyncio
async def test_failed_file_publication_leaves_no_partial_attachment(tmp_path, monkeypatch):
    import os

    store = FilesystemArtifactStore(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("publication interrupted")

    monkeypatch.setattr(os, "link", fail)
    with pytest.raises(OSError, match="publication interrupted"):
        await store.put(artifact_id="image", media_type="image/jpeg", content=chunks(b"image"))
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(SageV2Error) as missing:
        await store.get("image")
    assert missing.value.info.code == "artifact.not_found"


@pytest.mark.asyncio
async def test_file_attachment_loader_never_follows_symlinks(tmp_path):
    import os
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("requires no-follow file opens")
    root = tmp_path / "artifacts"
    store = FilesystemArtifactStore(root)
    external = tmp_path / "secret"
    external.write_bytes(b"private")
    store._path("image").symlink_to(external)
    with pytest.raises(SageV2Error) as error:
        await store.get("image")
    assert error.value.info.code == "artifact.integrity_failed"
