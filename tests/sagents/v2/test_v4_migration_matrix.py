import json
from pathlib import Path

import pytest

from sagents.v2.contracts.commands import CancelRun, InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.runtime.session.journal import (
    FILESYSTEM_SESSION_STORE_FORMAT,
    FILESYSTEM_SESSION_STORE_FORMAT_V2,
    FILESYSTEM_SESSION_STORE_FORMAT_V3,
)
from sagents.v2.runtime.session.migration import (
    _make_writable,
    adopt_unowned_sessions,
    migrate_manifest_v1,
    migrate_runtime_root,
)


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


async def _legacy_store(path: Path, legacy_format: str):
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
    metadata["format"] = legacy_format
    metadata_path.write_text(json.dumps(metadata))
    snapshot_path = next((path / "sessions").rglob("state.json"))
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["format"] = legacy_format
    snapshot["state"]["session_format_version"] = "sage.session-aggregate/v1"
    for session in snapshot["state"]["sessions"]:
        session.pop("owner", None)
    for run in snapshot["state"]["runs"]:
        run.pop("request_context", None)
    for entry in snapshot["state"]["start_idempotency"]:
        entry.pop("principal_type", None)
    snapshot["checksum"] = FilesystemSessionStore._checksum(
        {key: value for key, value in snapshot.items() if key != "checksum"}
    )
    snapshot_path.write_text(json.dumps(snapshot))
    return created


async def _v3_store(path: Path):
    return await _legacy_store(path, FILESYSTEM_SESSION_STORE_FORMAT_V3)


@pytest.mark.asyncio
async def test_desktop_adopts_only_unowned_legacy_sessions(tmp_path: Path):
    root = tmp_path / "sessions"
    created = await _legacy_store(root, FILESYSTEM_SESSION_STORE_FORMAT_V2)

    report = adopt_unowned_sessions(root, principal_id="default_user")

    assert report.adopted_sessions == 1
    snapshot_path = next((root / "sessions").rglob("state.json"))
    payload = json.loads(snapshot_path.read_text())
    assert payload["state"]["sessions"][0]["owner"] == {
        "principal_id": "default_user",
        "principal_type": "user",
        "tenant_id": None,
        "delegated_by": None,
        "scopes": [],
    }
    assert payload["state"]["start_idempotency"][0]["principal_type"] == "user"

    reopened = FilesystemSessionStore(root)
    default_user = RequestContext(
        actor=ActorRef(
            principal_id="default_user",
            principal_type=PrincipalType.USER,
        )
    )
    await reopened.authorize_session_actor(created.handle.session_id, default_user)
    await reopened.close()

    second = adopt_unowned_sessions(root, principal_id="another_user")
    assert second.adopted_sessions == 0


@pytest.mark.asyncio
async def test_owner_adoption_ignores_corrupt_already_owned_session(tmp_path: Path):
    root = tmp_path / "sessions"
    await _legacy_store(root, FILESYSTEM_SESSION_STORE_FORMAT_V2)
    first = adopt_unowned_sessions(root, principal_id="default_user")
    assert first.adopted_sessions == 1

    snapshot_path = next((root / "sessions").rglob("state.json"))
    payload = json.loads(snapshot_path.read_text())
    payload["checksum"] = "sha256:corrupt"
    snapshot_path.write_text(json.dumps(payload))

    second = adopt_unowned_sessions(root, principal_id="default_user")

    assert second.adopted_sessions == 0


@pytest.mark.asyncio
async def test_owner_adoption_rejects_corrupt_unowned_session(tmp_path: Path):
    root = tmp_path / "sessions"
    await _legacy_store(root, FILESYSTEM_SESSION_STORE_FORMAT_V2)
    snapshot_path = next((root / "sessions").rglob("state.json"))
    payload = json.loads(snapshot_path.read_text())
    payload["checksum"] = "sha256:corrupt"
    snapshot_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="checksum mismatch"):
        adopt_unowned_sessions(root, principal_id="default_user")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "legacy_format",
    [FILESYSTEM_SESSION_STORE_FORMAT_V2, FILESYSTEM_SESSION_STORE_FORMAT_V3],
)
async def test_known_legacy_store_is_readable_and_upgrades_on_write(
    tmp_path: Path,
    legacy_format: str,
):
    root = tmp_path / "sessions"
    created = await _legacy_store(root, legacy_format)
    snapshot_path = next((root / "sessions").rglob("state.json"))

    reopened = FilesystemSessionStore(root)
    restored = await reopened.get_run(created.handle.run_id)

    assert restored.run_id == created.handle.run_id
    assert json.loads(snapshot_path.read_text())["format"] == legacy_format
    metadata = json.loads((root / ".session-store" / "store.json").read_text())
    assert metadata["format"] == FILESYSTEM_SESSION_STORE_FORMAT
    assert metadata["read_compatible_from"] == FILESYSTEM_SESSION_STORE_FORMAT_V2

    await HarnessRuntime(reopened).cancel_run(
        CancelRun(
            run_id=created.handle.run_id,
            expected_revision=restored.revision,
            idempotency_key="cancel-legacy-run",
        ),
        CONTEXT,
    )
    await reopened.close()

    upgraded = json.loads(snapshot_path.read_text())
    assert upgraded["format"] == FILESYSTEM_SESSION_STORE_FORMAT
    assert upgraded["state"]["session_format_version"] == "sage.session-aggregate/v2"


@pytest.mark.asyncio
async def test_v3_supports_explicit_dry_run_then_atomic_migration(tmp_path: Path):
    root = tmp_path / "sessions"
    created = await _v3_store(root)
    (root / "settings.json").write_text('{"theme":"dark"}')
    (root / "memory").mkdir()
    (root / "memory" / "index.json").write_text("{}")
    (root / "desktop-v2-sidecar.json").write_text('{"pid":1}')

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
    _make_writable(report.backup)


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


def test_manifest_migration_dry_run_validates_without_writing(tmp_path: Path):
    source = tmp_path / "sage.yaml"
    source.write_text(
        """schema_version: sage/v1
kind: application
metadata: {id: app.test, version: 1.0.0, name: Test}
runtime: {}
entrypoint: {agent: main}
agents:
  main:
    name: Main
    instructions: {inline: hello}
    models: {}
"""
    )

    output = migrate_manifest_v1(source, dry_run=True)

    assert output == tmp_path / "sage.v2.yaml"
    assert not output.exists()


@pytest.mark.asyncio
async def test_migration_backup_permissions_do_not_follow_symlinks(tmp_path: Path):
    root = tmp_path / "sessions"
    await _v3_store(root)
    outside = tmp_path / "outside.txt"
    outside.write_text("owned elsewhere")
    outside.chmod(0o600)
    (root / "outside-link.txt").symlink_to(outside)

    report = migrate_runtime_root(root)

    assert report.backup is not None
    assert (report.backup / "outside-link.txt").is_symlink()
    assert outside.stat().st_mode & 0o777 == 0o600
    _make_writable(report.backup)
