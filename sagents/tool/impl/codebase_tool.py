#!/usr/bin/env python3
"""Codebase 认知工具集

为 Agent 提供"代码库认知"的一等工具：

- ``grep``：基于 ripgrep 的结构化全文搜索（``rg --json``），rg 缺失时降级到
  ``grep -rn`` 并按宽松解析返回；命中后按 ``head_limit`` 截断并标 ``truncated``。
- ``glob``：按 glob 表达式查找文件，支持 ``**`` 递归匹配，按 mtime 倒序返回；
  实现走沙箱接口避免污染宿主机。
- ``list_dir``：直接复用 ``ISandboxHandle.get_file_tree``，参数透传，默认忽略
  ``.git`` / ``node_modules`` 等噪音目录。

设计目标：让模型在主流程中无需 fallback 到 shell，避免 ``rg --json`` 等输出
污染上下文，并稳定返回结构化诊断。所有操作走沙箱、共享 ``execute_command``，
错误统一走 ``error_codes.make_tool_error``。
"""

from __future__ import annotations

import fnmatch
import json
import os
import shlex
from typing import Any, Dict, List, Optional, Tuple

from ..tool_base import tool
from ..error_codes import ToolErrorCode, make_tool_error
from sagents.utils.logger import logger
from sagents.utils.agent_session_helper import get_session_sandbox as _get_session_sandbox_util


_DEFAULT_IGNORE_PATTERNS: Tuple[str, ...] = (
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    "dist",
    "build",
    ".next",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".idea",
    ".vscode",
)


def _truncate(items: List[Any], head_limit: Optional[int]) -> Tuple[List[Any], bool]:
    if not head_limit or head_limit <= 0 or len(items) <= head_limit:
        return items, False
    return items[:head_limit], True


class CodebaseTool:
    """代码库认知三件套：grep / glob / list_dir。"""

    # ==================== 基础设施 ====================

    def _get_sandbox(self, session_id: str):
        return _get_session_sandbox_util(session_id, log_prefix="CodebaseTool")

    async def _run(self, sandbox: Any, command: str, timeout: int = 60) -> Tuple[int, str, str]:
        """在沙箱中执行命令，返回 (return_code, stdout, stderr)。失败时 return_code=-1。"""
        try:
            result = await sandbox.execute_command(command=command, timeout=timeout)
            return (
                int(getattr(result, "return_code", -1) or 0),
                getattr(result, "stdout", "") or "",
                getattr(result, "stderr", "") or "",
            )
        except Exception as exc:
            logger.warning(f"CodebaseTool: 命令执行失败 cmd={command!r} err={exc}")
            return -1, "", str(exc)

    async def _has_command(self, sandbox: Any, name: str) -> bool:
        if os.name == "nt":
            cmd = f"where {name}"
        else:
            cmd = f"command -v {shlex.quote(name)}"
        rc, out, _ = await self._run(sandbox, cmd, timeout=5)
        return rc == 0 and bool((out or "").strip())

    # ==================== grep ====================

    @staticmethod
    def _build_rg_command(
        pattern: str,
        path: Optional[str],
        glob_filter: Optional[str],
        type_filter: Optional[str],
        case_insensitive: bool,
        multiline: bool,
        before_lines: Optional[int],
        after_lines: Optional[int],
        context_lines: Optional[int],
        files_with_matches: bool,
        count_only: bool,
    ) -> str:
        parts: List[str] = ["rg", "--no-heading"]
        if files_with_matches:
            parts.append("--files-with-matches")
        elif count_only:
            parts.append("--count")
        else:
            parts.append("--json")
            parts.append("--line-number")
            parts.append("--column")
        if case_insensitive:
            parts.append("-i")
        if multiline:
            parts.extend(["-U", "--multiline-dotall"])
        if context_lines and context_lines > 0:
            parts.extend(["-C", str(context_lines)])
        else:
            if before_lines and before_lines > 0:
                parts.extend(["-B", str(before_lines)])
            if after_lines and after_lines > 0:
                parts.extend(["-A", str(after_lines)])
        if glob_filter:
            parts.extend(["--glob", shlex.quote(glob_filter)])
        if type_filter:
            parts.extend(["--type", shlex.quote(type_filter)])
        # pattern 用 -e 显式传入，避免被当成路径
        parts.extend(["-e", shlex.quote(pattern)])
        if path:
            parts.append(shlex.quote(path))
        return " ".join(parts)

    @staticmethod
    def _parse_rg_json(stdout: str, head_limit: int) -> Tuple[List[Dict[str, Any]], bool]:
        """解析 ``rg --json`` 输出，返回结构化 match 列表。

        每个 match 形如 ``{file, line, col, match, before, after}``；
        before/after 仅在带 -B/-A/-C 时填充。
        """
        matches: List[Dict[str, Any]] = []
        truncated = False
        pending_context: Dict[str, List[str]] = {}

        def _take(meta: Dict[str, Any], key: str, sub: str) -> Any:
            d = meta.get(key)
            if isinstance(d, dict):
                return d.get(sub)
            return None

        for raw in stdout.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                evt = json.loads(raw)
            except Exception:
                continue
            etype = evt.get("type")
            data = evt.get("data") or {}
            if etype == "match":
                file_path = _take(data, "path", "text") or ""
                line_no = data.get("line_number")
                lines = _take(data, "lines", "text") or ""
                # rg 的 column 在 submatches[i].start 上（字节偏移，1-based 输出时已经处理）
                col = None
                subs = data.get("submatches") or []
                if subs and isinstance(subs, list):
                    s0 = subs[0] or {}
                    col = (s0.get("start") or 0) + 1
                matched_text_parts: List[str] = []
                for sm in subs:
                    if isinstance(sm, dict):
                        mt = (sm.get("match") or {}).get("text")
                        if isinstance(mt, str):
                            matched_text_parts.append(mt)
                ctx = pending_context.pop(file_path, None) or []
                entry = {
                    "file": file_path,
                    "line": line_no,
                    "col": col,
                    "match": (matched_text_parts[0] if matched_text_parts else lines.rstrip("\n")),
                    "line_text": lines.rstrip("\n"),
                }
                if ctx:
                    entry["context"] = ctx
                matches.append(entry)
                if len(matches) >= head_limit:
                    truncated = True
                    break
            elif etype == "context":
                file_path = _take(data, "path", "text") or ""
                line_no = data.get("line_number")
                lines = _take(data, "lines", "text") or ""
                pending_context.setdefault(file_path, []).append(
                    f"{line_no}: {lines.rstrip('n')}"
                )
        return matches, truncated

    async def _grep_with_rg(
        self,
        sandbox: Any,
        *,
        pattern: str,
        path: Optional[str],
        glob_filter: Optional[str],
        type_filter: Optional[str],
        output_mode: str,
        case_insensitive: bool,
        multiline: bool,
        before_lines: Optional[int],
        after_lines: Optional[int],
        context_lines: Optional[int],
        head_limit: int,
    ) -> Dict[str, Any]:
        files_only = output_mode == "files_with_matches"
        count_only = output_mode == "count"
        cmd = self._build_rg_command(
            pattern=pattern,
            path=path,
            glob_filter=glob_filter,
            type_filter=type_filter,
            case_insensitive=case_insensitive,
            multiline=multiline,
            before_lines=before_lines,
            after_lines=after_lines,
            context_lines=context_lines,
            files_with_matches=files_only,
            count_only=count_only,
        )
        rc, out, err = await self._run(sandbox, cmd, timeout=60)
        # rg: 0=有命中, 1=无命中, 2+=工具错
        if rc not in (0, 1):
            return make_tool_error(
                ToolErrorCode.INTERNAL_ERROR,
                f"ripgrep exited {rc}: {err.strip()[:200]}",
                tool="rg",
            )
        if files_only:
            files = [ln.strip() for ln in out.splitlines() if ln.strip()]
            files, truncated = _truncate(files, head_limit)
            return {
                "success": True,
                "status": "success",
                "tool": "rg",
                "output_mode": "files_with_matches",
                "files": files,
                "count": len(files),
                "truncated": truncated,
            }
        if count_only:
            counts: List[Dict[str, Any]] = []
            for ln in out.splitlines():
                if not ln.strip() or ":" not in ln:
                    continue
                file_part, _, num = ln.rpartition(":")
                try:
                    counts.append({"file": file_part, "matches": int(num)})
                except ValueError:
                    continue
            counts, truncated = _truncate(counts, head_limit)
            return {
                "success": True,
                "status": "success",
                "tool": "rg",
                "output_mode": "count",
                "counts": counts,
                "total": sum(c.get("matches", 0) for c in counts),
                "truncated": truncated,
            }

        matches, truncated = self._parse_rg_json(out, head_limit=head_limit)
        return {
            "success": True,
            "status": "success",
            "tool": "rg",
            "output_mode": "content",
            "matches": matches,
            "count": len(matches),
            "truncated": truncated,
        }

    async def _grep_with_basic(
        self,
        sandbox: Any,
        *,
        pattern: str,
        path: Optional[str],
        case_insensitive: bool,
        head_limit: int,
        output_mode: str,
    ) -> Dict[str, Any]:
        """rg 不可用时的兜底：``grep -rn``。功能子集：仅支持基本搜索 + 行号 + 大小写。"""
        target = path if path else "."
        flags = ["-rnE"]
        if case_insensitive:
            flags.append("-i")
        if output_mode == "files_with_matches":
            flags.append("-l")
        elif output_mode == "count":
            flags.append("-c")
        cmd = f"grep {' '.join(flags)} -e {shlex.quote(pattern)} {shlex.quote(target)}"
        rc, out, err = await self._run(sandbox, cmd, timeout=60)
        # grep: 0=命中, 1=无命中, 2=错误
        if rc not in (0, 1):
            return make_tool_error(
                ToolErrorCode.INTERNAL_ERROR,
                f"grep exited {rc}: {err.strip()[:200]}",
                tool="grep",
            )

        if output_mode == "files_with_matches":
            files = [ln.strip() for ln in out.splitlines() if ln.strip()]
            files, truncated = _truncate(files, head_limit)
            return {
                "success": True,
                "status": "success",
                "tool": "grep",
                "output_mode": "files_with_matches",
                "files": files,
                "count": len(files),
                "truncated": truncated,
            }
        if output_mode == "count":
            counts: List[Dict[str, Any]] = []
            for ln in out.splitlines():
                if not ln.strip() or ":" not in ln:
                    continue
                file_part, _, num = ln.rpartition(":")
                try:
                    n = int(num)
                except ValueError:
                    continue
                if n > 0:
                    counts.append({"file": file_part, "matches": n})
            counts, truncated = _truncate(counts, head_limit)
            return {
                "success": True,
                "status": "success",
                "tool": "grep",
                "output_mode": "count",
                "counts": counts,
                "total": sum(c.get("matches", 0) for c in counts),
                "truncated": truncated,
            }

        matches: List[Dict[str, Any]] = []
        for ln in out.splitlines():
            # 形如 path:line:content
            parts = ln.split(":", 2)
            if len(parts) < 3:
                continue
            file_part, line_no_str, content = parts
            try:
                line_no = int(line_no_str)
            except ValueError:
                continue
            matches.append({
                "file": file_part,
                "line": line_no,
                "col": None,
                "match": content,
                "line_text": content,
            })
            if len(matches) >= head_limit:
                break
        truncated = len(matches) >= head_limit
        return {
            "success": True,
            "status": "success",
            "tool": "grep",
            "output_mode": "content",
            "matches": matches,
            "count": len(matches),
            "truncated": truncated,
            "note": "ripgrep unavailable, fell back to grep with limited features",
        }

    @tool(
        description_i18n={
            "zh": "在沙箱代码库中执行结构化全文搜索（基于 ripgrep；缺失时降级到 grep）。返回结构化匹配 {file,line,col,match}，避免污染上下文。优先使用本工具而不是手写 shell rg。",
            "en": "Run a structured full-text search in the sandboxed codebase (ripgrep-based; falls back to grep when missing). Returns structured matches {file,line,col,match}. Prefer this over hand-written shell rg.",
        },
        param_description_i18n={
            "pattern": {"zh": "正则表达式（默认 PCRE2 风格；ripgrep 缺失时按 ERE 解析）", "en": "Regex pattern (PCRE2-style by default; ERE when falling back to grep)"},
            "path": {"zh": "搜索根路径（虚拟路径），缺省为沙箱工作区根", "en": "Search root path (virtual). Defaults to the sandbox workspace root"},
            "glob": {"zh": "rg --glob 过滤，例如 '**/*.py' 或 '!**/dist/**'", "en": "rg --glob filter, e.g. '**/*.py' or '!**/dist/**'"},
            "type": {"zh": "rg --type 过滤（py/js/ts/...）", "en": "rg --type filter (py/js/ts/...)"},
            "output_mode": {"zh": "输出模式：content（默认，行+上下文）/ files_with_matches / count", "en": "Output mode: content (default, lines+context) / files_with_matches / count"},
            "case_insensitive": {"zh": "等价 rg -i", "en": "Equivalent to rg -i"},
            "multiline": {"zh": "等价 rg -U --multiline-dotall，让 . 跨行", "en": "Equivalent to rg -U --multiline-dotall to let . match newlines"},
            "before_lines": {"zh": "等价 rg -B N", "en": "Equivalent to rg -B N"},
            "after_lines": {"zh": "等价 rg -A N", "en": "Equivalent to rg -A N"},
            "context_lines": {"zh": "等价 rg -C N，与 before/after 互斥优先", "en": "Equivalent to rg -C N; takes precedence over before/after"},
            "head_limit": {"zh": "结果上限（content 模式按 match 计；files/count 模式按条目计），默认 200", "en": "Result cap (matches in content mode; entries in files/count modes). Default 200"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "pattern": {"type": "string", "description": "Regex pattern"},
            "path": {"type": "string", "description": "Search root virtual path"},
            "glob": {"type": "string", "description": "Glob filter, e.g. **/*.py"},
            "type": {"type": "string", "description": "rg --type filter"},
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "default": "content",
            },
            "case_insensitive": {"type": "boolean", "default": False},
            "multiline": {"type": "boolean", "default": False},
            "before_lines": {"type": "integer", "minimum": 0},
            "after_lines": {"type": "integer", "minimum": 0},
            "context_lines": {"type": "integer", "minimum": 0},
            "head_limit": {"type": "integer", "default": 200, "minimum": 1},
            "session_id": {"type": "string", "description": "Session ID"},
        },
    )
    async def grep(
        self,
        pattern: str,
        path: Optional[str] = None,
        glob: Optional[str] = None,
        type: Optional[str] = None,
        output_mode: str = "content",
        case_insensitive: bool = False,
        multiline: bool = False,
        before_lines: Optional[int] = None,
        after_lines: Optional[int] = None,
        context_lines: Optional[int] = None,
        head_limit: int = 200,
        session_id: str = None,
    ) -> Dict[str, Any]:
        if not session_id:
            raise ValueError("CodebaseTool: session_id is required")
        if not isinstance(pattern, str) or not pattern:
            return make_tool_error(
                ToolErrorCode.INVALID_ARGUMENT,
                "pattern 必须是非空字符串",
            )
        if output_mode not in {"content", "files_with_matches", "count"}:
            return make_tool_error(
                ToolErrorCode.INVALID_ARGUMENT,
                "output_mode 必须是 content/files_with_matches/count 之一",
            )
        try:
            sandbox = self._get_sandbox(session_id)
        except Exception as exc:
            return make_tool_error(ToolErrorCode.SANDBOX_ERROR, f"获取沙箱失败: {exc}")

        try:
            if await self._has_command(sandbox, "rg"):
                return await self._grep_with_rg(
                    sandbox,
                    pattern=pattern,
                    path=path,
                    glob_filter=glob,
                    type_filter=type,
                    output_mode=output_mode,
                    case_insensitive=case_insensitive,
                    multiline=multiline,
                    before_lines=before_lines,
                    after_lines=after_lines,
                    context_lines=context_lines,
                    head_limit=head_limit,
                )
            return await self._grep_with_basic(
                sandbox,
                pattern=pattern,
                path=path,
                case_insensitive=case_insensitive,
                head_limit=head_limit,
                output_mode=output_mode,
            )
        except Exception as exc:
            logger.error(f"CodebaseTool.grep: 运行失败: {exc}")
            return make_tool_error(ToolErrorCode.INTERNAL_ERROR, f"grep 失败: {exc}")

    # ==================== glob ====================

    @staticmethod
    def _to_pure_pattern(pattern: str) -> str:
        """规范化 glob：去掉前导 ``./``，使用 POSIX 分隔符。"""
        p = (pattern or "").strip()
        if p.startswith("./"):
            p = p[2:]
        return p.replace("\\", "/")

    @staticmethod
    def _glob_match(rel_path: str, pattern: str) -> bool:
        """支持 ``**`` 的 glob 匹配（基于 fnmatch + 自定义双星处理）。

        - ``**/x`` 匹配任意深度下的 x（含 0 层）。
        - ``a/**/b`` 匹配 a 与 b 之间任意深度。
        - 不命中时再尝试 fnmatch.fnmatch 兜底（兼容简单 ``*.py``）。
        """
        rel = rel_path.replace("\\", "/").lstrip("./")
        pat = pattern.replace("\\", "/").lstrip("./")
        # 直接 fnmatch（处理 *.py / dir/*.py 这类）
        if fnmatch.fnmatchcase(rel, pat):
            return True
        # ** 展开：转成正则
        import re as _re
        regex_parts: List[str] = []
        i = 0
        while i < len(pat):
            ch = pat[i]
            if ch == "*" and i + 1 < len(pat) and pat[i + 1] == "*":
                # ** : 跨目录
                if i + 2 < len(pat) and pat[i + 2] == "/":
                    regex_parts.append("(?:.*/)?")
                    i += 3
                    continue
                regex_parts.append(".*")
                i += 2
                continue
            if ch == "*":
                regex_parts.append("[^/]*")
            elif ch == "?":
                regex_parts.append("[^/]")
            elif ch in ".+()|^$":
                regex_parts.append("\\" + ch)
            else:
                regex_parts.append(ch)
            i += 1
        regex = "^" + "".join(regex_parts) + "$"
        return _re.match(regex, rel) is not None

    async def _walk_files(
        self,
        sandbox: Any,
        root: str,
        ignore_patterns: Tuple[str, ...],
        max_files: int,
    ) -> List[Tuple[str, float]]:
        """非递归 BFS 列出 root 下的所有文件 (虚拟路径, mtime)。

        命中 ``ignore_patterns`` 中的目录名直接跳过子树。
        ``max_files`` 防止巨大代码库爆内存。
        """
        results: List[Tuple[str, float]] = []
        stack: List[str] = [root]
        seen_dirs = 0
        while stack:
            current = stack.pop()
            seen_dirs += 1
            if seen_dirs > 5000:
                logger.warning(f"CodebaseTool: walk 超过 5000 目录，截断 root={root}")
                break
            try:
                entries = await sandbox.list_directory(current, include_hidden=True)
            except Exception as exc:
                logger.debug(f"CodebaseTool: 列目录失败 {current}: {exc}")
                continue
            for entry in entries:
                name = os.path.basename(entry.path.rstrip("/"))
                if name in ignore_patterns:
                    continue
                if entry.is_dir:
                    stack.append(entry.path)
                elif entry.is_file:
                    results.append((entry.path, float(entry.modified_time or 0)))
                    if len(results) >= max_files:
                        return results
        return results

    @tool(
        description_i18n={
            "zh": "按 glob 表达式查找文件。支持 ** 跨目录、*.py 等基本通配。结果按 mtime 倒序返回，超过 head_limit 自动截断。优先用本工具而不是 shell find。",
            "en": "Find files by glob pattern. Supports ** for any depth and *.py-style wildcards. Results sorted by mtime desc and truncated by head_limit. Prefer this over shell find.",
        },
        param_description_i18n={
            "pattern": {"zh": "glob 表达式，如 '**/*.tsx' 或 'src/**/test_*.py'", "en": "Glob, e.g. '**/*.tsx' or 'src/**/test_*.py'"},
            "path": {"zh": "搜索根路径（虚拟路径），缺省为沙箱工作区根", "en": "Search root path (virtual). Defaults to the sandbox workspace root"},
            "head_limit": {"zh": "返回上限，默认 200", "en": "Result cap, default 200"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "pattern": {"type": "string", "description": "Glob pattern"},
            "path": {"type": "string", "description": "Search root virtual path"},
            "head_limit": {"type": "integer", "default": 200, "minimum": 1},
            "session_id": {"type": "string", "description": "Session ID"},
        },
    )
    async def glob(
        self,
        pattern: str,
        path: Optional[str] = None,
        head_limit: int = 200,
        session_id: str = None,
    ) -> Dict[str, Any]:
        if not session_id:
            raise ValueError("CodebaseTool: session_id is required")
        if not isinstance(pattern, str) or not pattern:
            return make_tool_error(
                ToolErrorCode.INVALID_ARGUMENT,
                "pattern 必须是非空字符串",
            )
        try:
            sandbox = self._get_sandbox(session_id)
        except Exception as exc:
            return make_tool_error(ToolErrorCode.SANDBOX_ERROR, f"获取沙箱失败: {exc}")

        root = path or sandbox.workspace_path
        try:
            files = await self._walk_files(
                sandbox,
                root=root,
                ignore_patterns=_DEFAULT_IGNORE_PATTERNS,
                max_files=10000,
            )
        except Exception as exc:
            logger.error(f"CodebaseTool.glob: walk 失败: {exc}")
            return make_tool_error(ToolErrorCode.INTERNAL_ERROR, f"glob 遍历失败: {exc}")

        norm_pattern = self._to_pure_pattern(pattern)
        # 计算相对 root 的路径用于匹配，绝对路径用于返回
        root_norm = (root or "").replace("\\", "/").rstrip("/")
        matched: List[Tuple[str, float]] = []
        for fp, mtime in files:
            fp_norm = fp.replace("\\", "/")
            rel = fp_norm[len(root_norm):].lstrip("/") if root_norm and fp_norm.startswith(root_norm) else fp_norm
            if self._glob_match(rel, norm_pattern):
                matched.append((fp, mtime))

        matched.sort(key=lambda x: x[1], reverse=True)
        capped, truncated = _truncate(matched, head_limit)
        return {
            "success": True,
            "status": "success",
            "pattern": pattern,
            "root": root,
            "files": [fp for fp, _ in capped],
            "count": len(capped),
            "truncated": truncated,
        }

    # ==================== list_dir ====================

    @tool(
        description_i18n={
            "zh": "列出目录结构（紧凑文本树）。基于沙箱 get_file_tree，默认忽略 .git/node_modules 等噪音。",
            "en": "List directory structure as a compact text tree. Backed by sandbox get_file_tree; ignores .git/node_modules-style noise by default.",
        },
        param_description_i18n={
            "path": {"zh": "目录虚拟路径，缺省为沙箱工作区根", "en": "Directory virtual path. Defaults to sandbox workspace root"},
            "depth": {"zh": "最大遍历深度，默认 2", "en": "Max traversal depth, default 2"},
            "max_items_per_dir": {"zh": "每个目录最多展示的条目数，默认 50", "en": "Max items per directory, default 50"},
            "include_hidden": {"zh": "是否包含隐藏文件，默认 false", "en": "Include hidden files, default false"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "path": {"type": "string", "description": "Directory virtual path"},
            "depth": {"type": "integer", "default": 2, "minimum": 1},
            "max_items_per_dir": {"type": "integer", "default": 50, "minimum": 1},
            "include_hidden": {"type": "boolean", "default": False},
            "session_id": {"type": "string", "description": "Session ID"},
        },
    )
    async def list_dir(
        self,
        path: Optional[str] = None,
        depth: int = 2,
        max_items_per_dir: int = 50,
        include_hidden: bool = False,
        session_id: str = None,
    ) -> Dict[str, Any]:
        if not session_id:
            raise ValueError("CodebaseTool: session_id is required")
        try:
            sandbox = self._get_sandbox(session_id)
        except Exception as exc:
            return make_tool_error(ToolErrorCode.SANDBOX_ERROR, f"获取沙箱失败: {exc}")

        root = path or sandbox.workspace_path
        try:
            tree = await sandbox.get_file_tree(
                root_path=root,
                include_hidden=include_hidden,
                max_depth=max(1, int(depth)),
                max_items_per_dir=max(1, int(max_items_per_dir)),
            )
        except Exception as exc:
            logger.error(f"CodebaseTool.list_dir: get_file_tree 失败: {exc}")
            return make_tool_error(ToolErrorCode.INTERNAL_ERROR, f"列目录失败: {exc}")

        return {
            "success": True,
            "status": "success",
            "root": root,
            "depth": depth,
            "tree": tree or "",
        }
