"""Server file management over the same Cube Volumes used by Run bindings.

An operation uses temporary compute, including when no Run is active. Only
download buffers and immutable Skill sources touch the Sage host filesystem.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from zipfile import ZipFile, ZIP_DEFLATED

from sagents.v2.runtime.execution.sandbox.plugins.cube import cube_volume_name
from sagents.v2.runtime.execution.sandbox.plugins.cube.files import cube_file_call
from app.v2.server.storage.downloads import (
    MAX_ARCHIVE_BYTES,
    MAX_ARCHIVE_ENTRIES,
    SnapshotChangedError,
    relative_path,
)
from app.v2.server.storage.external_workspaces import (
    MAX_BINARY_BYTES,
    decode_workspace_files,
    workspace_parts,
)


class CubeWorkspaceStorage:
    def __init__(self, host):
        self.host = host

    def _operation(self, user, agent, function):
        client = self.host.execution.sandbox_provider.client
        sandbox = client.create_sandbox(cube_volume_name(user, agent), timeout=300)
        try:
            return function(sandbox)
        finally:
            try:
                sandbox.kill()
            finally:
                close = getattr(sandbox, "close", None)
                if close is not None:
                    close()

    def list_directory(self, user, agent, value):
        path = relative_path(value).as_posix()

        def read(sandbox):
            rows = cube_file_call(
                sandbox, "list", path, max_entries=MAX_ARCHIVE_ENTRIES
            )
            return sorted(
                [
                    {
                        "name": PurePosixPath(row["path"]).name,
                        "path": row["path"],
                        "is_directory": row["is_directory"],
                        "size": row["size"],
                        "modified_at": datetime.fromtimestamp(
                            row["modified_at"], timezone.utc
                        ).isoformat(),
                    }
                    for row in rows
                ],
                key=lambda row: (not row["is_directory"], row["name"].casefold()),
            )

        return self._operation(user, agent, read)

    def workspace_version(self, user, agent, value, *, max_bytes=MAX_ARCHIVE_BYTES,
                          max_entries=MAX_ARCHIVE_ENTRIES, exclude_root_entry=None):
        path = relative_path(value).as_posix()

        def read(sandbox):
            try:
                return cube_file_call(sandbox, "version", path,
                                      max_bytes=max_bytes, max_entries=max_entries,
                                      exclude_entry=exclude_root_entry)
            except ValueError as exc:
                if str(exc) == "workspace changed while inspecting contents":
                    raise SnapshotChangedError(str(exc)) from exc
                raise

        return self._operation(user, agent, read)

    @staticmethod
    def _copy(sandbox, entry, target):
        remaining, offset = entry["size"], 0
        while remaining:
            try:
                data = cube_file_call(
                    sandbox,
                    "read",
                    entry["path"],
                    allow_large=True,
                    offset=offset,
                    max_bytes=min(remaining, 1 << 20),
                    expected=[entry["size"], entry["mtime_ns"], entry["ctime_ns"]],
                )
            except ValueError as exc:
                raise SnapshotChangedError(
                    "file changed while creating workspace snapshot"
                ) from exc
            chunk = base64.b64decode(data["data"], validate=True)
            if not chunk or len(chunk) > remaining:
                raise SnapshotChangedError(
                    "file changed while creating workspace snapshot"
                )
            target.write(chunk)
            offset += len(chunk)
            remaining -= len(chunk)
        current = cube_file_call(sandbox, "stat", entry["path"])
        if any(current[key] != entry[key] for key in ("size", "mtime_ns", "ctime_ns")):
            raise SnapshotChangedError("file changed while creating workspace snapshot")

    def prepare_download(
        self,
        user,
        agent,
        value,
        *,
        archive_name="workspace",
        max_bytes=MAX_ARCHIVE_BYTES,
        max_entries=MAX_ARCHIVE_ENTRIES,
        exclude_root_entry=None,
    ):
        path = relative_path(value)
        output = SpooledTemporaryFile(max_size=8 << 20, mode="w+b")

        def read(sandbox):
            entry = cube_file_call(sandbox, "stat", path.as_posix())
            if entry["is_file"]:
                if entry["size"] > max_bytes:
                    raise OverflowError("file is too large to download")
                self._copy(sandbox, entry, output)
                return path.name
            entries = cube_file_call(
                sandbox,
                "walk",
                path.as_posix(),
                max_entries=max_entries,
                exclude_entry=exclude_root_entry,
            )
            if (
                len(entries) + 1 > max_entries
                or sum(row["size"] for row in entries) > max_bytes
            ):
                raise OverflowError("directory is too large to archive")
            prefix = path.name or archive_name
            with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr(prefix + "/", b"")
                for row in entries:
                    relative = PurePosixPath(row["path"]).relative_to(path)
                    name = prefix + "/" + relative.as_posix()
                    if row["is_directory"]:
                        archive.writestr(name + "/", b"")
                    else:
                        with archive.open(name, "w") as target:
                            self._copy(sandbox, row, target)
            return prefix + ".zip"

        try:
            filename = self._operation(user, agent, read)
            output.seek(0)
            return output, filename
        except BaseException:
            output.close()
            raise

    def import_file(self, user, agent, path, source):
        workspace_parts(path)
        size = source.seek(0, 2)
        if not 0 < size <= MAX_BINARY_BYTES:
            raise ValueError("workspace file quota exceeded or empty workspace file")
        source.seek(0)

        def compare(sandbox):
            entry = cube_file_call(sandbox, "stat", path)
            if not entry["is_file"] or entry["size"] != size:
                raise FileExistsError("workspace file conflicts with existing data")

            class Comparison:
                def write(self, chunk):
                    if source.read(len(chunk)) != chunk:
                        raise FileExistsError(
                            "workspace file conflicts with existing data"
                        )

            try:
                self._copy(sandbox, entry, Comparison())
            except SnapshotChangedError as exc:
                raise FileExistsError(
                    "workspace file conflicts with existing data"
                ) from exc

        def write(sandbox):
            try:
                token = cube_file_call(sandbox, "write_begin", path, overwrite=False)[
                    "token"
                ]
            except FileExistsError:
                compare(sandbox)
                return
            try:
                offset = 0
                while chunk := source.read(48 << 10):
                    cube_file_call(
                        sandbox,
                        "write_chunk",
                        path,
                        token=token,
                        offset=offset,
                        max_bytes=MAX_BINARY_BYTES,
                        data=base64.b64encode(chunk).decode(),
                    )
                    offset += len(chunk)
                if offset != size:
                    raise ValueError("workspace upload changed while reading")
                try:
                    cube_file_call(
                        sandbox, "write_commit", path, token=token, overwrite=False
                    )
                except FileExistsError:
                    source.seek(0)
                    compare(sandbox)
            finally:
                cube_file_call(sandbox, "write_abort", path, token=token)

        self._operation(user, agent, write)

    def import_files(self, user, agent, directory, files):
        root, decoded = decode_workspace_files(directory, files)

        def write(sandbox):
            cube_file_call(sandbox, "mkdir", "/".join(root))
            for parts, content in decoded.items():
                path = "/".join((*root, *parts))
                try:
                    cube_file_call(
                        sandbox,
                        "write",
                        path,
                        data=base64.b64encode(content).decode(),
                        max_bytes=4 << 20,
                        overwrite=False,
                    )
                except FileExistsError:
                    current = cube_file_call(sandbox, "read", path, max_bytes=4 << 20)
                    if base64.b64decode(current["data"], validate=True) != content:
                        raise FileExistsError(
                            "workspace file conflicts with existing data"
                        )
            return len(decoded)

        return self._operation(user, agent, write)

    def delete_path(self, user, agent, path, *, recursive=False):
        workspace_parts(path)

        def delete(sandbox):
            try:
                return cube_file_call(sandbox, "remove", path, recursive=recursive)
            except FileNotFoundError:
                return False

        return self._operation(user, agent, delete)

    def write_skill(self, user, agent, name, files):
        from app.v2.server.skills.records import normalize_skill_name

        name = normalize_skill_name(name)

        # Skills supplied here have already passed catalog/ZIP validation.
        def write(sandbox):
            for relative, content in files.items():
                if len(content) > 8 << 20:
                    raise OverflowError("Skill file exceeds Cube file limit")
                cube_file_call(
                    sandbox,
                    "write",
                    f"skills/{name}/{relative}",
                    data=base64.b64encode(content).decode(),
                    max_bytes=8 << 20,
                    overwrite=True,
                )

        self._operation(user, agent, write)
        return PurePosixPath("/workspace/skills") / name

    def skill_files(self, user, agent, name):
        from app.v2.server.skills.records import normalize_skill_name

        root = "skills/" + normalize_skill_name(name)

        def read(sandbox):
            try:
                entries = cube_file_call(sandbox, "walk", root, max_entries=2000)
            except FileNotFoundError:
                return None
            if sum(row["size"] for row in entries) > 64 << 20:
                raise OverflowError("Skill exceeds Cube size limit")
            return {
                str(PurePosixPath(row["path"]).relative_to(root)): base64.b64decode(
                    cube_file_call(sandbox, "read", row["path"], max_bytes=8 << 20)[
                        "data"
                    ],
                    validate=True,
                )
                for row in entries
                if row["is_file"]
                and PurePosixPath(row["path"]).name
                not in {".materialized-skill.json", ".skill-manifest.json"}
            }

        return self._operation(user, agent, read)

    def replace_skill(self, user, agent, name, files):
        from uuid import uuid4
        from app.v2.server.skills.records import normalize_skill_name

        name = normalize_skill_name(name)
        token = uuid4().hex
        staged, backup = ".sage-stage-" + token, ".sage-backup-" + token

        def replace(sandbox):
            try:
                cube_file_call(sandbox, "mkdir", "skills/" + staged)
                for relative, content in files.items():
                    cube_file_call(
                        sandbox,
                        "write",
                        f"skills/{staged}/{relative}",
                        data=base64.b64encode(content).decode(),
                        max_bytes=8 << 20,
                        overwrite=False,
                    )
                cube_file_call(
                    sandbox,
                    "publish_skill",
                    "skills/" + name,
                    staged=staged,
                    backup=backup,
                )
            finally:
                try:
                    cube_file_call(
                        sandbox, "remove", "skills/" + staged, recursive=True
                    )
                except FileNotFoundError:
                    pass

        self._operation(user, agent, replace)
