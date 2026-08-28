"""Decorator-backed V2 workspace file and code-search tools."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import posixpath
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from sagents.v2.tool import SideEffectLevel, ToolInvocation, tool
from sagents.v2.tool.plugins.official.runtime import OfficialToolRuntime


class FileSystemTools:
    """Real workspace operations; every public method is a V2 Tool."""

    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime
        self._patch_lock = asyncio.Lock()

    @tool(
        description="Read text file within a line range.",
        side_effect_level=SideEffectLevel.READ,
    )
    async def file_read(
        self,
        file_path: str,
        invocation: ToolInvocation,
        start_line: int = 0,
        end_line: int | None = 400,
        include_line_numbers: bool = True,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id
        content = await self.runtime.read_text(file_path, invocation)
        lines = content.splitlines()
        start = max(0, start_line)
        end = len(lines) if end_line is None else min(len(lines), max(start, end_line))
        selected = lines[start:end]
        if include_line_numbers:
            rendered = "\n".join(
                f"{index + 1:>6}\t{line}"
                for index, line in enumerate(selected, start=start)
            )
        else:
            rendered = "\n".join(selected)
        return {
            "status": "success",
            "file_path": file_path,
            "content": rendered,
            "start_line": start,
            "end_line": end,
            "total_lines": len(lines),
        }

    @tool(
        description="Write text to a file.",
        side_effect_level=SideEffectLevel.WRITE,
        requires_approval=True,
    )
    async def file_write(
        self,
        file_path: str,
        content: str,
        invocation: ToolInvocation,
        mode: Literal["overwrite", "append"] = "overwrite",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id
        await self.runtime.write_text(
            file_path, content, invocation, append=mode == "append"
        )
        return {
            "status": "success",
            "message": f"Wrote {len(content)} characters",
            "file_path": file_path,
            "mode": mode,
        }

    @tool(
        description=(
            "Update one text file with search_replace or inclusive line_range "
            "operations."
        ),
        side_effect_level=SideEffectLevel.WRITE,
        requires_approval=True,
    )
    async def file_update(
        self,
        file_path: str,
        invocation: ToolInvocation,
        operations: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id
        content = await self.runtime.read_text(file_path, invocation)
        summaries: list[dict[str, Any]] = []
        replacements = 0
        for index, operation in enumerate(operations or []):
            mode = operation.get("update_mode")
            replacement = operation.get("replacement")
            if not isinstance(replacement, str):
                raise ValueError(f"operation {index}: replacement must be a string")
            if mode == "line_range":
                start = operation.get("start_line")
                end = operation.get("end_line")
                if not isinstance(start, int) or not isinstance(end, int) or end < start:
                    raise ValueError(f"operation {index}: invalid inclusive line range")
                lines = content.splitlines(keepends=True)
                if start < 0 or end >= len(lines):
                    raise ValueError(f"operation {index}: line range is outside file")
                suffix = "\n" if lines[end].endswith("\n") and replacement else ""
                lines[start : end + 1] = [replacement + suffix]
                content = "".join(lines)
                count = end - start + 1
            elif mode == "search_replace":
                pattern = operation.get("search_pattern")
                if not isinstance(pattern, str) or not pattern:
                    raise ValueError(f"operation {index}: search_pattern is required")
                literal_count = content.count(pattern)
                replace_all = bool(operation.get("replace_all", False))
                if literal_count:
                    if literal_count > 1 and not replace_all:
                        raise ValueError(
                            f"operation {index}: search_pattern matched multiple times"
                        )
                    count = literal_count if replace_all else 1
                    content = content.replace(pattern, replacement, 0 if replace_all else 1)
                else:
                    regex = re.compile(pattern, re.MULTILINE)
                    matches = list(regex.finditer(content))
                    if not matches:
                        raise ValueError(f"operation {index}: search_pattern was not found")
                    if len(matches) > 1 and not replace_all:
                        raise ValueError(
                            f"operation {index}: search_pattern matched multiple times"
                        )
                    content, count = regex.subn(
                        replacement, content, count=0 if replace_all else 1
                    )
            else:
                raise ValueError(
                    f"operation {index}: update_mode must be search_replace or line_range"
                )
            replacements += count
            summaries.append({"index": index, "mode": mode, "replacements": count})
        if not summaries:
            raise ValueError("operations must contain at least one update")
        await self.runtime.write_text(file_path, content, invocation)
        return {
            "status": "success",
            "file_path": file_path,
            "operations": summaries,
            "replacements": replacements,
        }

    @tool(
        description="Apply a structured multi-file patch inside the workspace.",
        side_effect_level=SideEffectLevel.WRITE,
        requires_approval=True,
    )
    async def apply_patch(
        self,
        patch: str,
        invocation: ToolInvocation,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id
        operations = _parse_patch(patch)
        snapshots: dict[str, bytes | None] = {}
        changes: list[dict[str, Any]] = []
        async with self._patch_lock:
            try:
                for operation in operations:
                    source = self.runtime.virtual_path(operation["path"])
                    target = self.runtime.virtual_path(
                        operation.get("move_to") or operation["path"]
                    )
                    for value in {source, target}:
                        if value not in snapshots:
                            snapshots[value] = (
                                await self.runtime.read_bytes(value, invocation)
                                if await self.runtime.exists(value, invocation)
                                else None
                            )
                    action = operation["action"]
                    if action == "add":
                        if await self.runtime.exists(source, invocation):
                            raise FileExistsError(operation["path"])
                        await self.runtime.write_text(
                            operation["path"], operation["content"], invocation
                        )
                    elif action == "delete":
                        await self.runtime.delete_file(operation["path"], invocation)
                    else:
                        original = await self.runtime.read_text(
                            operation["path"], invocation
                        )
                        updated = _apply_hunks(original, operation["hunks"])
                        destination = operation.get("move_to") or operation["path"]
                        await self.runtime.write_text(destination, updated, invocation)
                        if destination != operation["path"]:
                            await self.runtime.delete_file(operation["path"], invocation)
                    changes.append(
                        {
                            "action": action,
                            "path": operation["path"],
                            "move_to": operation.get("move_to"),
                        }
                    )
            except BaseException:
                for path, content in snapshots.items():
                    if content is None:
                        if await self.runtime.exists(path, invocation):
                            await self.runtime.delete_file(path, invocation)
                    else:
                        await self.runtime.write_bytes(path, content, invocation)
                raise
        return {
            "status": "success",
            "success": True,
            "files_changed": len(changes),
            "patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
            "changes": changes,
        }


class CodeSearchTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    @tool(description="Search file content with a regular expression.", side_effect_level=SideEffectLevel.READ)
    async def grep(
        self,
        pattern: str,
        invocation: ToolInvocation,
        path: str | None = None,
        glob: str | None = None,
        type: str | None = None,
        output_mode: Literal["content", "files_with_matches", "count"] = "content",
        case_insensitive: bool = False,
        multiline: bool = False,
        before_lines: int | None = None,
        after_lines: int | None = None,
        context_lines: int | None = None,
        head_limit: int = 200,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id, type
        root = self.runtime.virtual_path(path)
        flags = re.IGNORECASE if case_insensitive else 0
        flags |= re.DOTALL if multiline else 0
        regex = re.compile(pattern, flags)
        before = context_lines if context_lines is not None else before_lines or 0
        after = context_lines if context_lines is not None else after_lines or 0
        matches: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        if await self.runtime.exists(root, invocation):
            root_stat = await self.runtime.stat(root, invocation)
            if root_stat.is_directory:
                files = [
                    value
                    for value in await self.runtime.list_paths(root, invocation)
                    if value.is_file
                ]
            else:
                files = [root_stat]
        else:
            raise FileNotFoundError(root)
        for candidate in files:
            if not candidate.is_file:
                continue
            relative = posixpath.relpath(candidate.path, root)
            if glob and not fnmatch.fnmatch(relative, glob):
                continue
            try:
                text = await self.runtime.read_text(candidate.path, invocation)
            except (UnicodeDecodeError, OSError):
                continue
            if multiline:
                found = list(regex.finditer(text))
                if found:
                    counts[candidate.path] = len(found)
                    for match in found[: max(0, head_limit - len(matches))]:
                        matches.append(
                            {
                                "path": candidate.path,
                                "text": match.group(0),
                            }
                        )
            else:
                lines = text.splitlines()
                indexes = [index for index, line in enumerate(lines) if regex.search(line)]
                if indexes:
                    counts[candidate.path] = len(indexes)
                for index in indexes[: max(0, head_limit - len(matches))]:
                    start = max(0, index - before)
                    end = min(len(lines), index + after + 1)
                    matches.append(
                        {
                            "path": candidate.path,
                            "line": index + 1,
                            "text": "\n".join(lines[start:end]),
                        }
                    )
            if len(matches) >= head_limit:
                break
        if output_mode == "files_with_matches":
            return {"files": sorted(counts)[:head_limit]}
        if output_mode == "count":
            return {"counts": dict(list(sorted(counts.items()))[:head_limit])}
        return {"matches": matches, "truncated": len(matches) >= head_limit}

    @tool(description="Find files matching a glob.", side_effect_level=SideEffectLevel.READ)
    async def glob(
        self,
        pattern: str,
        invocation: ToolInvocation,
        path: str | None = None,
        head_limit: int = 200,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id
        root = self.runtime.virtual_path(path)
        values: list[str] = []
        for candidate in await self.runtime.list_paths(root, invocation):
            relative = posixpath.relpath(candidate.path, root)
            if candidate.is_file and fnmatch.fnmatch(relative, pattern):
                values.append(candidate.path)
                if len(values) >= head_limit:
                    break
        return {"files": values, "truncated": len(values) >= head_limit}

    @tool(description="List a workspace directory tree.", side_effect_level=SideEffectLevel.READ)
    async def list_dir(
        self,
        invocation: ToolInvocation,
        path: str | None = None,
        depth: int = 2,
        max_items_per_dir: int = 50,
        include_hidden: bool = False,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id
        root = self.runtime.virtual_path(path)
        entries: list[dict[str, Any]] = []
        per_parent: dict[str, int] = {}
        for candidate in await self.runtime.list_paths(root, invocation):
            relative = posixpath.relpath(candidate.path, root)
            parts = PurePosixPath(relative).parts
            if len(parts) > max(0, depth):
                continue
            if not include_hidden and any(part.startswith(".") for part in parts):
                continue
            parent = posixpath.dirname(candidate.path)
            count = per_parent.get(parent, 0)
            if count >= max_items_per_dir:
                continue
            per_parent[parent] = count + 1
            entries.append(
                {
                    "path": candidate.path,
                    "type": "directory" if candidate.is_directory else "file",
                    "size": candidate.size if candidate.is_file else None,
                }
            )
        return {"entries": entries}


def _parse_patch(patch: str) -> list[dict[str, Any]]:
    lines = patch.splitlines()
    if not lines or lines[0].strip() != "*** Begin Patch" or lines[-1].strip() != "*** End Patch":
        raise ValueError("patch must be wrapped in Begin Patch and End Patch")
    operations: list[dict[str, Any]] = []
    index = 1
    while index < len(lines) - 1:
        header = lines[index]
        if header.startswith("*** Add File: "):
            operation = {"action": "add", "path": header[14:].strip()}
            index += 1
            content: list[str] = []
            while index < len(lines) - 1 and not lines[index].startswith("*** "):
                if not lines[index].startswith("+"):
                    raise ValueError("Add File content lines must start with '+'")
                content.append(lines[index][1:])
                index += 1
            operation["content"] = "\n".join(content) + "\n"
        elif header.startswith("*** Delete File: "):
            operation = {"action": "delete", "path": header[17:].strip()}
            index += 1
        elif header.startswith("*** Update File: "):
            operation = {"action": "update", "path": header[17:].strip(), "hunks": []}
            index += 1
            if index < len(lines) - 1 and lines[index].startswith("*** Move to: "):
                operation["move_to"] = lines[index][13:].strip()
                index += 1
            current: list[str] = []
            while index < len(lines) - 1 and not lines[index].startswith(
                ("*** Add File: ", "*** Delete File: ", "*** Update File: ")
            ):
                if lines[index].startswith("@@"):
                    if current:
                        operation["hunks"].append(current)
                    current = []
                elif lines[index] != "*** End of File":
                    current.append(lines[index])
                index += 1
            if current:
                operation["hunks"].append(current)
        else:
            raise ValueError(f"invalid patch header: {header}")
        path = PurePosixPath(operation["path"])
        if not operation["path"] or path.is_absolute() or ".." in path.parts:
            raise ValueError("patch paths must be workspace-relative")
        operations.append(operation)
    return operations


def _apply_hunks(original: str, hunks: list[list[str]]) -> str:
    lines = original.splitlines()
    for hunk in hunks:
        old = [line[1:] for line in hunk if line.startswith((" ", "-"))]
        new = [line[1:] for line in hunk if line.startswith((" ", "+"))]
        if not old:
            lines.extend(new)
            continue
        match = next(
            (
                index
                for index in range(0, len(lines) - len(old) + 1)
                if lines[index : index + len(old)] == old
            ),
            None,
        )
        if match is None:
            raise ValueError("patch hunk context was not found")
        lines[match : match + len(old)] = new
    trailing = "\n" if original.endswith("\n") or lines else ""
    return "\n".join(lines) + trailing
