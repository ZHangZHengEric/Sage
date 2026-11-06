"""Bounded, no-follow file operations inside a Cube Volume mount.

The Cube SDK currently decodes ``files.read`` as text.  Run this small helper
through the SDK command API so Sage's byte-oriented file port stays lossless.
All paths are resolved below the mounted volume with directory file descriptors.
"""

from __future__ import annotations

import base64
import json
import shlex


_REMOTE = r'''
import base64, errno, json, os, secrets, shutil, stat, sys

request = json.loads(base64.b64decode(sys.argv[1]))
root = request["root"]
parts = request["parts"]
flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

def directory(parts, create=False):
    fd = os.open(root, flags)
    try:
        for part in parts:
            if create:
                try: os.mkdir(part, 0o755, dir_fd=fd)
                except FileExistsError: pass
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise

def info(parent, name, prefix):
    item = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if stat.S_ISLNK(item.st_mode) or not (stat.S_ISREG(item.st_mode) or stat.S_ISDIR(item.st_mode)):
        raise PermissionError("unsupported file type")
    if stat.S_ISREG(item.st_mode) and item.st_nlink != 1:
        raise PermissionError("hard-linked file is not allowed")
    return {"path": prefix, "size": item.st_size if stat.S_ISREG(item.st_mode) else 0,
            "is_file": stat.S_ISREG(item.st_mode), "is_directory": stat.S_ISDIR(item.st_mode),
            "modified_at": item.st_mtime, "mtime_ns": item.st_mtime_ns, "ctime_ns": item.st_ctime_ns}

def entries(fd, prefix, recursive=False, exclude_entry=None):
    result = []
    for name in sorted(os.listdir(fd)):
        if name == exclude_entry: continue
        try: item = info(fd, name, prefix + "/" + name if prefix else name)
        except PermissionError: continue
        result.append(item)
        if len(result) > request.get("max_entries", 20000): raise OverflowError("too many workspace entries")
        if recursive and item["is_directory"]:
            child = os.open(name, flags, dir_fd=fd)
            try:
                nested = entries(child, item["path"], True)
                result.extend(nested)
                if len(result) > request.get("max_entries", 20000): raise OverflowError("too many workspace entries")
            finally: os.close(child)
    return result

try:
    operation = request["operation"]
    if operation in ("list", "walk"):
        fd = directory(parts)
        try: result = entries(fd, "/".join(parts), operation == "walk", request.get("exclude_entry"))
        finally: os.close(fd)
    elif operation == "mkdir":
        fd = directory(parts, create=True)
        os.close(fd)
        result = {}
    elif operation == "stat" and not parts:
        fd = directory(())
        os.close(fd)
        result = {"path": "", "size": 0, "is_file": False, "is_directory": True, "modified_at": 0}
    else:
        parent = directory(parts[:-1], create=operation in ("write", "write_begin"))
        name = parts[-1]
        try:
            if operation == "stat": result = info(parent, name, "/".join(parts))
            elif operation == "write_begin":
                try:
                    info(parent, name, "/".join(parts))
                    if not request["overwrite"]: raise FileExistsError(name)
                except FileNotFoundError: pass
                token = ".sage-write-" + secrets.token_hex(16)
                fd = os.open(token, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                os.close(fd)
                result = {"token": token}
            elif operation in ("write_chunk", "write_commit", "write_abort"):
                token = request["token"]
                if not token.startswith(".sage-write-") or "/" in token or "\\" in token:
                    raise ValueError("invalid write token")
                if operation == "write_abort":
                    try: os.unlink(token, dir_fd=parent)
                    except FileNotFoundError: pass
                    result = {}
                elif operation == "write_chunk":
                    data = base64.b64decode(request["data"], validate=True)
                    fd = os.open(token, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    try:
                        item = os.fstat(fd)
                        if not stat.S_ISREG(item.st_mode) or item.st_nlink != 1 or item.st_size != request["offset"]:
                            raise PermissionError("invalid staged write")
                        if item.st_size + len(data) > request["max_bytes"]: raise OverflowError("file exceeds limit")
                        with os.fdopen(fd, "wb", closefd=False) as f: f.write(data)
                    finally: os.close(fd)
                    result = {}
                else:
                    info(parent, token, token)
                    if request["overwrite"]:
                        try: info(parent, name, name)
                        except FileNotFoundError: pass
                        os.replace(token, name, src_dir_fd=parent, dst_dir_fd=parent)
                    else:
                        os.link(token, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                        os.unlink(token, dir_fd=parent)
                    result = info(parent, name, "/".join(parts))
            elif operation == "publish_skill":
                staged, backup = request["staged"], request["backup"]
                if any("/" in value or "\\" in value or not value.startswith(".sage-") for value in (staged, backup)):
                    raise ValueError("invalid Skill staging name")
                item = info(parent, staged, staged)
                if not item["is_directory"]: raise NotADirectoryError(staged)
                moved = False
                try:
                    info(parent, name, name)
                    os.rename(name, backup, src_dir_fd=parent, dst_dir_fd=parent)
                    moved = True
                except FileNotFoundError: pass
                try:
                    os.rename(staged, name, src_dir_fd=parent, dst_dir_fd=parent)
                except BaseException:
                    if moved: os.rename(backup, name, src_dir_fd=parent, dst_dir_fd=parent)
                    raise
                result = {"backup": backup if moved else None}
            elif operation == "read":
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    item = os.fstat(fd)
                    expected = request.get("expected")
                    if expected and [item.st_size, item.st_mtime_ns, item.st_ctime_ns] != expected:
                        raise ValueError("file changed while creating workspace snapshot")
                    limit = request["max_bytes"]
                    if not stat.S_ISREG(item.st_mode) or item.st_nlink != 1 or (not request.get("allow_large") and item.st_size > limit):
                        raise PermissionError("file is not a supported regular file or exceeds limit")
                    with os.fdopen(fd, "rb", closefd=False) as stream:
                        stream.seek(request.get("offset", 0))
                        data = stream.read(limit if request.get("allow_large") else limit + 1)
                    if len(data) > limit: raise OverflowError("file exceeds limit")
                    after = os.fstat(fd)
                    if expected and [after.st_size, after.st_mtime_ns, after.st_ctime_ns] != expected:
                        raise ValueError("file changed while creating workspace snapshot")
                    result = {"data": base64.b64encode(data).decode("ascii")}
                finally: os.close(fd)
            elif operation == "write":
                data = base64.b64decode(request["data"])
                if len(data) > request["max_bytes"]: raise OverflowError("file exceeds limit")
                mode = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK
                if not request["overwrite"]: mode |= os.O_EXCL
                fd = os.open(name, mode, 0o600, dir_fd=parent)
                try:
                    item = os.fstat(fd)
                    if not stat.S_ISREG(item.st_mode) or item.st_nlink != 1:
                        raise PermissionError("only regular files without hard links are allowed")
                    os.ftruncate(fd, 0)
                    with os.fdopen(fd, "wb", closefd=False) as stream: stream.write(data)
                finally: os.close(fd)
                result = info(parent, name, "/".join(parts))
            elif operation == "delete":
                item = info(parent, name, "/".join(parts))
                if item["is_directory"]:
                    os.rmdir(name, dir_fd=parent)
                else:
                    os.unlink(name, dir_fd=parent)
                result = {}
            elif operation == "remove":
                try: item = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError: item = None
                if item is not None:
                    if stat.S_ISDIR(item.st_mode):
                        if request.get("recursive"):
                            if not shutil.rmtree.avoids_symlink_attacks: raise RuntimeError("safe removal unavailable")
                            shutil.rmtree(name, dir_fd=parent)
                        else: os.rmdir(name, dir_fd=parent)
                    else: os.unlink(name, dir_fd=parent)
                result = item is not None
            else: raise ValueError("unsupported operation")
        finally: os.close(parent)
    print(json.dumps({"ok": result}, separators=(",", ":")))
except BaseException as exc:
    kind = "PermissionError" if isinstance(exc, OSError) and exc.errno == errno.ELOOP else type(exc).__name__
    print(json.dumps({"error": kind, "message": str(exc), "errno": getattr(exc, "errno", None)}, separators=(",", ":")))
'''


def relative_parts(path: str, *, root: str = "/workspace") -> tuple[str, ...]:
    if not isinstance(path, str) or "\x00" in path or "\\" in path:
        raise ValueError("invalid workspace path")
    if path.startswith("/"):
        if path != root and not path.startswith(root + "/"):
            raise PermissionError("path escapes workspace")
        path = path[len(root):].lstrip("/")
    parts = tuple(part for part in path.split("/") if part and part != ".")
    if any(part == ".." for part in parts):
        raise PermissionError("path escapes workspace")
    return parts


def _file_call(sandbox, operation: str, path: str, *, root: str = "/workspace", **kwargs):
    payload = {"operation": operation, "root": root, "parts": relative_parts(path, root=root), **kwargs}
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    command = "python3 -I -c " + shlex.quote(_REMOTE) + " " + shlex.quote(encoded)
    result = sandbox.commands.run(command, cwd=root, timeout=60)
    if result.exit_code != 0:
        raise RuntimeError(f"Cube workspace file operation failed: {result.stderr[:500]}")
    try:
        response = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError("Cube workspace file operation returned invalid data") from exc
    if "error" in response:
        kind = response["error"]
        message = response.get("message", kind)
        errors = {"FileNotFoundError": FileNotFoundError, "NotADirectoryError": NotADirectoryError,
                  "FileExistsError": FileExistsError, "IsADirectoryError": IsADirectoryError,
                  "PermissionError": PermissionError, "OverflowError": OverflowError,
                  "ValueError": ValueError, "OSError": OSError}
        error = errors.get(kind, RuntimeError)
        if issubclass(error, OSError) and response.get("errno") is not None:
            raise error(response["errno"], message)
        raise error(message)
    return response["ok"]


def cube_file_call(sandbox, operation: str, path: str, *, root: str = "/workspace", **kwargs):
    # Keep each shell argument below Linux MAX_ARG_STRLEN. Large writes are
    # staged beside their destination and published only after every chunk.
    if operation != "write" or len(kwargs.get("data", "")) <= 16 << 10:
        return _file_call(sandbox, operation, path, root=root, **kwargs)
    content = base64.b64decode(kwargs["data"], validate=True)
    if len(content) > kwargs["max_bytes"]:
        raise OverflowError("file exceeds limit")
    options = {key: kwargs[key] for key in ("max_bytes", "overwrite")}
    token = _file_call(sandbox, "write_begin", path, root=root, **options)["token"]
    try:
        for offset in range(0, len(content), 12 << 10):
            _file_call(sandbox, "write_chunk", path, root=root, token=token, offset=offset,
                max_bytes=kwargs["max_bytes"], data=base64.b64encode(content[offset:offset + (12 << 10)]).decode())
        return _file_call(sandbox, "write_commit", path, root=root, token=token, **options)
    finally:
        _file_call(sandbox, "write_abort", path, root=root, token=token)
