"""Read workspace files and build temporary downloads without following symlinks."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
import json
from urllib.parse import quote
from pathlib import Path, PurePosixPath
import stat
from tempfile import SpooledTemporaryFile
from zipfile import ZipFile, ZIP_DEFLATED

MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 20000


def relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value or ".")
    if path.is_absolute() or ".." in path.parts or "\\" in value or "\0" in value:
        raise ValueError("invalid workspace path")
    return path


@contextmanager
def open_entry(root: Path, path: PurePosixPath):
    """Open each component relative to its parent fd; reject symlink swaps."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(path.parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if index < len(path.parts) - 1:
                flags |= os.O_DIRECTORY
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        if not (stat.S_ISDIR(os.fstat(fd).st_mode) or stat.S_ISREG(os.fstat(fd).st_mode)):
            raise ValueError("unsupported file type")
        yield fd
    finally:
        os.close(fd)


def list_directory(root: Path, value: str) -> list[dict]:
    path = relative_path(value)
    with open_entry(root, path) as fd:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise NotADirectoryError(value)
        items = []
        with os.scandir(fd) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    continue
                items.append({
                    "name": entry.name, "path": (path / entry.name).as_posix(),
                    "is_directory": stat.S_ISDIR(info.st_mode), "size": info.st_size,
                    "modified_at": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                })
                if len(items) > MAX_ARCHIVE_ENTRIES:
                    raise OverflowError("too many files in directory")
        return sorted(items, key=lambda item: (not item["is_directory"], item["name"].casefold()))


def prepare_download(root: Path, value: str, *, archive_name: str = "workspace",
                     max_bytes: int = MAX_ARCHIVE_BYTES, max_entries: int = MAX_ARCHIVE_ENTRIES):
    path = relative_path(value)
    output = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    try:
        with open_entry(root, path) as fd:
            if stat.S_ISREG(os.fstat(fd).st_mode):
                if os.fstat(fd).st_size > max_bytes:
                    raise OverflowError("file is too large to download")
                with os.fdopen(os.dup(fd), "rb") as source:
                    remaining = os.fstat(fd).st_size
                    while remaining:
                        chunk = source.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            break
                        output.write(chunk)
                        remaining -= len(chunk)
                filename = path.name
            else:
                filename = f"{path.name or archive_name}.zip"
                total = [0, 0]
                with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                    _archive_directory(fd, archive, path.name or archive_name, total,
                                       max_bytes=max_bytes, max_entries=max_entries)
        output.seek(0)
        return output, filename
    except BaseException:
        output.close()
        raise


def _archive_directory(fd: int, archive: ZipFile, prefix: str, total: list[int],
                       *, max_bytes: int = MAX_ARCHIVE_BYTES,
                       max_entries: int = MAX_ARCHIVE_ENTRIES):
    total[0] += 1
    if total[0] > max_entries:
        raise OverflowError("directory is too large to archive")
    archive.writestr(f"{prefix}/", b"")
    with os.scandir(fd) as entries:
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                continue
            child = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                opened = os.fstat(child)
                name = f"{prefix}/{entry.name}"
                if stat.S_ISDIR(opened.st_mode):
                    _archive_directory(child, archive, name, total,
                                       max_bytes=max_bytes, max_entries=max_entries)
                elif stat.S_ISREG(opened.st_mode):
                    total[0] += 1
                    total[1] += opened.st_size
                    if total[0] > max_entries or total[1] > max_bytes:
                        raise OverflowError("directory is too large to archive")
                    with os.fdopen(os.dup(child), "rb") as source, archive.open(name, "w") as target:
                        # Read the size observed at open, even if a running tool appends.
                        remaining = opened.st_size
                        while remaining:
                            chunk = source.read(min(remaining, 1024 * 1024))
                            if not chunk:
                                break
                            target.write(chunk)
                            remaining -= len(chunk)
            finally:
                os.close(child)


def prepare_session_export(session_id: str, state: dict):
    """Package a database-backed Session without creating business storage."""
    name = quote(session_id, safe="")
    if name in {"", ".", ".."}:
        raise ValueError("invalid Session id")
    output = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
    total = 0
    try:
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
            def write_json(path, value):
                nonlocal total
                encoded = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
                total += len(encoded)
                if total > MAX_ARCHIVE_BYTES or len(archive.filelist) >= MAX_ARCHIVE_ENTRIES:
                    raise OverflowError("Session is too large to archive")
                archive.writestr(f"{name}/{path}", encoded)

            # state.json is the full canonical aggregate, not just visible messages.
            write_json("state.json", state)
            write_json("session.json", state["sessions"][0])
            for run in state.get("runs", []):
                run_id = quote(run["run_id"], safe="")
                write_json(f"runs/{run_id}.json", run)
                write_json(f"events/{run_id}.json", state.get("run_events", {}).get(run["run_id"], []))
        output.seek(0)
        return output, f"{name}.zip"
    except BaseException:
        output.close()
        raise
