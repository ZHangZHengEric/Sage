"""Workspace imports must stay within the bound Agent and tenant directory."""

import base64

import pytest

from app.v2.server.storage import downloads
from app.v2.server.storage.downloads import SnapshotChangedError, prepare_download
from app.v2.server.storage.external_workspaces import (
    ensure_workspace_directory, import_workspace_files, workspace_parts,
)
from app.v2.server.storage.paths import prepare_server_v2_storage


def test_workspace_import_is_scoped_idempotent_and_rejects_conflicts(tmp_path):
    paths = prepare_server_v2_storage(tmp_path)
    files = {"src/index.html": base64.b64encode(b"<html></html>").decode()}
    assert import_workspace_files(paths, "tenant-a", "agent-a", "projects/site", files) == 1
    assert import_workspace_files(paths, "tenant-a", "agent-a", "projects/site", files) == 1
    root = paths.workspace_path("tenant-a", "agent-a")
    assert (root / "projects/site/src/index.html").read_bytes() == b"<html></html>"
    assert not (paths.workspace_path("tenant-b", "agent-a") / "projects/site/src/index.html").exists()
    assert not (paths.workspace_path("tenant-a", "agent-b") / "projects/site/src/index.html").exists()
    with pytest.raises(FileExistsError):
        import_workspace_files(paths, "tenant-a", "agent-a", "projects/site",
                               {"src/index.html": base64.b64encode(b"changed").decode()})
    assert (root / "projects/site/src/index.html").read_bytes() == b"<html></html>"


@pytest.mark.parametrize("value", ["", "/tmp/outside", "../outside", "a/../b", "a//b",
                                      "a\\b", ".runs/item", "a/./b", "a/", "a\0b"])
def test_workspace_path_rejects_escape_and_ambiguous_forms(value):
    with pytest.raises(ValueError):
        workspace_parts(value)


def test_workspace_import_rejects_symlinks_and_bad_data(tmp_path):
    paths = prepare_server_v2_storage(tmp_path)
    root = paths.workspace_dir("tenant", "agent")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "projects").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        ensure_workspace_directory(paths, "tenant", "agent", "projects/site")
    assert not (outside / "site").exists()
    with pytest.raises(ValueError):
        import_workspace_files(paths, "tenant", "agent", "safe", {"file.txt": "not base64"})
    with pytest.raises(ValueError):
        import_workspace_files(paths, "tenant", "agent", "safe", {"../escape": "YQ=="})
    assert not (root / "safe").exists()


def test_workspace_import_enforces_total_limit_before_writing(tmp_path):
    paths = prepare_server_v2_storage(tmp_path)
    encoded = base64.b64encode(b"x" * (4 << 20)).decode()
    with pytest.raises(ValueError):
        import_workspace_files(paths, "tenant", "agent", "project",
                               {f"{index}.txt": encoded for index in range(5)})
    assert not (paths.workspace_path("tenant", "agent") / "project").exists()


def test_download_rejects_file_modified_during_snapshot(tmp_path, monkeypatch):
    project = tmp_path / "projects" / "site"
    project.mkdir(parents=True)
    page = project / "index.html"
    page.write_bytes(b"before")
    original_open = downloads.ZipFile.open

    class MutatingWriter:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

        def write(self, data):
            written = self.inner.write(data)
            page.write_bytes(b"after with a different size")
            return written

    def open_and_mutate(archive, name, mode="r", *args, **kwargs):
        opened = original_open(archive, name, mode, *args, **kwargs)
        return MutatingWriter(opened) if mode == "w" else opened

    monkeypatch.setattr(downloads.ZipFile, "open", open_and_mutate)
    with pytest.raises(SnapshotChangedError):
        prepare_download(tmp_path, "projects/site")


def test_workspace_delete_is_recursive_idempotent_and_isolated(tmp_path):
    from app.v2.server.storage.external_workspaces import delete_workspace_path
    paths = prepare_server_v2_storage(tmp_path)
    for tenant, agent in [("a", "one"), ("b", "one"), ("a", "two")]:
        import_workspace_files(paths, tenant, agent, "assets/nested", {"a.txt": "YQ=="})
    with pytest.raises(OSError):
        delete_workspace_path(paths, "a", "one", "assets")
    assert delete_workspace_path(paths, "a", "one", "assets", recursive=True)
    assert not delete_workspace_path(paths, "a", "one", "assets", recursive=True)
    assert (paths.workspace_path("b", "one") / "assets/nested/a.txt").exists()
    assert (paths.workspace_path("a", "two") / "assets/nested/a.txt").exists()
    assert not delete_workspace_path(paths, "missing", "agent", "file")
    assert not paths.workspace_path("missing", "agent").exists()


def test_workspace_delete_unlinks_symlinks_without_following_them(tmp_path):
    from app.v2.server.storage.external_workspaces import delete_workspace_path
    paths = prepare_server_v2_storage(tmp_path)
    root = paths.workspace_dir("a", "one")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("keep")
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        delete_workspace_path(paths, "a", "one", "link/keep", recursive=True)
    assert delete_workspace_path(paths, "a", "one", "link", recursive=True)
    (root / "dir").mkdir()
    (root / "dir" / "link").symlink_to(outside, target_is_directory=True)
    assert delete_workspace_path(paths, "a", "one", "dir", recursive=True)
    assert (outside / "keep").read_text() == "keep"
    root.rmdir()
    root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        delete_workspace_path(paths, "a", "one", "keep")
    assert (outside / "keep").exists()


@pytest.mark.parametrize("value", ["", ".", "..", "../a", "/tmp/a", "a/../b", "a//b", ".sage", "a\\b"])
def test_workspace_delete_rejects_invalid_paths(tmp_path, value):
    from app.v2.server.storage.external_workspaces import delete_workspace_path
    paths = prepare_server_v2_storage(tmp_path)
    with pytest.raises(ValueError):
        delete_workspace_path(paths, "a", "one", value, recursive=True)
