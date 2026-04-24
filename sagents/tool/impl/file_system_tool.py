import os
import re
from typing import Dict, Any, Optional, List

from ..tool_base import tool
from ..error_codes import ToolErrorCode, make_tool_error
from sagents.utils.file_content_validator import FileContentValidator
from sagents.utils.logger import logger
from sagents.utils.agent_session_helper import get_session_sandbox as _get_session_sandbox_util


class FileSystemTool:
    """文件系统操作工具集 - 通过沙箱执行"""

    @staticmethod
    def _build_validation_result(file_path: str, content: str) -> Dict[str, Any]:
        """Run post-write validation for common file formats."""
        return FileContentValidator.validate(file_path, content)

    @staticmethod
    def _apply_line_range_update(
        content: str,
        replacement: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> Dict[str, Any]:
        """对文本内容执行按行区间替换。行号为 0-based，start/end 都是包含边界。"""
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        normalized_start = 0 if start_line is None else max(0, start_line)
        normalized_end = (total_lines - 1) if end_line is None else min(total_lines - 1, end_line)

        if normalized_start > normalized_end:
            return make_tool_error(
                ToolErrorCode.INVALID_ARGUMENT,
                "开始行号不能大于结束行号",
            )

        if total_lines == 0:
            return make_tool_error(
                ToolErrorCode.PRECONDITION_FAILED,
                "文件为空，无法执行按行替换",
            )

        normalized_end_exclusive = normalized_end + 1

        original_segment = "".join(lines[normalized_start:normalized_end_exclusive])
        replacement_segment = replacement
        has_suffix = normalized_end_exclusive < total_lines

        if has_suffix and replacement_segment and not replacement_segment.endswith(("\n", "\r")):
            replacement_segment += "\n"

        new_content = "".join(lines[:normalized_start]) + replacement_segment + "".join(lines[normalized_end_exclusive:])
        replace_count = 1 if original_segment != replacement_segment else 0

        if normalized_start == normalized_end and not replacement_segment:
            replace_count = 0

        return {
            "status": "success",
            "content": new_content,
            "replacements": replace_count,
            "start_line": normalized_start,
            "end_line": normalized_end,
            "lines_replaced": max(0, normalized_end_exclusive - normalized_start),
        }

    @staticmethod
    def _format_match_contexts(content: str, match_positions: List[int], context_chars: int = 40, max_items: int = 3) -> List[Dict[str, Any]]:
        """根据字符位置列出匹配的行号与上下文片段，便于 LLM 理解多匹配场景。"""
        contexts: List[Dict[str, Any]] = []
        if not match_positions:
            return contexts

        line_starts = [0]
        for idx, ch in enumerate(content):
            if ch == "\n":
                line_starts.append(idx + 1)

        def locate_line(pos: int) -> int:
            lo, hi = 0, len(line_starts) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if line_starts[mid] <= pos:
                    lo = mid
                else:
                    hi = mid - 1
            return lo

        for pos in match_positions[:max_items]:
            line_no = locate_line(pos)
            line_start = line_starts[line_no]
            line_end = line_starts[line_no + 1] - 1 if line_no + 1 < len(line_starts) else len(content)
            line_text = content[line_start:line_end]
            snippet_start = max(0, pos - context_chars)
            snippet_end = min(len(content), pos + context_chars)
            snippet = content[snippet_start:snippet_end].replace("\n", "\\n")
            contexts.append({
                "line": line_no,
                "column": pos - line_start,
                "line_text": line_text,
                "snippet": snippet,
            })
        return contexts

    @staticmethod
    def _apply_search_update(
        content: str,
        search_pattern: Optional[str],
        replacement: str,
        replace_all: bool = False,
    ) -> Dict[str, Any]:
        """对文本内容执行搜索替换。

        规则：
        1. 如果 search_pattern 作为普通文本能直接命中，则按普通文本完全匹配替换；
        2. 如果普通文本未命中，再尝试按正则表达式处理；
        3. 默认要求唯一匹配；多匹配时返回 MULTIPLE_MATCHES 错误，需显式 replace_all=True 才允许批量替换。
        """
        if not search_pattern:
            return make_tool_error(
                ToolErrorCode.INVALID_ARGUMENT,
                "搜索替换模式下必须提供 search_pattern",
            )

        text_count = content.count(search_pattern) if search_pattern in content else 0
        if text_count > 0:
            match_mode = "text"
            if text_count > 1 and not replace_all:
                positions: List[int] = []
                start = 0
                for _ in range(text_count):
                    idx = content.find(search_pattern, start)
                    if idx < 0:
                        break
                    positions.append(idx)
                    start = idx + max(1, len(search_pattern))
                return make_tool_error(
                    ToolErrorCode.MULTIPLE_MATCHES,
                    (
                        f"search_pattern 在文件中命中 {text_count} 次，默认要求唯一匹配。"
                        "请扩大 search_pattern 的上下文使其唯一，或显式设置 replace_all=true。"
                    ),
                    hint="扩大 search_pattern 上下文使其唯一，或对该 operation 设置 replace_all=true",
                    match_mode=match_mode,
                    match_count=text_count,
                    matches=FileSystemTool._format_match_contexts(content, positions),
                )
            new_content = content.replace(search_pattern, replacement)
            replace_count = text_count
        else:
            try:
                pattern = re.compile(search_pattern)
            except re.error as exc:
                return make_tool_error(
                    ToolErrorCode.INVALID_ARGUMENT,
                    f"search_pattern 不是有效的正则表达式: {exc}",
                )
            match_mode = "regex"
            regex_matches = list(pattern.finditer(content))
            regex_count = len(regex_matches)
            if regex_count > 1 and not replace_all:
                positions = [m.start() for m in regex_matches]
                return make_tool_error(
                    ToolErrorCode.MULTIPLE_MATCHES,
                    (
                        f"search_pattern 作为正则匹配命中 {regex_count} 次，默认要求唯一匹配。"
                        "请使 search_pattern 更精确，或显式设置 replace_all=true。"
                    ),
                    hint="收紧正则使其唯一命中，或对该 operation 设置 replace_all=true",
                    match_mode=match_mode,
                    match_count=regex_count,
                    matches=FileSystemTool._format_match_contexts(content, positions),
                )
            # 对 replacement 中的反斜杠进行转义，避免被解释为正则替换模板
            # 例如 \s 会被替换为 \\s，这样在 subn 中会被正确处理为字面量 \s
            escaped_replacement = replacement.replace("\\", "\\\\")
            new_content, replace_count = pattern.subn(escaped_replacement, content)

        return {
            "status": "success",
            "content": new_content,
            "replacements": replace_count,
            "match_mode": match_mode,
        }

    @staticmethod
    def _normalize_update_operation(
        op: Dict[str, Any],
    ) -> Dict[str, Any]:
        """标准化单个更新操作并显式判定更新模式。

        为了减少模型误用，这里要求两种模式尽量互斥：
        - search_replace: 仅允许 search_pattern + replacement
        - line_range: 仅允许 start_line + end_line + replacement
        """
        has_search = bool(op.get("search_pattern"))
        has_start = op.get("start_line") is not None
        has_end = op.get("end_line") is not None
        update_mode = op.get("update_mode")

        if update_mode not in (None, "search_replace", "line_range"):
            return make_tool_error(
                ToolErrorCode.INVALID_ARGUMENT,
                "update_mode 只能是 search_replace 或 line_range",
            )

        if update_mode == "line_range" or has_start or has_end:
            if not (has_start and has_end):
                return make_tool_error(
                    ToolErrorCode.INVALID_ARGUMENT,
                    "按行替换时必须同时提供 start_line 和 end_line，且二者都为整数",
                )
            if has_search:
                return make_tool_error(
                    ToolErrorCode.INVALID_ARGUMENT,
                    "按行替换模式下不要同时提供 search_pattern",
                )
            return {
                "status": "success",
                "update_mode": "line_range",
            }

        if update_mode == "search_replace" or has_search:
            if not has_search:
                return make_tool_error(
                    ToolErrorCode.INVALID_ARGUMENT,
                    "搜索替换时必须提供 search_pattern",
                )
            return {
                "status": "success",
                "update_mode": "search_replace",
            }

        return make_tool_error(
            ToolErrorCode.INVALID_ARGUMENT,
            "每个操作必须明确指定 search_pattern 或 start_line/end_line",
        )

    def _get_sandbox(self, session_id: str):
        """通过 session_id 获取沙箱。详见
        ``sagents.utils.agent_session_helper.get_session_sandbox``。
        """
        return _get_session_sandbox_util(session_id, log_prefix="FileSystemTool")

    @staticmethod
    async def _auto_lint(file_path: str, session_id: str, max_items: int = 20) -> Optional[Dict[str, Any]]:
        """对刚写入的文件触发 lint，结果挂到上层返回。失败/跳过都返回结构化信息，从不抛异常。"""
        if not file_path or not session_id:
            return None
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in {".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue"}:
            return None
        if os.environ.get("SAGE_AUTO_LINT", "true").lower() == "false":
            return None
        try:
            from .lint_tool import LintTool  # 本地引入避免循环依赖
            lt = LintTool()
            result = await lt.read_lints(paths=[file_path], max_diagnostics=max_items, session_id=session_id)
            return result
        except Exception as exc:
            logger.warning(f"FileSystemTool: 自动 lint 失败 {file_path}: {exc}")
            return {"status": "error", "reason": str(exc)}

    @tool(
        description_i18n={
            "zh": "读取文本文件指定行范围内容",
            "en": "Read text file within a line range",
        },
        param_description_i18n={
            "file_path": {"zh": "文件虚拟路径", "en": "File virtual path"},
            "start_line": {"zh": "开始行号，默认0", "en": "Start line number, default 0"},
            "end_line": {"zh": "结束行号（不包含），默认400，None表示读取到文件末尾", "en": "End line number (exclusive), default 400, None means read to end"},
            "include_line_numbers": {"zh": "是否在返回内容中附带行号，默认true", "en": "Whether to include line numbers in returned content, default true"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "file_path": {"type": "string", "description": "File virtual path"},
            "start_line": {"type": "integer", "default": 0},
            "end_line": {"type": "integer", "default": 400},
            "include_line_numbers": {"type": "boolean", "default": True},
            "session_id": {"type": "string", "description": "Session ID"},
        }
    )
    async def file_read(
        self,
        file_path: str,
        start_line: int = 0,
        end_line: Optional[int] = 400,
        include_line_numbers: bool = True,
        session_id: str = None,
    ) -> Dict[str, Any]:
        """读取文本文件指定行范围内容

        Args:
            file_path: 文件虚拟路径
            start_line: 开始行号，默认0
            end_line: 结束行号（不包含），默认400
            session_id: 会话ID（必填）

        Returns:
            包含文件内容和元信息
        """
        if not session_id:
            raise ValueError("FileSystemTool: session_id is required")

        sandbox = self._get_sandbox(session_id)

        try:
            content = await sandbox.read_file(file_path, encoding="utf-8")
            lines = content.splitlines()
            total_lines = len(lines)

            if end_line is None:
                end_line = total_lines
            start_line = max(0, start_line)
            end_line = min(total_lines, end_line)

            selected_lines = lines[start_line:end_line]
            selected_content = "\n".join(selected_lines)
            numbered_content = selected_content

            if include_line_numbers:
                numbered_content = "\n".join(
                    f"{line_number + 1:>4} | {line_text}"
                    for line_number, line_text in enumerate(selected_lines, start=start_line)
                )

            return {
                "status": "success",
                "content": numbered_content,
                "raw_content": selected_content,
                "total_lines": total_lines,
                "start_line": start_line,
                "end_line": end_line,
                "lines_read": len(selected_lines),
                "file_path": file_path,
                "line_numbers_included": include_line_numbers,
            }

        except FileNotFoundError as e:
            logger.error(f"FileSystemTool: 读取文件失败 {file_path}: {e}")
            return make_tool_error(
                ToolErrorCode.NOT_FOUND,
                f"读取文件失败: {str(e)}",
                file_path=file_path,
            )
        except PermissionError as e:
            logger.error(f"FileSystemTool: 读取文件失败 {file_path}: {e}")
            return make_tool_error(
                ToolErrorCode.PERMISSION_DENIED,
                f"读取文件失败: {str(e)}",
                file_path=file_path,
            )
        except Exception as e:
            logger.error(f"FileSystemTool: 读取文件失败 {file_path}: {e}")
            return make_tool_error(
                ToolErrorCode.SANDBOX_ERROR,
                f"读取文件失败: {str(e)}",
                file_path=file_path,
            )

    @tool(
        description_i18n={
            "zh": "写入文本到文件。适合短内容写入；较长的代码或文档请拆成多次追加写入，每次 content 不超过 1000 个字。",
            "en": "Write text to a file. Best for short content; for longer code or documents, write in multiple append calls, keeping each content under 1000 characters.",
        },
        param_description_i18n={
            "file_path": {"zh": "文件虚拟路径", "en": "File virtual path"},
            "mode": {"zh": "写入模式：overwrite 覆盖写入，append 追加到文件末尾", "en": "Write mode: overwrite replaces the file, append adds to the end of the file"},
            "content": {"zh": "要写入的文本内容，不能超过 1000 个字；较长的代码或文档请分多次追加写入", "en": "Text content to write, must not exceed 1000 characters; for longer code or documents, use multiple append calls"},
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "file_path": {"type": "string", "description": "File virtual path"},
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append"],
                "default": "overwrite",
                "description": "Write mode: overwrite replaces the file, append adds to the end of the file",
            },
            "content": {
                "type": "string",
                "description": "Text content to write. Keep it under 1000 characters; for longer code or documents, use multiple append calls",
            },
            "session_id": {"type": "string", "description": "Session ID"},
        },
        return_data={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "success or error"},
                "message": {"type": "string", "description": "Write result summary"},
                "file_path": {"type": "string", "description": "Target file path"},
                "validation": {
                    "type": "object",
                    "description": "Post-write content validation result",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "skipped": {"type": "boolean"},
                        "passed": {"type": "boolean"},
                        "status": {"type": "string", "description": "passed, warning, error, or skipped"},
                        "validator": {"type": "string"},
                        "file_extension": {"type": "string"},
                        "message": {"type": "string"},
                        "warnings": {"type": "array", "items": {"type": "string"}},
                        "errors": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    )
    async def file_write(
        self,
        file_path: str,
        content: str,
        mode: str = "overwrite",
        session_id: str = None,
    ) -> Dict[str, Any]:
        """写入文本到文件。

        Args:
            file_path: 文件虚拟路径
            content: 要写入的内容，不能超过 1000 个字；较长的代码或文档请分多次追加写入
            mode: 写入模式，overwrite 覆盖写入，append 追加到文件末尾
            session_id: 会话ID（必填）

        Returns:
            操作结果
        """
        if not session_id:
            raise ValueError("FileSystemTool: session_id is required")
        if mode not in {"overwrite", "append"}:
            raise ValueError("FileSystemTool: mode must be one of ['overwrite', 'append']")

        sandbox = self._get_sandbox(session_id)

        try:
            final_content = content
            dir_path = os.path.dirname(file_path)
            if dir_path:
                await sandbox.ensure_directory(dir_path)

            if mode == "append":
                existing = ""
                try:
                    if await sandbox.file_exists(file_path):
                        existing = await sandbox.read_file(file_path, encoding="utf-8")
                except Exception:
                    existing = ""
                final_content = existing + content
                await sandbox.write_file(file_path, final_content, mode="overwrite")
            else:
                await sandbox.write_file(file_path, content, mode="overwrite")

            validation = self._build_validation_result(file_path, final_content)
            lints = await self._auto_lint(file_path, session_id)
            result: Dict[str, Any] = {
                "status": "success",
                "success": True,
                "message": "文件写入成功" if validation.get("status") in {"passed", "skipped"} else "文件写入成功，但校验发现问题",
                "file_path": file_path,
                "content_length": len(content),
                "mode": mode,
                "validation": validation,
            }
            if lints is not None:
                result["lints"] = lints
            return result

        except PermissionError as e:
            logger.error(f"FileSystemTool: 写入文件失败 {file_path}: {e}")
            return make_tool_error(
                ToolErrorCode.PERMISSION_DENIED,
                f"写入文件失败: {str(e)}",
                file_path=file_path,
            )
        except Exception as e:
            logger.error(f"FileSystemTool: 写入文件失败 {file_path}: {e}")
            return make_tool_error(
                ToolErrorCode.SANDBOX_ERROR,
                f"写入文件失败: {str(e)}",
                file_path=file_path,
            )

    @tool(
        description_i18n={
            "zh": "更新单个文件内容。优先使用局部替换或按行区间替换，不要整文件重写；较大的修改请拆成多次小范围更新。",
            "en": "Update a single file. Prefer local replacement or line-range replacement instead of rewriting the whole file; split larger changes into multiple small updates.",
        },
        param_description_i18n={
            "file_path": {"zh": "文件虚拟路径", "en": "File virtual path"},
            "operations": {
                "zh": "替换操作列表。每项必须明确指定一种模式：search_replace 或 line_range。search_replace 只传 search_pattern + replacement，默认要求 search_pattern 在文件中唯一命中，多匹配会返回 MULTIPLE_MATCHES 错误；如确需批量替换，对该 operation 显式设置 replace_all=true。line_range 只传 start_line、end_line + replacement。按行替换时 start_line 和 end_line 都是包含边界（0-based），且二者必须同时提供。search_pattern 可以是普通文本，也可以是正则表达式；执行时会先按普通文本匹配，未命中再按正则处理。请不要用它整文件重写",
                "en": "Replacement operations. Each item must explicitly choose one mode: search_replace or line_range. search_replace accepts only search_pattern + replacement and by default REQUIRES the pattern to match uniquely in the file; multi-match returns MULTIPLE_MATCHES error. Set replace_all=true on the operation to opt-in batch replace. line_range accepts only start_line, end_line + replacement. For line-range mode, both start_line and end_line are inclusive (0-based) and must be provided together. search_pattern can be plain text or a regex; execution first tries plain-text matching, then falls back to regex if not found. Do not use it to rewrite the whole file",
            },
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "file_path": {"type": "string", "description": "File virtual path"},
            "operations": {
                "type": "array",
                "description": "Replacement operations for the same file. Prefer small local updates. Each operation must choose search_replace or line_range explicitly",
                "items": {
                    "type": "object",
                    "properties": {
                        "update_mode": {
                            "type": "string",
                            "enum": ["search_replace", "line_range"],
                            "description": "Explicit update mode for this operation"
                        },
                        "search_pattern": {
                            "type": "string",
                            "description": "Text or regex pattern to replace. Use only when update_mode is search_replace"
                        },
                        "replacement": {
                            "type": "string",
                            "description": "Replacement content. Keep it small and local whenever possible"
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "Start line number (inclusive, 0-based) for line-range replacement. Use only when update_mode is line_range"
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "End line number (inclusive, 0-based) for line-range replacement. Use only when update_mode is line_range"
                        },
                        "replace_all": {
                            "type": "boolean",
                            "default": False,
                            "description": "Search-replace only. Default false: requires unique match; multi-match returns MULTIPLE_MATCHES error. Set true to allow replacing all occurrences."
                        },
                    },
                },
            },
            "session_id": {"type": "string", "description": "Session ID"},
        },
        return_data={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "success or error"},
                "message": {"type": "string", "description": "Update result summary"},
                "file_path": {"type": "string", "description": "Target file path"},
                "validation": {
                    "type": "object",
                    "description": "Post-update content validation result",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "skipped": {"type": "boolean"},
                        "passed": {"type": "boolean"},
                        "status": {"type": "string", "description": "passed, warning, error, or skipped"},
                        "validator": {"type": "string"},
                        "file_extension": {"type": "string"},
                        "message": {"type": "string"},
                        "warnings": {"type": "array", "items": {"type": "string"}},
                        "errors": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    )
    async def file_update(
        self,
        file_path: str,
        operations: Optional[List[Dict[str, Any]]] = None,
        session_id: str = None,
    ) -> Dict[str, Any]:
        """更新单个文件内容。优先使用局部替换或按行区间替换，不要整文件重写。

        Args:
            file_path: 文件虚拟路径
            operations: 同一文件的替换操作列表。优先传局部更新，每项支持两种形式：
                1. {"update_mode": "search_replace", "search_pattern": "...", "replacement": "..."}
                2. {"update_mode": "line_range", "start_line": 10, "end_line": 12, "replacement": "..."}，其中 start_line 和 end_line 都是包含边界（0-based）
            session_id: 会话ID（必填）

        Returns:
            更新结果统计
        """
        if not session_id:
            raise ValueError("FileSystemTool: session_id is required")

        sandbox = self._get_sandbox(session_id)

        try:
            content = await sandbox.read_file(file_path, encoding="utf-8")
            current_content = content
            operation_summaries = []
            total_replacements = 0

            normalized_operations = [op for op in (operations or []) if isinstance(op, dict)]
            if not normalized_operations:
                return make_tool_error(
                    ToolErrorCode.INVALID_ARGUMENT,
                    "必须提供 operations，且每项必须是对象",
                    file_path=file_path,
                )

            line_range_ops = []
            other_ops = []
            for index, op in enumerate(normalized_operations):
                if "replacement" not in op:
                    return make_tool_error(
                        ToolErrorCode.INVALID_ARGUMENT,
                        f"第 {index + 1} 个操作缺少 replacement",
                        file_path=file_path,
                        failed_operation_index=index,
                    )

                op_summary = {"index": index}
                mode_result = self._normalize_update_operation(op)
                if mode_result["status"] == "error":
                    return make_tool_error(
                        mode_result.get("error_code", ToolErrorCode.INVALID_ARGUMENT),
                        f"第 {index + 1} 个操作失败: {mode_result['message']}",
                        file_path=file_path,
                        failed_operation_index=index,
                    )
                is_line_range = mode_result["update_mode"] == "line_range"
                if is_line_range:
                    op_summary["start_line"] = op.get("start_line")
                    op_summary["end_line"] = op.get("end_line")
                    line_range_ops.append((index, op, op_summary))
                else:
                    op_summary["search_pattern"] = op.get("search_pattern")
                    other_ops.append((index, op, op_summary))

            for index, op, op_summary in sorted(
                line_range_ops,
                key=lambda item: (
                    -1 if item[1].get("start_line") is None else -item[1].get("start_line"),
                    -1 if item[1].get("end_line") is None else -item[1].get("end_line"),
                ),
            ):
                step_result = self._apply_line_range_update(
                    current_content,
                    replacement=op.get("replacement", ""),
                    start_line=op.get("start_line"),
                    end_line=op.get("end_line"),
                )
                if step_result["status"] == "error":
                    return make_tool_error(
                        step_result.get("error_code", ToolErrorCode.INVALID_ARGUMENT),
                        f"第 {index + 1} 个操作失败: {step_result['message']}",
                        file_path=file_path,
                        failed_operation_index=index,
                    )

                requested_start = op.get("start_line")
                requested_end = op.get("end_line")
                if (
                    isinstance(requested_start, int)
                    and isinstance(requested_end, int)
                    and requested_end >= requested_start
                    and step_result.get("lines_replaced", 0) == 0
                ):
                    return make_tool_error(
                        ToolErrorCode.NO_MATCH,
                        (
                            f"第 {index + 1} 个操作未替换任何行（start_line={requested_start}, end_line={requested_end}）。"
                            "当前工具使用 0-based 且 start_line/end_line 都是包含边界；请检查行号是否有效。"
                        ),
                        file_path=file_path,
                        failed_operation_index=index,
                    )
                current_content = step_result["content"]
                total_replacements += step_result["replacements"]
                op_summary.update({
                    "update_mode": "line_range",
                    "start_line": step_result["start_line"],
                    "end_line": step_result["end_line"],
                    "lines_replaced": step_result["lines_replaced"],
                    "replacements": step_result["replacements"],
                })
                operation_summaries.append(op_summary)

            for index, op, op_summary in other_ops:
                step_result = self._apply_search_update(
                    current_content,
                    search_pattern=op.get("search_pattern"),
                    replacement=op.get("replacement", ""),
                    replace_all=bool(op.get("replace_all", False)),
                )
                if step_result["status"] == "error":
                    extras: Dict[str, Any] = {
                        "file_path": file_path,
                        "failed_operation_index": index,
                    }
                    for key in ("match_count", "matches", "match_mode"):
                        if key in step_result:
                            extras[key] = step_result[key]
                    return make_tool_error(
                        step_result.get("error_code", ToolErrorCode.INVALID_ARGUMENT),
                        f"第 {index + 1} 个操作失败: {step_result['message']}",
                        hint=step_result.get("hint"),
                        **extras,
                    )
                current_content = step_result["content"]
                total_replacements += step_result["replacements"]
                op_summary.update({
                    "update_mode": "search_replace",
                    "match_mode": step_result["match_mode"],
                    "replacements": step_result["replacements"],
                    "replace_all": bool(op.get("replace_all", False)),
                })
                operation_summaries.append(op_summary)

            if total_replacements == 0 and not line_range_ops:
                return make_tool_error(
                    ToolErrorCode.NO_MATCH,
                    "未找到匹配项，未进行任何替换",
                    file_path=file_path,
                    replacements=0,
                )

            if total_replacements == 0 and line_range_ops:
                validation = self._build_validation_result(file_path, current_content)
                return {
                    "status": "success",
                    "message": (
                        "已执行按行替换，但目标区间与替换内容一致，文件无变化"
                        if validation.get("status") in {"passed", "skipped"}
                        else "已执行按行替换，但目标区间与替换内容一致，文件无变化；校验发现问题"
                    ),
                    "replacements": 0,
                    "operations_applied": len(operation_summaries),
                    "operations": sorted(operation_summaries, key=lambda item: item["index"]),
                    "original_length": len(content),
                    "new_length": len(current_content),
                    "file_path": file_path,
                    "update_mode": "batch" if len(operation_summaries) > 1 else operation_summaries[0]["update_mode"],
                    "validation": validation,
                }

            await sandbox.write_file(file_path, current_content, mode="overwrite")
            validation = self._build_validation_result(file_path, current_content)
            lints = await self._auto_lint(file_path, session_id)

            result = {
                "status": "success",
                "success": True,
                "message": (
                    f"成功执行 {len(operation_summaries)} 个更新操作，共替换 {total_replacements} 处内容"
                    if validation.get("status") in {"passed", "skipped"}
                    else f"成功执行 {len(operation_summaries)} 个更新操作，共替换 {total_replacements} 处内容；校验发现问题"
                ),
                "replacements": total_replacements,
                "operations_applied": len(operation_summaries),
                "operations": sorted(operation_summaries, key=lambda item: item["index"]),
                "original_length": len(content),
                "new_length": len(current_content),
                "file_path": file_path,
                "update_mode": "batch" if len(operation_summaries) > 1 else operation_summaries[0]["update_mode"],
                "validation": validation,
            }
            if len(operation_summaries) == 1 and operation_summaries[0]["update_mode"] == "line_range":
                result.update({
                    "start_line": operation_summaries[0]["start_line"],
                    "end_line": operation_summaries[0]["end_line"],
                    "lines_replaced": operation_summaries[0]["lines_replaced"],
                })
            if lints is not None:
                result["lints"] = lints

            return result

        except FileNotFoundError as e:
            logger.error(f"FileSystemTool: 文件更新失败 {file_path}: {e}")
            return make_tool_error(
                ToolErrorCode.NOT_FOUND,
                f"文件更新失败: {str(e)}",
                file_path=file_path,
            )
        except PermissionError as e:
            logger.error(f"FileSystemTool: 文件更新失败 {file_path}: {e}")
            return make_tool_error(
                ToolErrorCode.PERMISSION_DENIED,
                f"文件更新失败: {str(e)}",
                file_path=file_path,
            )
        except Exception as e:
            logger.error(f"FileSystemTool: 文件更新失败 {file_path}: {e}")
            return make_tool_error(
                ToolErrorCode.SANDBOX_ERROR,
                f"文件更新失败: {str(e)}",
                file_path=file_path,
            )
