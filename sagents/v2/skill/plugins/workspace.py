"""Stable Skill directories, with manager-authoritative synchronization.

All filesystem work uses the accepted Run's sandbox grants. Shared-workspace
leases protect concurrent Runs in this process; distributed hosts must isolate
workspaces or supply cross-process coordination. Read-only mounting requires a
real sandbox mount port and never falls back to writable copies or symlinks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import posixpath
from weakref import WeakValueDictionary

from sagents.v2.contracts.errors import ErrorCategory
from sagents.v2.runtime.execution.sandbox import FileOperation, OperationIntent
from sagents.v2.skill.contracts import SkillBundle, SkillDescriptor
from sagents.v2.skill.plugins.repository import files_digest, skill_error
from sagents.v2.skill.plugins.sandbox import SandboxSkillWorkspace


_locks: WeakValueDictionary = WeakValueDictionary()
_users: dict[tuple, dict[object, str]] = {}


def _hashes(files):
    return {
        path: hashlib.sha256(content).hexdigest() for path, content in files.items()
    }


class _StableSkillWorkspace(SandboxSkillWorkspace):
    refresh_on_load = True

    def __init__(
        self, sandbox, issuer, *, max_files=2000, max_total_bytes=64 * 1024**2
    ):
        super().__init__(sandbox, issuer)
        self.max_files, self.max_total_bytes = max_files, max_total_bytes
        self._identity = object()
        self._leased = set()

    def _key(self, destination):
        return (
            self.sandbox.ref.tenant_id,
            getattr(self.sandbox, "workspace_identity", self.sandbox.ref.sandbox_id),
            destination,
        )

    def _lock_for(self, destination):
        return _locks.setdefault(self._key(destination), asyncio.Lock())

    def _claim(self, destination, content_hash, *, changing=False):
        owners = _users.get(self._key(destination), {})
        if any(
            owner is not self._identity and (changing or value != content_hash)
            for owner, value in owners.items()
        ):
            raise skill_error(
                "skill.workspace_in_use",
                "Another active Run is using this Skill; synchronize after it releases the workspace",
            )
        _users.setdefault(self._key(destination), {})[self._identity] = content_hash
        self._leased.add(self._key(destination))

    async def close(self):
        for key in self._leased:
            owners = _users.get(key, {})
            owners.pop(self._identity, None)
            if not owners:
                _users.pop(key, None)
        self._leased.clear()

    def _check(self, bundle):
        if bundle.descriptor.name in {".", "..", ".catalog"}:
            raise skill_error(
                "skill.invalid_name", "Skill name is not a safe directory name"
            )
        paths = set(bundle.files)
        if any(
            posixpath.dirname(path) in paths
            or any(parent in paths for parent in _parents(path))
            for path in paths
        ):
            raise skill_error(
                "skill.invalid_paths",
                "Skill contains overlapping file and directory paths",
            )
        if (
            len(paths) > self.max_files
            or sum(map(len, bundle.files.values())) > self.max_total_bytes
        ):
            raise skill_error(
                "skill.bundle_too_large", "Skill exceeds workspace limits"
            )

    def _catalog(self, destination):
        return posixpath.join(
            posixpath.dirname(destination), ".catalog", posixpath.basename(destination)
        )

    async def _read(self, path, run_id):
        return await self.sandbox.filesystem.read_bytes(
            path, **self._authorization(FileOperation.READ, path, run_id)
        )

    async def _optional(self, path, run_id):
        try:
            return await self._read(path, run_id)
        except FileNotFoundError:
            return None

    async def _write(self, path, content, run_id):
        current = await self._optional(path, run_id)
        if current == content:
            return
        operation = FileOperation.CREATE if current is None else FileOperation.WRITE
        await self.sandbox.filesystem.write_bytes(
            path, content, **self._authorization(operation, path, run_id)
        )

    async def _delete(self, path, run_id):
        try:
            await self.sandbox.filesystem.delete(
                path, **self._authorization(FileOperation.DELETE, path, run_id)
            )
        except FileNotFoundError:
            pass

    async def _tree(self, root, run_id):
        root = self.sandbox.filesystem.normalize_path(root)
        try:
            entries = await self.sandbox.filesystem.list_paths(
                root, **self._authorization(FileOperation.LIST, root, run_id)
            )
        except (FileNotFoundError, NotADirectoryError):
            return {}, ()
        files, directories, total = {}, [], 0
        for entry in entries:
            path = self.sandbox.filesystem.normalize_path(entry.path)
            relative = posixpath.relpath(path, root)
            if relative in {".", ".."} or relative.startswith("../"):
                raise skill_error(
                    "skill.workspace_invalid", "Skill file escapes its directory"
                )
            if entry.is_directory:
                directories.append(path)
            elif entry.is_file:
                if (
                    len(files) >= self.max_files
                    or total + entry.size > self.max_total_bytes
                ):
                    raise skill_error(
                        "skill.bundle_too_large",
                        "Skill directory exceeds workspace limits",
                    )
                content = await self._read(path, run_id)
                total += len(content)
                if total > self.max_total_bytes:
                    raise skill_error(
                        "skill.bundle_too_large",
                        "Skill directory exceeds workspace limits",
                    )
                files[relative] = content
        return files, tuple(directories)

    async def _state(self, destination, run_id):
        data = await self._optional(self._catalog(destination) + "/state.json", run_id)
        if data is None:
            return None
        try:
            state = json.loads(data)
            if state["name"] != posixpath.basename(destination) or not isinstance(
                state["files"], dict
            ):
                raise ValueError("invalid Skill state")
            for mapping in (state["files"], state.get("pending_files", {})):
                if not isinstance(mapping, dict) or not all(
                    isinstance(k, str) and isinstance(v, str)
                    for k, v in mapping.items()
                ):
                    raise ValueError("invalid file hashes")
            return state
        except (ValueError, KeyError, TypeError) as exc:
            raise skill_error(
                "skill.workspace_state_invalid",
                "Skill tracking metadata is invalid; existing files were preserved",
            ) from exc

    async def _save_state(self, destination, state, run_id):
        await self._write(
            self._catalog(destination) + "/state.json",
            json.dumps(state, sort_keys=True, separators=(",", ":")).encode(),
            run_id,
        )

    async def reattach(self, loaded, bundle, *, run_id, destination):
        resolved = await self.resolve_bundle(
            bundle, run_id=run_id, destination=destination
        )
        if (
            resolved.content_hash != loaded.content_hash
            # LoadedSkill inherits StrictModel's whitespace normalization.
            # Compare the same representation on recovery; the bundle hash
            # above still verifies every original byte, including whitespace.
            or resolved.files["SKILL.md"].decode("utf-8").strip() != loaded.instructions.strip()
        ):
            raise skill_error(
                "skill.restore_version_changed",
                "Accepted Skill contents are unavailable; do not replace them while restoring a checkpoint",
            )
        state = await self._state(destination, run_id)
        if (
            getattr(self, "manager_authoritative", False)
            and state is not None
            and state.get("content_hash") != loaded.content_hash
        ):
            raise skill_error(
                "skill.restore_version_changed",
                "The shared Skill directory has advanced; use an isolated workspace to restore this version",
            )
        path = await self.materialize(resolved, run_id=run_id, destination=destination)
        return loaded.model_copy(update={"workspace_path": path})


def _parents(path):
    parent = posixpath.dirname(path)
    while parent:
        yield parent
        parent = posixpath.dirname(parent)


class AutoSyncSkillWorkspace(_StableSkillWorkspace):
    manager_authoritative = True
    plugin_id = "sage.skill.workspace.auto-sync"
    name = "Manager-authoritative Skill synchronization"
    description = "Archive Agent edits, then synchronize the stable Skill directory to the manager's selected contents."

    async def resolve_bundle(self, bundle, *, run_id, destination):
        return bundle

    async def _archive(self, actual, destination, state, run_id, changed_paths):
        digest = files_digest(actual).split(":", 1)[1]
        root = self._catalog(destination) + "/agent-edits/" + digest
        changes = {
            path: content
            for path, content in actual.items()
            if state is None or path in changed_paths
        }
        for path, content in changes.items():
            await self._write(root + "/files/" + path, content, run_id)
        record = {
            "name": posixpath.basename(destination),
            "run_id": run_id,
            "base_hash": state.get("content_hash") if state else None,
            "reason": "agent_changes" if state else "untracked_local_changes",
            "files": _hashes(changes),
            "deleted_files": sorted(changed_paths - set(actual)) if state else [],
            "snapshot_hash": digest,
        }
        # The archive is complete before a single active file is replaced.
        await self._write(
            root + "/record.json", json.dumps(record, sort_keys=True).encode(), run_id
        )

    async def materialize(self, bundle, *, run_id, destination):
        self._check(bundle)
        destination = self.sandbox.filesystem.normalize_path(destination)
        source_directory = bundle.descriptor.metadata.get("source_directory")
        if isinstance(source_directory, str):
            try:
                same_directory = (
                    self.sandbox.filesystem.normalize_path(source_directory)
                    == destination
                )
            except (ValueError, PermissionError):
                same_directory = False  # A source outside the sandbox is separate.
            if same_directory:
                raise skill_error(
                    "skill.source_overlaps_workspace",
                    "Auto-sync requires a separate manager source; the source and Agent working directory are the same",
                    ErrorCategory.VALIDATION,
                )
        async with self._lock_for(destination):
            actual, directories = await self._tree(destination, run_id)
            current = _hashes(actual)
            desired = _hashes(bundle.files)
            state = await self._state(destination, run_id)
            self._claim(
                destination, files_digest(bundle.files), changing=current != desired
            )
            baseline = state["files"] if state is not None else desired
            pending = state.get("pending_files") if state else None
            # A prior interrupted synchronization can contain both old and new
            # manager bytes. Do not misclassify those as Agent modifications.
            changed_paths = {
                path
                for path in set(current) | set(baseline) | set(pending or {})
                if current.get(path)
                not in (
                    {baseline.get(path), pending.get(path), desired.get(path)}
                    if pending is not None
                    else {baseline.get(path), desired.get(path)}
                )
            }
            if changed_paths and (state is not None or actual):
                await self._archive(actual, destination, state, run_id, changed_paths)
            next_state = {
                "name": bundle.descriptor.name,
                "content_hash": bundle.content_hash,
                "descriptor": bundle.descriptor.model_dump(mode="json"),
                "files": desired,
            }
            if current != desired:
                await self._save_state(
                    destination,
                    {**next_state, "files": baseline, "pending_files": desired},
                    run_id,
                )
                for relative in actual.keys() - bundle.files.keys():
                    await self._delete(destination + "/" + relative, run_id)
                required_dirs = {
                    parent for relative in bundle.files for parent in _parents(relative)
                }
                for path in sorted(
                    directories, key=lambda value: value.count("/"), reverse=True
                ):
                    if posixpath.relpath(path, destination) not in required_dirs:
                        await self._delete(path, run_id)
                for relative, content in bundle.files.items():
                    await self._write(destination + "/" + relative, content, run_id)
            await self._save_state(destination, next_state, run_id)
        return destination

    async def begin_edit(self, bundle, *, run_id, destination):
        # Agent edits the visible directory. The next load archives any changes
        # and restores manager contents; it never treats edits as a new source.
        return await self.materialize(bundle, run_id=run_id, destination=destination)


class FixedCopySkillWorkspace(_StableSkillWorkspace):
    plugin_id = "sage.skill.workspace.fixed-copy"
    name = "Fixed Skill working copy"
    description = (
        "Create one stable working copy; never synchronize later manager publications."
    )

    async def resolve_bundle(self, bundle, *, run_id, destination):
        destination = self.sandbox.filesystem.normalize_path(destination)
        actual, _ = await self._tree(destination, run_id)
        if not actual:
            return bundle.model_copy(
                update={"content_hash": files_digest(bundle.files)}
            )
        state = await self._state(destination, run_id)
        descriptor = (
            SkillDescriptor.model_validate(state["descriptor"])
            if state
            else bundle.descriptor
        )
        return SkillBundle(
            descriptor=descriptor, files=actual, content_hash=files_digest(actual)
        )

    async def materialize(self, bundle, *, run_id, destination):
        self._check(bundle)
        destination = self.sandbox.filesystem.normalize_path(destination)
        async with self._lock_for(destination):
            actual, _ = await self._tree(destination, run_id)
            if actual:
                self._claim(destination, files_digest(actual))
                return destination
            self._claim(destination, files_digest(bundle.files), changing=True)
            for relative, content in bundle.files.items():
                await self._write(destination + "/" + relative, content, run_id)
            await self._save_state(
                destination,
                {
                    "name": bundle.descriptor.name,
                    "content_hash": bundle.content_hash,
                    "descriptor": bundle.descriptor.model_dump(mode="json"),
                    "files": _hashes(bundle.files),
                },
                run_id,
            )
        return destination

    async def begin_edit(self, bundle, *, run_id, destination):
        return await self.materialize(bundle, run_id=run_id, destination=destination)


class ReadonlyMountSkillWorkspace(_StableSkillWorkspace):
    plugin_id = "sage.skill.workspace.readonly-mount"
    name = "Read-only Skill mount"
    description = "Expose a Skill through a real sandbox read-only mount; require backend support."

    async def resolve_bundle(self, bundle, *, run_id, destination):
        return bundle

    async def materialize(self, bundle, *, run_id, destination):
        self._check(bundle)
        destination = self.sandbox.filesystem.normalize_path(destination)
        mount = getattr(
            getattr(self.sandbox, "skill_mounts", None), "mount_readonly", None
        )
        if not callable(mount):
            raise skill_error(
                "skill.readonly_mount_unsupported",
                "This sandbox does not provide read-only Skill mounts",
                ErrorCategory.VALIDATION,
            )
        async with self._lock_for(destination):
            self._claim(destination, files_digest(bundle.files))
            self._sequence += 1
            intent = OperationIntent(
                operation="skill.mount_readonly",
                run_id=run_id,
                sandbox_id=self.sandbox.ref.sandbox_id,
                tool_call_id=f"skill_mount_{self._sequence}",
                path=destination,
                metadata={
                    "content_hash": bundle.content_hash,
                    "files_hash": files_digest(bundle.files),
                },
            )
            grant = self.issuer.issue(
                ref=self.sandbox.ref,
                intent=intent,
                allowed_operations=frozenset({intent.operation}),
            )
            path = await mount(
                bundle,
                destination=destination,
                run_id=run_id,
                intent=intent,
                grant=grant,
            )
            if self.sandbox.filesystem.normalize_path(path) != destination:
                raise skill_error(
                    "skill.mount_path_invalid",
                    "Mount provider returned a different destination",
                )
        return destination
