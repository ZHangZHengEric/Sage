import json
from pathlib import Path

import pytest

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.runtime.session.journal import (
    FILESYSTEM_SESSION_STORE_FORMAT,
    FILESYSTEM_SESSION_STORE_FORMAT_V3,
)
from sagents.v2.runtime.session.migration import (
    migrate_manifest_v1,
    migrate_runtime_root,
)


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


async def _v3_store(path: Path):
    store = FilesystemSessionStore(path)
    created = await store.create_run(
        StartRun(
            agent_id="agent_1",
            input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="start",
        ),
        CONTEXT,
    )
    await store.close()
    metadata_path = path / ".session-store" / "store.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["format"] = FILESYSTEM_SESSION_STORE_FORMAT_V3
    metadata_path.write_text(json.dumps(metadata))
    snapshot_path = next((path / "sessions").rglob("state.json"))
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["format"] = FILESYSTEM_SESSION_STORE_FORMAT_V3
    snapshot["state"]["session_format_version"] = "sage.session-aggregate/v1"
    snapshot["checksum"] = FilesystemSessionStore._checksum(
        {key: value for key, value in snapshot.items() if key != "checksum"}
    )
    snapshot_path.write_text(json.dumps(snapshot))
    return created


@pytest.mark.asyncio
async def test_v3_requires_explicit_dry_run_then_atomic_migration(tmp_path: Path):
    root = tmp_path / "sessions"
    created = await _v3_store(root)
    (root / "settings.json").write_text('{"theme":"dark"}')
    (root / "memory").mkdir()
    (root / "memory" / "index.json").write_text("{}")
    (root / "desktop-v2-sidecar.json").write_text('{"pid":1}')

    with pytest.raises(Exception, match="sage v2 migrate"):
        FilesystemSessionStore(root)

    dry_run = migrate_runtime_root(root, dry_run=True)
    assert dry_run.sessions == 1
    assert dry_run.runs == 1
    assert dry_run.backup is None
    assert json.loads((root / ".session-store/store.json").read_text())["format"] == FILESYSTEM_SESSION_STORE_FORMAT_V3

    report = migrate_runtime_root(root)
    assert report.backup is not None and report.backup.is_dir()
    assert report.backup.stat().st_mode & 0o222 == 0
    assert json.loads((root / ".session-store/store.json").read_text())["format"] == FILESYSTEM_SESSION_STORE_FORMAT
    assert (root / "settings.json").read_text() == '{"theme":"dark"}'
    assert (root / "memory" / "index.json").read_text() == "{}"
    assert not (root / "desktop-v2-sidecar.json").exists()
    reopened = FilesystemSessionStore(root)
    assert (await reopened.get_run(created.handle.run_id)).run_id == created.handle.run_id
    await reopened.close()


@pytest.mark.asyncio
async def test_migration_rejects_corruption_and_cleans_interrupted_target(tmp_path: Path):
    root = tmp_path / "sessions"
    await _v3_store(root)
    temporary = root.with_name(f".{root.name}.sage-v4-migration")
    temporary.mkdir()
    (temporary / "interrupted").write_text("partial")
    snapshot_path = next((root / "sessions").rglob("state.json"))
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["checksum"] = "sha256:corrupt"
    snapshot_path.write_text(json.dumps(snapshot))

    with pytest.raises(ValueError, match="checksum mismatch"):
        migrate_runtime_root(root)
    assert not temporary.exists()
    assert root.exists()


def test_manifest_migration_never_overwrites_source_or_target(tmp_path: Path):
    source = tmp_path / "sage.yaml"
    source.write_text(
        """schema_version: sage/v1
kind: application
metadata: {id: app.test, version: 1.0.0, name: Test}
runtime:
  scheduler: {max_concurrent_runs: 2}
entrypoint: {agent: main}
agents:
  main:
    name: Main
    instructions: {inline: hello}
    models: {}
interfaces:
  native: {enabled: true}
"""
    )

    output = migrate_manifest_v1(source)
    assert "schema_version: sage/v1" in source.read_text()
    assert "schema_version: sage/v2" in output.read_text()
    assert "sage.protocol.native" in output.read_text()
    with pytest.raises(FileExistsError):
        migrate_manifest_v1(source)
