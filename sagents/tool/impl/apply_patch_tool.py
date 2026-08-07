"""Sandbox-aware multi-file patch tool for coding agents."""

from __future__ import annotations

import asyncio
import hashlib
import os
import posixpath
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..error_codes import ToolErrorCode, make_tool_error
from ..tool_base import tool
from ._apply_patch import (
    PatchError,
    PatchOperation,
    apply_update_operation,
    count_content_lines,
    parse_patch,
)
from .file_system_tool import FileSystemTool
from sagents.utils.agent_session_helper import get_session_sandbox
from sagents.utils.lock_manager import lock_manager
from sagents.utils.logger import logger


@dataclass(frozen=True)
class FileSnapshot:
    relative_path: str
    actual_path: str
    exists: bool
    content: Optional[str]


@dataclass(frozen=True)
class PlannedChange:
    action: str
    path: str
    actual_path: str
    old_content: Optional[str]
    new_content: Optional[str]
    move_path: Optional[str] = None
    move_actual_path: Optional[str] = None
    lines_added: int = 0
    lines_removed: int = 0

    @property
    def output_path(self) -> Optional[str]:
        if self.action == "delete":
            return None
        return self.move_path or self.path

    @property
    def output_actual_path(self) -> Optional[str]:
        if self.action == "delete":
            return None
        return self.move_actual_path or self.actual_path


@dataclass
class _CommitJournal:
    """Actual paths this transaction has started and finished mutating."""

    started: Set[str] = field(default_factory=set)
    completed: Set[str] = field(default_factory=set)


class ApplyPatchTool:
    """Apply a preflighted text patch through the active session sandbox."""

    def _get_sandbox(self, session_id: str) -> Any:
        return get_session_sandbox(session_id, log_prefix="ApplyPatchTool")

    @staticmethod
    def _workspace_path(sandbox: Any, relative_path: str) -> str:
        root = str(getattr(sandbox, "workspace_path", "") or "").replace("\\", "/")
        if not root or root == ".":
            return relative_path
        normalized_root = root.rstrip("/") or "/"
        return posixpath.join(normalized_root, relative_path)

    @staticmethod
    def _canonical_host_identity(path: str) -> str:
        return os.path.normcase(
            os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))
        )

    @classmethod
    def _host_workspace_identity(cls, sandbox: Any) -> Optional[str]:
        """Resolve the host directory that actually backs the workspace.

        Local/Passthrough providers report the virtual workspace path as
        ``host_workspace_path``, so the volume mount containing the workspace is
        the canonical identity: providers mounting one host directory at
        different virtual roots must share a lock, while unrelated host
        directories mounted at the same virtual root must not.
        """
        host_workspace = getattr(sandbox, "host_workspace_path", None)
        if not host_workspace:
            return None
        workspace = str(getattr(sandbox, "workspace_path", "") or "") or str(
            host_workspace
        )
        normalized_workspace = workspace.replace("\\", "/").rstrip("/") or "/"
        best_mount: Optional[Tuple[str, str]] = None
        for mount in getattr(sandbox, "volume_mounts", None) or []:
            mount_path = str(getattr(mount, "mount_path", "") or "")
            host_path = str(getattr(mount, "host_path", "") or "")
            if not mount_path or not host_path:
                continue
            normalized_mount = mount_path.replace("\\", "/").rstrip("/") or "/"
            if normalized_mount == "/":
                matches = normalized_workspace.startswith("/")
            else:
                matches = normalized_workspace == normalized_mount or (
                    normalized_workspace.startswith(normalized_mount + "/")
                )
            if matches and (
                best_mount is None or len(normalized_mount) > len(best_mount[0])
            ):
                best_mount = (normalized_mount, host_path)
        if best_mount is None:
            return cls._canonical_host_identity(str(host_workspace))
        normalized_mount, host_path = best_mount
        remainder = normalized_workspace[len(normalized_mount) :].strip("/")
        if remainder:
            host_path = os.path.join(host_path, *remainder.split("/"))
        return cls._canonical_host_identity(host_path)

    @classmethod
    def _workspace_lock_key(cls, sandbox: Any) -> str:
        host_identity = cls._host_workspace_identity(sandbox)
        if host_identity:
            identity = f"host:{host_identity}"
        else:
            sandbox_id = str(getattr(sandbox, "sandbox_id", "") or "")
            workspace = str(getattr(sandbox, "workspace_path", "") or "")
            identity = f"sandbox:{sandbox_id}:{workspace}"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return f"apply_patch:{digest}"

    @staticmethod
    async def _snapshot(
        sandbox: Any, relative_path: str, actual_path: str
    ) -> FileSnapshot:
        try:
            exists = await sandbox.file_exists(actual_path)
            content = (
                await sandbox.read_file(actual_path, encoding="utf-8")
                if exists
                else None
            )
            return FileSnapshot(
                relative_path=relative_path,
                actual_path=actual_path,
                exists=exists,
                content=content,
            )
        except PermissionError as exc:
            raise PatchError(
                f"Permission denied while reading {relative_path}: {exc}",
                code=ToolErrorCode.PERMISSION_DENIED,
                path=relative_path,
            ) from exc
        except UnicodeError as exc:
            raise PatchError(
                f"Cannot patch non-UTF-8 text file {relative_path}: {exc}",
                code=ToolErrorCode.UNSUPPORTED,
                path=relative_path,
                hint="apply_patch supports UTF-8 text files only.",
            ) from exc
        except PatchError:
            raise
        except Exception as exc:
            raise PatchError(
                f"Failed to read {relative_path} during patch preflight: {exc}",
                code=ToolErrorCode.SANDBOX_ERROR,
                path=relative_path,
            ) from exc

    async def _preflight(
        self, sandbox: Any, operations: Sequence[PatchOperation]
    ) -> Tuple[List[PlannedChange], Dict[str, FileSnapshot]]:
        relative_paths: List[str] = []
        for operation in operations:
            relative_paths.append(operation.path)
            if operation.move_path:
                relative_paths.append(operation.move_path)

        snapshots: Dict[str, FileSnapshot] = {}
        for relative_path in relative_paths:
            actual_path = self._workspace_path(sandbox, relative_path)
            snapshots[relative_path] = await self._snapshot(
                sandbox, relative_path, actual_path
            )

        plan: List[PlannedChange] = []
        for operation in operations:
            source = snapshots[operation.path]
            if operation.action == "add":
                if source.exists:
                    raise PatchError(
                        f"Cannot add {operation.path}: the file already exists",
                        code=ToolErrorCode.PRECONDITION_FAILED,
                        line_number=operation.line_number,
                        path=operation.path,
                        hint="Use Update File for an existing path.",
                    )
                content = operation.content or ""
                plan.append(
                    PlannedChange(
                        action="add",
                        path=operation.path,
                        actual_path=source.actual_path,
                        old_content=None,
                        new_content=content,
                        lines_added=count_content_lines(content),
                    )
                )
                continue

            if not source.exists or source.content is None:
                raise PatchError(
                    f"Cannot {operation.action} {operation.path}: the file does not exist",
                    code=ToolErrorCode.NOT_FOUND,
                    line_number=operation.line_number,
                    path=operation.path,
                )

            if operation.action == "delete":
                plan.append(
                    PlannedChange(
                        action="delete",
                        path=operation.path,
                        actual_path=source.actual_path,
                        old_content=source.content,
                        new_content=None,
                        lines_removed=count_content_lines(source.content),
                    )
                )
                continue

            if operation.action != "update":
                raise PatchError(
                    f"Unsupported patch action: {operation.action}",
                    code=ToolErrorCode.UNSUPPORTED,
                    line_number=operation.line_number,
                    path=operation.path,
                )

            new_content, lines_added, lines_removed = apply_update_operation(
                source.content, operation
            )
            move_actual_path = None
            if operation.move_path:
                destination = snapshots[operation.move_path]
                if destination.exists:
                    raise PatchError(
                        f"Cannot move {operation.path} to {operation.move_path}: destination exists",
                        code=ToolErrorCode.PRECONDITION_FAILED,
                        line_number=operation.line_number,
                        path=operation.move_path,
                    )
                move_actual_path = destination.actual_path

            plan.append(
                PlannedChange(
                    action="move" if operation.move_path else "update",
                    path=operation.path,
                    actual_path=source.actual_path,
                    old_content=source.content,
                    new_content=new_content,
                    move_path=operation.move_path,
                    move_actual_path=move_actual_path,
                    lines_added=lines_added,
                    lines_removed=lines_removed,
                )
            )

        return plan, snapshots

    async def _verify_preconditions(
        self, sandbox: Any, snapshots: Dict[str, FileSnapshot]
    ) -> None:
        for expected in snapshots.values():
            current = await self._snapshot(
                sandbox, expected.relative_path, expected.actual_path
            )
            if current.exists != expected.exists or current.content != expected.content:
                raise PatchError(
                    f"File changed during patch preflight: {expected.relative_path}",
                    code=ToolErrorCode.PRECONDITION_FAILED,
                    path=expected.relative_path,
                    hint="Re-read the affected files and regenerate the patch.",
                )

    @staticmethod
    async def _write_file(sandbox: Any, path: str, content: str) -> None:
        parent = posixpath.dirname(path.replace("\\", "/"))
        if parent:
            await sandbox.ensure_directory(parent)
        await sandbox.write_file(path, content, encoding="utf-8", mode="overwrite")

    async def _commit(
        self,
        sandbox: Any,
        plan: Sequence[PlannedChange],
        journal: Optional[_CommitJournal] = None,
    ) -> None:
        writes: List[Tuple[str, str]] = []
        deletes: List[str] = []
        for change in plan:
            if change.action == "delete":
                deletes.append(change.actual_path)
                continue
            output_path = change.output_actual_path
            if output_path is None or change.new_content is None:
                raise RuntimeError(
                    f"Invalid planned {change.action} change for {change.path}"
                )
            writes.append((output_path, change.new_content))
            if change.action == "move":
                deletes.append(change.actual_path)

        # Complete every content write before destructive deletes. This keeps the
        # common failure path recoverable without recreating source files.
        for path, content in writes:
            if journal is not None:
                journal.started.add(path)
            await self._write_file(sandbox, path, content)
            if journal is not None:
                journal.completed.add(path)
        for path in deletes:
            if journal is not None:
                journal.started.add(path)
            await sandbox.delete_file(path)
            if journal is not None:
                journal.completed.add(path)

    async def _commit_and_verify(
        self,
        sandbox: Any,
        plan: Sequence[PlannedChange],
        journal: _CommitJournal,
    ) -> None:
        await self._commit(sandbox, plan, journal=journal)
        await self._verify_commit(sandbox, plan)

    @staticmethod
    async def _settle(task: "asyncio.Future[Any]") -> bool:
        """Wait for ``task`` to finish even while this coroutine is cancelled.

        The task is shielded so a cancelled tool call never interrupts an
        in-flight sandbox mutation; rollback therefore always observes settled
        file states. Returns True when a cancellation request arrived while
        waiting. The task's result or exception stays on the task object.
        """
        interrupted = False
        while True:
            try:
                await asyncio.shield(task)
                return interrupted
            except asyncio.CancelledError:
                if task.done():
                    return True
                interrupted = True
            except BaseException:
                return interrupted

    @staticmethod
    async def _verify_commit(sandbox: Any, plan: Sequence[PlannedChange]) -> None:
        for change in plan:
            output_path = change.output_actual_path
            if output_path is not None and change.new_content is not None:
                if not await sandbox.file_exists(output_path):
                    raise OSError(
                        f"Patched file is missing after commit: {change.output_path}"
                    )
                committed_content = await sandbox.read_file(
                    output_path, encoding="utf-8"
                )
                if committed_content != change.new_content:
                    raise OSError(
                        f"Patched file content verification failed: {change.output_path}"
                    )
            if change.action in {"delete", "move"} and await sandbox.file_exists(
                change.actual_path
            ):
                raise OSError(
                    f"Source file still exists after {change.action}: {change.path}"
                )

    @staticmethod
    def _planned_file_states(
        plan: Sequence[PlannedChange],
    ) -> Dict[str, FileSnapshot]:
        states: Dict[str, FileSnapshot] = {}
        for change in plan:
            if change.action in {"delete", "move"}:
                states[change.path] = FileSnapshot(
                    relative_path=change.path,
                    actual_path=change.actual_path,
                    exists=False,
                    content=None,
                )
            output_path = change.output_path
            output_actual_path = change.output_actual_path
            if (
                output_path is not None
                and output_actual_path is not None
                and change.new_content is not None
            ):
                states[output_path] = FileSnapshot(
                    relative_path=output_path,
                    actual_path=output_actual_path,
                    exists=True,
                    content=change.new_content,
                )
        return states

    @staticmethod
    def _same_file_state(left: FileSnapshot, right: FileSnapshot) -> bool:
        return left.exists == right.exists and (
            not left.exists or left.content == right.content
        )

    async def _rollback(
        self,
        sandbox: Any,
        snapshots: Dict[str, FileSnapshot],
        plan: Sequence[PlannedChange],
        journal: Optional[_CommitJournal] = None,
    ) -> Dict[str, Any]:
        errors: List[Dict[str, str]] = []
        planned_states = self._planned_file_states(plan)
        for snapshot in reversed(list(snapshots.values())):
            try:
                current = await self._snapshot(
                    sandbox, snapshot.relative_path, snapshot.actual_path
                )
                if self._same_file_state(current, snapshot):
                    continue

                planned = planned_states.get(snapshot.relative_path)
                planned_matches = planned is not None and self._same_file_state(
                    current, planned
                )
                # A mutation this transaction started but never completed can
                # leave content matching neither the snapshot nor the planned
                # state. That torn write is ours, not an external edit, so it
                # must be restored.
                interrupted_write = (
                    journal is not None
                    and snapshot.actual_path in journal.started
                    and snapshot.actual_path not in journal.completed
                )
                if not planned_matches and not interrupted_write:
                    raise OSError(
                        "Rollback skipped because the path changed outside this patch "
                        f"transaction: {snapshot.relative_path}"
                    )

                if snapshot.exists:
                    if snapshot.content is None:
                        raise OSError(
                            f"Missing rollback snapshot content: {snapshot.relative_path}"
                        )
                    await self._write_file(
                        sandbox, snapshot.actual_path, snapshot.content
                    )
                elif current.exists:
                    await sandbox.delete_file(snapshot.actual_path)

                restored_exists = await sandbox.file_exists(snapshot.actual_path)
                if snapshot.exists:
                    if not restored_exists:
                        raise OSError(
                            f"Rollback did not restore file: {snapshot.relative_path}"
                        )
                    restored_content = await sandbox.read_file(
                        snapshot.actual_path, encoding="utf-8"
                    )
                    if restored_content != snapshot.content:
                        raise OSError(
                            f"Rollback content verification failed: {snapshot.relative_path}"
                        )
                elif restored_exists:
                    raise OSError(
                        f"Rollback did not remove file: {snapshot.relative_path}"
                    )
            except Exception as exc:
                errors.append({"path": snapshot.relative_path, "error": str(exc)})
        return {
            "attempted": True,
            "succeeded": not errors,
            "errors": errors,
        }

    @staticmethod
    def _patch_error_payload(error: PatchError) -> Dict[str, Any]:
        extras: Dict[str, Any] = {}
        if error.line_number is not None:
            extras["line_number"] = error.line_number
        if error.path is not None:
            extras["file_path"] = error.path
        return make_tool_error(
            error.code,
            str(error),
            hint=error.hint,
            **extras,
        )

    @staticmethod
    def _validation_result(path: str, content: str) -> Dict[str, Any]:
        try:
            return FileSystemTool._build_validation_result(path, content)
        except Exception as exc:
            message = f"Content validation could not run: {exc}"
            logger.warning(f"ApplyPatchTool: {message} ({path})")
            return {
                "enabled": False,
                "skipped": True,
                "passed": False,
                "status": "warning",
                "validator": None,
                "file_extension": posixpath.splitext(path)[1].lower(),
                "message": message,
                "warnings": [message],
                "errors": [],
            }

    @staticmethod
    def _change_result(change: PlannedChange) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "action": change.action,
            "path": change.path,
            "lines_added": change.lines_added,
            "lines_removed": change.lines_removed,
        }
        if change.move_path:
            result["move_path"] = change.move_path
            result["warning"] = (
                "Text content is preserved, but file mode metadata may not be preserved by every sandbox provider."
            )
        if change.output_path and change.new_content is not None:
            result["validation"] = ApplyPatchTool._validation_result(
                change.output_path, change.new_content
            )
        return result

    @tool(
        explicit_only=True,
        description_i18n={
            "zh": "一次性对工作空间中的一个或多个文本文件应用结构化补丁。所有操作会先预检；写入失败时会尽力回滚。支持 Add File、Update File、Delete File 和 Move to。",
            "en": "Apply one structured patch to one or more text files in the workspace. All operations are preflighted before writing, and failed writes trigger best-effort rollback. Supports Add File, Update File, Delete File, and Move to.",
        },
        param_description_i18n={
            "patch": {
                "zh": "结构化补丁文本。使用 *** Begin Patch / *** End Patch 包裹 Add File、Update File、Delete File；移动时在 Update File 后添加 *** Move to。更新行必须以空格、+ 或 - 开头。无上下文行的纯新增 hunk 会追加到文件末尾。路径必须相对当前工作空间。",
                "en": "Structured patch text wrapped in *** Begin Patch / *** End Patch with Add File, Update File, or Delete File blocks; put *** Move to after Update File to move a file. Update lines must start with a space, +, or -. A pure-addition hunk with no context lines appends to the end of the file. Paths must be workspace-relative.",
            },
            "session_id": {
                "zh": "会话ID（必填，自动注入）",
                "en": "Session ID (required, auto-injected)",
            },
        },
        param_schema={
            "patch": {
                "type": "string",
                "description": (
                    "Patch text using *** Begin Patch / *** End Patch and one or more "
                    "*** Add File, *** Update File, or *** Delete File blocks. Use "
                    "*** Move to immediately after Update File for moves. Update lines "
                    "start with space, +, or -. Pure additions without context append "
                    "to the file. Paths are workspace-relative."
                ),
            },
            "session_id": {"type": "string", "description": "Session ID"},
        },
        return_data={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "success": {"type": "boolean"},
                "message": {"type": "string"},
                "files_changed": {"type": "integer"},
                "patch_sha256": {"type": "string"},
                "changes": {"type": "array", "items": {"type": "object"}},
                "rollback": {"type": "object"},
            },
        },
    )
    async def apply_patch(
        self,
        patch: str,
        session_id: str = None,  # pyright: ignore[reportArgumentType]
    ) -> Dict[str, Any]:
        """Apply a workspace-relative multi-file text patch.

        Args:
            patch: Patch text wrapped in Begin Patch / End Patch markers.
            session_id: Active session ID, injected by the runtime.

        Returns:
            Structured patch result with per-file change summaries.
        """
        if not session_id:
            raise ValueError("ApplyPatchTool: session_id is required")

        try:
            operations = parse_patch(patch)
        except PatchError as error:
            return self._patch_error_payload(error)

        try:
            sandbox = self._get_sandbox(session_id)
        except PermissionError as exc:
            return make_tool_error(ToolErrorCode.PERMISSION_DENIED, str(exc))
        except Exception as exc:
            return make_tool_error(ToolErrorCode.SANDBOX_ERROR, str(exc))

        lock_key = self._workspace_lock_key(sandbox)
        lock = lock_manager.get_lock(lock_key)
        # Keep the keyed lock registered after release. LockManager expires idle
        # locks; deleting it here could split concurrent waiters across two locks.
        async with lock:
            try:
                plan, snapshots = await self._preflight(sandbox, operations)
                await self._verify_preconditions(sandbox, snapshots)
            except PatchError as error:
                return self._patch_error_payload(error)

            # Shield the commit from cancellation so an in-flight write always
            # settles before rollback runs; a cancelled call then either keeps
            # the fully committed state for one instant and restores it, or
            # restores immediately — never a partially written file.
            journal = _CommitJournal()
            commit_task = asyncio.ensure_future(
                self._commit_and_verify(sandbox, plan, journal)
            )
            interrupted = await self._settle(commit_task)
            commit_cancelled = commit_task.cancelled()
            commit_error = None if commit_cancelled else commit_task.exception()

            if interrupted or commit_cancelled or commit_error is not None:
                rollback_task = asyncio.ensure_future(
                    self._rollback(sandbox, snapshots, plan, journal=journal)
                )
                await self._settle(rollback_task)
                rollback_error = rollback_task.exception()
                rollback = (
                    rollback_task.result()
                    if rollback_error is None
                    else {
                        "attempted": True,
                        "succeeded": False,
                        "errors": [{"path": "*", "error": str(rollback_error)}],
                    }
                )
                if interrupted or commit_cancelled:
                    if not rollback["succeeded"]:
                        logger.error(
                            "ApplyPatchTool: rollback after cancellation failed "
                            f"for session {session_id}: {rollback['errors']}"
                        )
                    raise asyncio.CancelledError
                logger.error(
                    f"ApplyPatchTool: commit failed for session {session_id}: {commit_error}"
                )
                code = (
                    ToolErrorCode.PERMISSION_DENIED
                    if isinstance(commit_error, PermissionError)
                    else ToolErrorCode.SANDBOX_ERROR
                )
                return make_tool_error(
                    code,
                    f"Patch commit failed: {commit_error}",
                    rollback=rollback,
                )

            change_results = [self._change_result(change) for change in plan]
            return {
                "success": True,
                "status": "success",
                "message": f"Applied patch to {len(plan)} file operation(s)",
                "files_changed": len(plan),
                "patch_sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                "changes": change_results,
                "rollback": {"attempted": False},
            }


__all__ = ["ApplyPatchTool", "FileSnapshot", "PlannedChange"]
