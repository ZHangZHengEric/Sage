"""Parser and in-memory applier for Sage's workspace patch tool."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from ..error_codes import ToolErrorCode


BEGIN_PATCH = "*** Begin Patch"
END_PATCH = "*** End Patch"
ADD_FILE = "*** Add File: "
DELETE_FILE = "*** Delete File: "
UPDATE_FILE = "*** Update File: "
MOVE_TO = "*** Move to: "
END_OF_FILE = "*** End of File"
MAX_PATCH_BYTES = 1_000_000
MAX_PATCH_OPERATIONS = 200


class PatchError(ValueError):
    """Structured patch failure that can be returned through the tool protocol."""

    def __init__(
        self,
        message: str,
        *,
        code: str = ToolErrorCode.PARSE_ERROR,
        line_number: Optional[int] = None,
        path: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.line_number = line_number
        self.path = path
        self.hint = hint


@dataclass(frozen=True)
class PatchChunk:
    change_context: Optional[str]
    old_lines: Tuple[str, ...]
    new_lines: Tuple[str, ...]
    lines_added: int
    lines_removed: int
    is_end_of_file: bool = False


@dataclass(frozen=True)
class PatchOperation:
    action: str
    path: str
    line_number: int
    content: Optional[str] = None
    chunks: Tuple[PatchChunk, ...] = ()
    move_path: Optional[str] = None


def _normalize_patch_path(raw_path: str, line_number: int) -> str:
    path = raw_path.strip().replace("\\", "/")
    if not path or "\x00" in path or "\n" in path or "\r" in path:
        raise PatchError(
            "Patch paths must be non-empty text paths",
            line_number=line_number,
        )
    if path.startswith(("/", "~/")) or re.match(r"^[A-Za-z]:", path):
        raise PatchError(
            f"Patch path must be relative to the workspace: {raw_path}",
            code=ToolErrorCode.INVALID_ARGUMENT,
            line_number=line_number,
            path=raw_path,
            hint="Use a workspace-relative path such as src/module.py.",
        )

    normalized = posixpath.normpath(path)
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    windows_parts = [part.rstrip(" .") for part in parts]
    if (
        normalized in {"", ".", ".."}
        or ".." in parts
        or any(part in {"", ".", ".."} for part in windows_parts)
    ):
        raise PatchError(
            f"Patch path escapes the workspace: {raw_path}",
            code=ToolErrorCode.PERMISSION_DENIED,
            line_number=line_number,
            path=raw_path,
        )
    if any(part.split(":", 1)[0].rstrip(" .").casefold() == ".git" for part in parts):
        raise PatchError(
            f"apply_patch cannot modify Git metadata: {raw_path}",
            code=ToolErrorCode.PERMISSION_DENIED,
            line_number=line_number,
            path=raw_path,
            hint="Use normal Git commands for repository metadata changes.",
        )
    return "/".join(parts)


def _is_operation_boundary(line: str) -> bool:
    return line == END_PATCH or line.startswith((ADD_FILE, DELETE_FILE, UPDATE_FILE))


def _parse_add_file(lines: Sequence[str], index: int) -> Tuple[PatchOperation, int]:
    line_number = index + 1
    path = _normalize_patch_path(lines[index][len(ADD_FILE) :], line_number)
    index += 1
    content_lines: List[str] = []
    while index < len(lines) and not _is_operation_boundary(lines[index]):
        line = lines[index]
        if not line.startswith("+"):
            raise PatchError(
                "Every line in an Add File block must start with '+'",
                line_number=index + 1,
                path=path,
            )
        content_lines.append(line[1:])
        index += 1
    if not content_lines:
        raise PatchError(
            "Add File requires at least one '+' content line",
            line_number=line_number,
            path=path,
        )
    return (
        PatchOperation(
            action="add",
            path=path,
            line_number=line_number,
            content="\n".join(content_lines) + "\n",
        ),
        index,
    )


def _finish_chunk(
    chunks: List[PatchChunk],
    context: Optional[str],
    old_lines: List[str],
    new_lines: List[str],
    lines_added: int,
    lines_removed: int,
    is_end_of_file: bool,
    *,
    line_number: int,
    path: str,
) -> None:
    if not old_lines and not new_lines:
        raise PatchError(
            "Update hunk must contain at least one context, addition, or deletion line",
            line_number=line_number,
            path=path,
        )
    chunks.append(
        PatchChunk(
            change_context=context,
            old_lines=tuple(old_lines),
            new_lines=tuple(new_lines),
            lines_added=lines_added,
            lines_removed=lines_removed,
            is_end_of_file=is_end_of_file,
        )
    )


def _parse_update_file(lines: Sequence[str], index: int) -> Tuple[PatchOperation, int]:
    line_number = index + 1
    path = _normalize_patch_path(lines[index][len(UPDATE_FILE) :], line_number)
    index += 1

    move_path: Optional[str] = None
    if index < len(lines) and lines[index].startswith(MOVE_TO):
        move_path = _normalize_patch_path(lines[index][len(MOVE_TO) :], index + 1)
        if move_path == path:
            raise PatchError(
                "Move destination must differ from the source path",
                code=ToolErrorCode.INVALID_ARGUMENT,
                line_number=index + 1,
                path=path,
            )
        index += 1

    chunks: List[PatchChunk] = []
    context: Optional[str] = None
    old_lines: List[str] = []
    new_lines: List[str] = []
    lines_added = 0
    lines_removed = 0
    chunk_line = index + 1
    is_end_of_file = False

    def flush_chunk() -> None:
        nonlocal context, old_lines, new_lines, lines_added, lines_removed
        nonlocal is_end_of_file, chunk_line
        if context is None and not old_lines and not new_lines:
            return
        _finish_chunk(
            chunks,
            context,
            old_lines,
            new_lines,
            lines_added,
            lines_removed,
            is_end_of_file,
            line_number=chunk_line,
            path=path,
        )
        context = None
        old_lines = []
        new_lines = []
        lines_added = 0
        lines_removed = 0
        is_end_of_file = False

    while index < len(lines) and not _is_operation_boundary(lines[index]):
        line = lines[index]
        if line == "@@" or line.startswith("@@ "):
            flush_chunk()
            context = line[3:] if line.startswith("@@ ") else None
            chunk_line = index + 1
            index += 1
            continue
        if line == END_OF_FILE:
            if context is None and not old_lines and not new_lines:
                raise PatchError(
                    "End of File must follow update hunk lines",
                    line_number=index + 1,
                    path=path,
                )
            is_end_of_file = True
            index += 1
            while index < len(lines) and not lines[index].strip():
                index += 1
            if index < len(lines) and not _is_operation_boundary(lines[index]):
                raise PatchError(
                    "End of File must be the final line in an Update File block",
                    line_number=index + 1,
                    path=path,
                )
            break
        if line.startswith(MOVE_TO):
            raise PatchError(
                "Move to must appear before update hunks",
                line_number=index + 1,
                path=path,
            )
        if line == "":
            old_lines.append("")
            new_lines.append("")
        elif line.startswith(" "):
            old_lines.append(line[1:])
            new_lines.append(line[1:])
        elif line.startswith("-"):
            old_lines.append(line[1:])
            lines_removed += 1
        elif line.startswith("+"):
            new_lines.append(line[1:])
            lines_added += 1
        else:
            raise PatchError(
                "Update lines must start with ' ', '+', '-', or '@@'",
                line_number=index + 1,
                path=path,
            )
        index += 1

    flush_chunk()
    if not chunks and move_path is None:
        raise PatchError(
            "Update File requires at least one hunk or a Move to destination",
            line_number=line_number,
            path=path,
        )
    return (
        PatchOperation(
            action="update",
            path=path,
            line_number=line_number,
            chunks=tuple(chunks),
            move_path=move_path,
        ),
        index,
    )


def _validate_unique_paths(operations: Sequence[PatchOperation]) -> None:
    touched: dict[str, PatchOperation] = {}
    for operation in operations:
        for path in (operation.path, operation.move_path):
            if path is None:
                continue
            previous = touched.get(path)
            if previous is not None:
                raise PatchError(
                    f"Patch modifies the same path more than once: {path}",
                    code=ToolErrorCode.PRECONDITION_FAILED,
                    line_number=operation.line_number,
                    path=path,
                    hint="Combine changes to one path into a single patch operation.",
                )
            touched[path] = operation


def parse_patch(patch: str) -> Tuple[PatchOperation, ...]:
    """Parse Sage's structured patch grammar into validated operations."""

    if not isinstance(patch, str) or not patch.strip():
        raise PatchError("patch must be a non-empty string")
    try:
        patch_size = len(patch.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise PatchError(
            "patch must contain valid UTF-8 text",
            code=ToolErrorCode.INVALID_ARGUMENT,
        ) from exc
    if patch_size > MAX_PATCH_BYTES:
        raise PatchError(
            f"Patch is too large ({patch_size} bytes; limit {MAX_PATCH_BYTES})",
            code=ToolErrorCode.INVALID_ARGUMENT,
        )

    normalized = patch.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or lines[0] != BEGIN_PATCH:
        raise PatchError(
            f"The first patch line must be '{BEGIN_PATCH}'",
            line_number=1,
        )

    operations: List[PatchOperation] = []
    index = 1
    while index < len(lines):
        line = lines[index]
        if line == END_PATCH:
            if index != len(lines) - 1:
                raise PatchError(
                    "No content is allowed after End Patch",
                    line_number=index + 2,
                )
            break
        if line.startswith(ADD_FILE):
            operation, index = _parse_add_file(lines, index)
        elif line.startswith(DELETE_FILE):
            line_number = index + 1
            path = _normalize_patch_path(line[len(DELETE_FILE) :], line_number)
            operation = PatchOperation(
                action="delete", path=path, line_number=line_number
            )
            index += 1
        elif line.startswith(UPDATE_FILE):
            operation, index = _parse_update_file(lines, index)
        else:
            raise PatchError(
                "Expected Add File, Delete File, Update File, or End Patch",
                line_number=index + 1,
            )
        operations.append(operation)
        if len(operations) > MAX_PATCH_OPERATIONS:
            raise PatchError(
                f"Patch contains too many file operations (limit {MAX_PATCH_OPERATIONS})",
                code=ToolErrorCode.INVALID_ARGUMENT,
                line_number=operation.line_number,
                hint="Split the change into smaller patches.",
            )
    else:
        raise PatchError(
            f"The last patch line must be '{END_PATCH}'",
            line_number=len(lines) + 1,
        )

    if not operations:
        raise PatchError("Patch must contain at least one file operation")
    _validate_unique_paths(operations)
    return tuple(operations)


def _detect_newline(content: str) -> str:
    if "\r\n" in content:
        return "\r\n"
    if "\r" in content:
        return "\r"
    return "\n"


def _split_source_lines(content: str) -> Tuple[List[str], str]:
    newline = _detect_newline(content)
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines, newline


def _matching_positions(
    lines: Sequence[str], pattern: Sequence[str], start: int, mode: str
) -> List[int]:
    if not pattern:
        return [min(max(start, 0), len(lines))]
    if len(pattern) > len(lines):
        return []

    def normalize(value: str) -> str:
        if mode == "exact":
            return value
        if mode == "rstrip":
            return value.rstrip()
        return value.strip()

    normalized_pattern = [normalize(line) for line in pattern]
    normalized_lines = [normalize(line) for line in lines]
    positions: List[int] = []
    last_start = len(lines) - len(pattern)
    for index in range(max(0, start), last_start + 1):
        matched = True
        for offset, expected in enumerate(normalized_pattern):
            if normalized_lines[index + offset] != expected:
                matched = False
                break
        if matched:
            positions.append(index)
            if len(positions) == 2:
                break
    return positions


def _find_unique_sequence(
    lines: Sequence[str],
    pattern: Sequence[str],
    start: int,
    *,
    path: str,
    description: str,
    end_of_file: bool = False,
) -> int:
    for mode in ("exact", "rstrip", "strip"):
        if end_of_file and pattern:
            position = len(lines) - len(pattern)
            positions = (
                [position]
                if position >= start
                and _matching_positions(lines, pattern, position, mode) == [position]
                else []
            )
        else:
            positions = _matching_positions(lines, pattern, start, mode)
        if not positions:
            continue
        if len(positions) > 1:
            raise PatchError(
                f"{description} matches multiple locations in {path}",
                code=ToolErrorCode.MULTIPLE_MATCHES,
                path=path,
                hint="Add more unchanged context lines or an '@@ section' anchor.",
            )
        return positions[0]
    expected = "\n".join(pattern)
    raise PatchError(
        f"Failed to find {description} in {path}:\n{expected}",
        code=ToolErrorCode.NO_MATCH,
        path=path,
        hint="Re-read the file and regenerate the patch with current context.",
    )


def apply_update_operation(
    original_content: str, operation: PatchOperation
) -> Tuple[str, int, int]:
    """Apply one parsed update operation entirely in memory."""

    if not operation.chunks and operation.move_path is not None:
        return original_content, 0, 0

    lines, newline = _split_source_lines(original_content)
    cursor = 0
    added = 0
    removed = 0

    for chunk in operation.chunks:
        if chunk.change_context is not None:
            context_index = _find_unique_sequence(
                lines,
                [chunk.change_context],
                cursor,
                path=operation.path,
                description=f"section context '{chunk.change_context}'",
            )
            cursor = context_index + 1

        if chunk.old_lines:
            start = _find_unique_sequence(
                lines,
                chunk.old_lines,
                cursor,
                path=operation.path,
                description="expected hunk lines",
                end_of_file=chunk.is_end_of_file,
            )
        else:
            # A hunk with additions only appends to the file. To insert
            # elsewhere, include unchanged context lines in old_lines.
            start = len(lines)

        lines[start : start + len(chunk.old_lines)] = list(chunk.new_lines)
        cursor = start + len(chunk.new_lines)
        added += chunk.lines_added
        removed += chunk.lines_removed

    new_content = newline.join(lines)
    if lines:
        new_content += newline
    if new_content == original_content and operation.move_path is None:
        raise PatchError(
            f"Patch produced no changes for {operation.path}",
            code=ToolErrorCode.PRECONDITION_FAILED,
            path=operation.path,
            hint="The patch may already be applied; re-read the file before retrying.",
        )
    return new_content, added, removed


def count_content_lines(content: str) -> int:
    if not content:
        return 0
    return len(content.splitlines())


__all__ = [
    "MAX_PATCH_BYTES",
    "MAX_PATCH_OPERATIONS",
    "PatchChunk",
    "PatchError",
    "PatchOperation",
    "apply_update_operation",
    "count_content_lines",
    "parse_patch",
]
