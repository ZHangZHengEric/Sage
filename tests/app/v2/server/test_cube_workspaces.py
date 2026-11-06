from __future__ import annotations

import base64
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.v2.server.storage.cube_workspaces import CubeWorkspaceStorage
from sagents.v2.runtime.execution.sandbox.plugins.cube import cube_volume_name
from tests.sagents.v2.cube_fakes import FakeCubeClient


@pytest.fixture
def storage(tmp_path):
    client = FakeCubeClient(tmp_path / "external-cube")
    host = SimpleNamespace(
        execution=SimpleNamespace(sandbox_provider=SimpleNamespace(client=client))
    )
    return CubeWorkspaceStorage(host), client


def test_remote_files_survive_compute_cleanup_and_keep_tenants_isolated(storage):
    backend, client = storage
    files = {"nested/data.bin": base64.b64encode(b"\0\xffbinary").decode()}
    assert backend.import_files("alice", "agent", "project", files) == 1
    assert backend.import_files("alice", "agent", "project", files) == 1
    assert backend.list_directory("bob", "agent", "") == []
    assert (
        backend.list_directory("alice", "agent", "project")[0]["path"]
        == "project/nested"
    )
    output, name = backend.prepare_download("alice", "agent", "project")
    try:
        with ZipFile(output) as archive:
            assert archive.read("project/nested/data.bin") == b"\0\xffbinary"
    finally:
        output.close()
    assert name == "project.zip"
    assert all(sandbox.killed for sandbox in client.created)
    with pytest.raises(FileExistsError):
        backend.import_files("alice", "agent", "project", {"nested/data.bin": "YQ=="})


def test_remote_management_rejects_symlinks_and_recursive_delete_keeps_other_files(
    storage, tmp_path
):
    backend, client = storage
    backend.import_files("alice", "agent", "project", {"keep.txt": "YQ=="})
    outside = tmp_path / "outside"
    outside.write_text("keep")
    root = client.root / cube_volume_name("alice", "agent")
    (root / "project" / "link").symlink_to(outside)
    with pytest.raises(PermissionError):
        backend.prepare_download("alice", "agent", "project/link")
    with pytest.raises(ValueError):
        backend.delete_path("alice", "agent", "../outside", recursive=True)
    assert backend.delete_path("alice", "agent", "project", recursive=True)
    assert outside.read_text() == "keep"
    assert not backend.delete_path("alice", "agent", "project", recursive=True)
    assert all(sandbox.killed for sandbox in client.created)


def test_large_remote_import_is_chunked_and_published_as_one_file(storage):
    backend, client = storage
    content = b"\x00\xffdata" * 12000
    backend.import_files(
        "alice", "agent", "project", {"large.bin": base64.b64encode(content).decode()}
    )
    output, _ = backend.prepare_download("alice", "agent", "project/large.bin")
    try:
        assert output.read() == content
    finally:
        output.close()
    root = client.root / cube_volume_name("alice", "agent")
    assert not list(root.rglob(".sage-write-*"))


def test_remote_skill_sync_replaces_the_tree_and_preserves_the_previous_version(
    storage,
):
    backend, client = storage
    original = {"SKILL.md": b"original", "old.txt": b"keep in backup"}
    backend.write_skill("alice", "agent", "guide", original)
    backend.write_skill("bob", "agent", "guide", original)
    updated = {"SKILL.md": b"updated", "scripts/tool.py": b"print('new')"}
    backend.replace_skill("alice", "agent", "guide", updated)
    assert backend.skill_files("alice", "agent", "guide") == updated
    assert backend.skill_files("bob", "agent", "guide") == original
    root = client.root / cube_volume_name("alice", "agent")
    backups = list((root / "skills").glob(".sage-backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "old.txt").read_bytes() == b"keep in backup"
    assert not list((root / "skills").glob(".sage-stage-*"))
    assert all(sandbox.killed for sandbox in client.created)


def test_remote_binary_upload_retries_preserve_existing_content(storage, monkeypatch):
    from app.v2.server.storage import cube_workspaces

    backend, client = storage
    monkeypatch.setattr(cube_workspaces, "MAX_BINARY_BYTES", 100000, raising=False)
    content = b"\x00\xffdata" * 12000
    for _ in range(2):
        backend.import_file("alice", "agent", "uploads/data.bin", BytesIO(content))
    with pytest.raises(FileExistsError):
        backend.import_file(
            "alice", "agent", "uploads/data.bin", BytesIO(b"x" * len(content))
        )
    for invalid in (b"", b"x" * 100001):
        with pytest.raises(ValueError):
            backend.import_file("alice", "agent", "uploads/invalid", BytesIO(invalid))
    root = client.root / cube_volume_name("alice", "agent")
    assert (root / "uploads/data.bin").read_bytes() == content
    assert not list(root.rglob(".sage-write-*"))
    assert not (root / "uploads/invalid").exists()
    assert all(sandbox.killed for sandbox in client.created)


def test_remote_archive_excludes_only_its_root_entry_before_applying_limits(storage):
    backend, _ = storage
    backend.import_files(
        "alice",
        "agent",
        "project",
        {
            "uploads/large": base64.b64encode(b"x" * 100).decode(),
            "nested/uploads/keep": base64.b64encode(b"ok").decode(),
        },
    )
    with pytest.raises(OverflowError):
        backend.prepare_download("alice", "agent", "project", max_bytes=2)
    output, _ = backend.prepare_download(
        "alice",
        "agent",
        "project",
        max_bytes=2,
        max_entries=4,
        exclude_root_entry="uploads",
    )
    with output, ZipFile(output) as archive:
        assert archive.read("project/nested/uploads/keep") == b"ok"
        assert not any(
            name.startswith("project/uploads/") for name in archive.namelist()
        )


@pytest.mark.timeout(90)
def test_remote_binary_upload_supports_files_larger_than_the_tool_file_limit(storage):
    backend, client = storage
    content = b"\x00\xff" * ((4 << 20) + 1)
    backend.import_file("alice", "agent", "uploads/large.bin", BytesIO(content))
    output, _ = backend.prepare_download("alice", "agent", "uploads/large.bin")
    with output:
        assert output.read() == content
    root = client.root / cube_volume_name("alice", "agent")
    assert not list(root.rglob(".sage-write-*"))
