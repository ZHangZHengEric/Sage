"""Unit tests for the shared filesystem-safety helpers.

These cover the primitives the Local and Passthrough providers delegate to:
root de-duplication, path containment, and the atomic writer.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys

import pytest

from sagents.utils.sandbox import _fs_safety


# --- dedupe_roots -------------------------------------------------------------


def test_dedupe_roots_sorts_longest_first():
    roots = [("/a", False), ("/a/b/c", False), ("/a/b", False)]
    assert _fs_safety.dedupe_roots(roots) == [
        ("/a/b/c", False),
        ("/a/b", False),
        ("/a", False),
    ]


def test_dedupe_roots_read_only_requires_every_occurrence():
    # A root is read-only only when *every* mount of it is read-only; a single
    # writable mount keeps it writable (preserves historical behavior).
    assert _fs_safety.dedupe_roots([("/x", True), ("/x", False)]) == [("/x", False)]
    assert _fs_safety.dedupe_roots([("/x", True), ("/x", True)]) == [("/x", True)]


def test_dedupe_roots_drops_empty():
    assert _fs_safety.dedupe_roots([("", True), ("/y", False)]) == [("/y", False)]


# --- path_under_root ----------------------------------------------------------


def test_path_under_root_matches_root_and_descendants():
    assert _fs_safety.path_under_root("/root", "/root") is True
    assert _fs_safety.path_under_root("/root/sub/file", "/root") is True


def test_path_under_root_rejects_sibling_prefix():
    # "/root-evil" must not be treated as inside "/root".
    assert _fs_safety.path_under_root("/root-evil/file", "/root") is False


# --- resolve_within_roots -----------------------------------------------------


def test_resolve_within_roots_returns_realpath(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    roots = [(str(workspace), False)]
    resolved = _fs_safety.resolve_within_roots(
        str(workspace / "file.txt"),
        roots,
        operation="write",
        read_only_label="sandbox",
    )
    assert resolved == str(workspace / "file.txt")


def test_resolve_within_roots_rejects_traversal(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    roots = [(str(workspace), False)]
    with pytest.raises(PermissionError, match="outside sandbox workspace"):
        _fs_safety.resolve_within_roots(
            str(workspace / ".." / "escape.txt"),
            roots,
            operation="write",
            read_only_label="sandbox",
        )


def test_resolve_within_roots_rejects_write_to_read_only(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    roots = [(str(workspace), True)]
    with pytest.raises(PermissionError, match="read-only in passthrough sandbox"):
        _fs_safety.resolve_within_roots(
            str(workspace / "file.txt"),
            roots,
            operation="write",
            read_only_label="passthrough sandbox",
        )
    # A read on the same read-only root is still allowed.
    assert _fs_safety.resolve_within_roots(
        str(workspace / "file.txt"),
        roots,
        operation="read",
        read_only_label="passthrough sandbox",
    ) == str(workspace / "file.txt")


# --- write_text: atomicity ----------------------------------------------------


def test_write_text_overwrite_roundtrips(tmp_path):
    target = tmp_path / "f.txt"
    _fs_safety.write_text(str(target), "hello\n")
    assert target.read_text() == "hello\n"


def test_write_text_creates_parent_dirs(tmp_path):
    target = tmp_path / "a" / "b" / "f.txt"
    _fs_safety.write_text(str(target), "x")
    assert target.read_text() == "x"


def test_write_text_failure_preserves_original_and_leaves_no_temp(
    tmp_path, monkeypatch
):
    target = tmp_path / "f.txt"
    target.write_text("original\n")

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(_fs_safety.os, "replace", boom)

    with pytest.raises(OSError, match="simulated replace failure"):
        _fs_safety.write_text(str(target), "new content that must not land\n")

    # The original file is untouched...
    assert target.read_text() == "original\n"
    # ...and the aborted temp file was cleaned up.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".sage-tmp-")]
    assert leftovers == []


def test_write_text_overwrite_leaves_no_temp_files(tmp_path):
    target = tmp_path / "f.txt"
    _fs_safety.write_text(str(target), "a")
    _fs_safety.write_text(str(target), "b")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".sage-tmp-")]
    assert leftovers == []
    assert target.read_text() == "b"


# --- write_text: mode preservation --------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_write_text_preserves_existing_file_mode(tmp_path):
    target = tmp_path / "script.sh"
    target.write_text("#!/bin/sh\n")
    os.chmod(target, 0o750)

    _fs_safety.write_text(str(target), "#!/bin/sh\necho hi\n")

    assert stat.S_IMODE(target.stat().st_mode) == 0o750
    assert target.read_text() == "#!/bin/sh\necho hi\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_write_text_new_file_uses_default_mode(tmp_path):
    target = tmp_path / "new.txt"
    _fs_safety.write_text(str(target), "x")
    assert stat.S_IMODE(target.stat().st_mode) == _fs_safety.DEFAULT_FILE_MODE


def test_write_text_preserves_existing_file_xattrs(tmp_path):
    target = tmp_path / "metadata.txt"
    target.write_text("old\n")
    attribute = "com.sage.test" if sys.platform == "darwin" else "user.sage.test"
    if hasattr(os, "setxattr"):
        try:
            os.setxattr(target, attribute, b"preserved")
        except OSError as exc:
            pytest.skip(f"extended attributes are not supported: {exc}")
    elif sys.platform == "darwin" and shutil.which("xattr"):
        subprocess.run(["xattr", "-w", attribute, "preserved", str(target)], check=True)
    else:
        pytest.skip("extended attributes are not supported by this platform")

    _fs_safety.write_text(str(target), "new\n")

    assert target.read_text() == "new\n"
    if hasattr(os, "getxattr"):
        assert os.getxattr(target, attribute) == b"preserved"
    else:
        result = subprocess.run(
            ["xattr", "-p", attribute, str(target)],
            check=True,
            capture_output=True,
        )
        assert result.stdout.rstrip(b"\n") == b"preserved"


# --- write_text: append -------------------------------------------------------


def test_write_text_append_extends_existing(tmp_path):
    target = tmp_path / "log.txt"
    _fs_safety.write_text(str(target), "one\n")
    _fs_safety.write_text(str(target), "two\n", mode="append")
    assert target.read_text() == "one\ntwo\n"
