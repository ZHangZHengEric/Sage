from __future__ import annotations

import ast
from dataclasses import dataclass
from html import unescape
import json
import re
import shlex
import uuid
import os
from urllib.parse import unquote
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Python 3.10 compatibility  # pyright: ignore[reportMissingImports]

from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.context.session_context import SessionContext
from sagents.utils.logger import logger

from .agent_base import AgentBase

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None


@dataclass(frozen=True)
class FileReference:
    path: str
    require_absolute: bool = True


@dataclass(frozen=True)
class MarkdownFileLink:
    markdown: str
    target: str
    in_code: bool = False


@dataclass(frozen=True)
class QuestionnaireFence:
    tag_name: str
    raw_payload: str
    start: int
    end: int
    opening_fence_length: int
    closing_fence_length: Optional[int]
    supported: bool


ARTIFACT_TAGS = (
    "yiii-artifacts",
    "movo-artifacts",
    "ling-artifacts",
    "sage-artifacts",
    "artifacts",
)
QUESTIONNAIRE_TAGS = (
    "yiii-questionnaire",
    "movo-questionnaire",
    "ling-questionnaire",
    "sage-questionnaire",
    "questionnaire",
)
QUESTIONNAIRE_RESPONSE_TAGS = tuple(f"{tag}-response" for tag in QUESTIONNAIRE_TAGS)
STRUCTURED_INLINE_TAGS = (
    ARTIFACT_TAGS + QUESTIONNAIRE_TAGS + QUESTIONNAIRE_RESPONSE_TAGS
)
QUESTIONNAIRE_FAMILY_REQUIREMENT = "*-questionnaire"
QUESTIONNAIRE_FENCE_START_PATTERN = re.compile(
    r"^[ \t]{0,3}(?P<fence>`{2,})(?P<tag>"
    r"(?:[a-z0-9][a-z0-9_-]*-)?questionnaire)[ \t]*\r?$",
    re.IGNORECASE | re.MULTILINE,
)
QUESTIONNAIRE_FENCE_END_PATTERN = re.compile(
    r"^[ \t]{0,3}(?P<fence>`{2,})[ \t]*\r?$",
    re.MULTILINE,
)
NESTED_FENCE_PATTERN = re.compile(
    r"^[ \t]{0,3}(?:`{3,}|~{3,})(?:[^\r\n]*)$",
    re.MULTILINE,
)
class SelfCheckAgent(AgentBase):
    """
    执行后的确定性自检 Agent。

    当前聚焦：
    1. Artifacts / Questionnaire 等特殊协议内 JSON/YAML 是否可解析且结构合法；
    2. 最终输出里引用到的结果文件是否真实存在；
    3. 最终消息中的 Markdown 文件链接必须使用绝对路径。
    """

    def __init__(
        self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""
    ):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "SelfCheckAgent"
        self.agent_description = "执行后自检智能体，负责验证产物存在性与基础语法可靠性"

    async def run_stream(
        self, session_context: SessionContext
    ) -> AsyncGenerator[List[MessageChunk], None]:
        if self._should_abort_due_to_session(session_context):
            return

        audit_status = session_context.audit_status
        audit_status["self_check_attempts"] = (
            int(audit_status.get("self_check_attempts", 0)) + 1
        )

        sandbox = session_context.sandbox
        if sandbox is None:
            logger.warning("SelfCheckAgent: sandbox unavailable, skip self-check")
            self._mark_passed(session_context, summary="skip: no sandbox")
            return

        latest_assistant_content = self._get_latest_assistant_content(session_context)
        has_structured_tags = self._content_has_structured_tags(
            latest_assistant_content
        )
        structured_tag_issues = self._validate_structured_tag_payloads(
            latest_assistant_content
        )
        structured_tag_names = self._structured_tag_names(latest_assistant_content)
        invalid_structured_tag_names = (
            self._invalid_structured_tag_names(latest_assistant_content)
        )
        required_structured_tag_names = {
            str(tag_name).lower()
            for tag_name in audit_status.get(
                "self_check_required_structured_tags", []
            )
            if str(tag_name).strip()
        }
        missing_required_structured_tags = (
            required_structured_tag_names - structured_tag_names
        )
        for tag_name in sorted(missing_required_structured_tags):
            structured_tag_issues.append(
                f"<{tag_name}> 必须在修复后的完整回复中重新输出，不能省略"
            )
        markdown_link_issues = self._validate_markdown_file_link_syntax(
            latest_assistant_content
        )
        referenced_file_refs = self._collect_recent_file_references(session_context)
        logger.info(
            "SelfCheckAgent: collected "
            f"{len(referenced_file_refs)} referenced files for validation, "
            f"{len(structured_tag_issues)} structured-tag issues, "
            f"{len(markdown_link_issues)} Markdown-link issues"
        )

        if (
            not referenced_file_refs
            and not structured_tag_issues
            and not markdown_link_issues
            and not has_structured_tags
        ):
            self._mark_passed(
                session_context, summary="skip: no candidate files detected"
            )
            return

        issues: List[str] = [*structured_tag_issues, *markdown_link_issues]
        checked_files: List[str] = []

        for file_ref in sorted(
            referenced_file_refs, key=lambda item: (item.path, item.require_absolute)
        ):
            original_file_path = file_ref.path
            normalized_path = self._normalize_raw_file_reference(original_file_path)
            if file_ref.require_absolute and not self._is_absolute_file_reference(
                normalized_path
            ):
                issues.append(
                    "最终回复中的文件链接必须使用绝对路径 Markdown 链接，"
                    f"请将 `{original_file_path}` 改为类似 "
                    "`[filename](file:///absolute/path/to/file)` 的格式。"
                )
                continue

            file_path = normalized_path
            if not self._is_absolute_file_reference(file_path):
                file_path = self._resolve_relative_file_reference(
                    session_context, file_path
                )
                if not file_path:
                    issues.append(f"无法解析相对文件路径: {original_file_path}")
                    continue

            workspace_issue = self._validate_reference_in_workspace(
                session_context,
                file_path,
                original_file_path=original_file_path,
            )
            if workspace_issue:
                issues.append(workspace_issue)
                continue

            checked_files.append(file_path)
            file_issues = await self._validate_file(
                session_context,
                file_path,
                require_exists=True,
                original_file_path=original_file_path,
            )
            issues.extend(file_issues)

        audit_status["self_check_checked_files"] = checked_files
        audit_status["self_check_issues"] = issues

        if issues:
            unresolved_structured_tag_names = (
                missing_required_structured_tags | invalid_structured_tag_names
            )
            if unresolved_structured_tag_names:
                audit_status["self_check_required_structured_tags"] = sorted(
                    unresolved_structured_tag_names
                )
            else:
                audit_status.pop("self_check_required_structured_tags", None)
            audit_status["self_check_passed"] = False
            # 强制下一轮重新进入执行链，而不是被上一次 completion_status 卡住。
            audit_status["completion_status"] = "in_progress"
            audit_status["task_completed"] = False

            language = self._get_session_language(session_context)
            content = self._format_failure_message(issues, checked_files, language)
            yield [
                MessageChunk(
                    role=MessageRole.USER.value,
                    content=content,
                    message_id=str(uuid.uuid4()),
                    agent_name=self.agent_name,
                    metadata={
                        **self._next_request_runtime_metadata(
                            runtime_diagnostic_source="sage_self_check"
                        ),
                        "self_check_passed": False,
                        "checked_files": checked_files,
                    },
                )
            ]
            return

        self._mark_passed(
            session_context,
            summary=f"checked {len(checked_files)} files",
            checked_files=checked_files,
        )

    def _mark_passed(
        self,
        session_context: SessionContext,
        summary: str,
        checked_files: Optional[List[str]] = None,
    ) -> None:
        session_context.audit_status["self_check_passed"] = True
        session_context.audit_status["self_check_issues"] = []
        session_context.audit_status["self_check_summary"] = summary
        session_context.audit_status.pop(
            "self_check_required_structured_tags", None
        )
        if checked_files is not None:
            session_context.audit_status["self_check_checked_files"] = checked_files

    def _collect_recent_referenced_files(
        self, session_context: SessionContext
    ) -> Set[str]:
        return {
            file_ref.path
            for file_ref in self._collect_recent_file_references(session_context)
        }

    def _get_latest_assistant_content(self, session_context: SessionContext) -> str:
        messages = session_context.message_manager.messages
        if not messages:
            return ""

        last_user_index = 0
        for i, message in enumerate(messages):
            if message.is_user_input_message():
                last_user_index = i

        latest_assistant_content = ""
        for message in messages[last_user_index:]:
            if (
                message.role == MessageRole.ASSISTANT.value
                and isinstance(message.content, str)
                and message.content.strip()
            ):
                latest_assistant_content = message.content
        return latest_assistant_content

    def _collect_recent_file_references(
        self, session_context: SessionContext
    ) -> Set[FileReference]:
        content = self._get_latest_assistant_content(session_context)
        if not content:
            return set()

        referenced_file_refs: Set[FileReference] = set()

        for link in self._iter_markdown_file_links(content):
            if link.in_code:
                continue
            normalized_path = self._normalize_raw_file_reference(link.target)
            if self._looks_like_file_path(normalized_path):
                referenced_file_refs.add(
                    FileReference(path=normalized_path, require_absolute=True)
                )

        for raw_path in self._extract_artifact_paths(content):
            normalized_path = self._normalize_raw_file_reference(raw_path)
            if self._looks_like_file_path(normalized_path):
                referenced_file_refs.add(
                    FileReference(path=normalized_path, require_absolute=False)
                )

        return self._dedupe_referenced_file_refs(referenced_file_refs)

    def _validate_markdown_file_link_syntax(self, content: str) -> List[str]:
        """Reject local file links hidden inside Markdown code regions."""
        if not content:
            return []

        issues: List[str] = []
        seen_markdown: Set[str] = set()
        for link in self._iter_markdown_file_links(content):
            normalized_target = self._normalize_raw_file_reference(link.target)
            if (
                not link.in_code
                or not self._looks_like_file_path(normalized_target)
                or link.markdown in seen_markdown
            ):
                continue
            seen_markdown.add(link.markdown)
            issues.append(
                "真实文件引用不能放在反引号或代码块中，请移除代码标记并直接输出标准 "
                f"Markdown 文件链接：{link.markdown}"
            )
        return issues

    def _iter_markdown_file_links(self, content: str):
        code_ranges = self._markdown_code_ranges(content)
        range_index = 0
        index = 0
        while index < len(content or ""):
            markdown_start = index
            if content.startswith("![", index):
                label_start = index + 1
            elif content[index] == "[":
                label_start = index
            else:
                index += 1
                continue

            label_end = self._find_matching_markdown_bracket(
                content, label_start, "[", "]"
            )
            if label_end is None or label_end + 1 >= len(content):
                index = label_start + 1
                continue
            if content[label_end + 1] != "(":
                index = label_end + 1
                continue

            parsed = self._parse_markdown_link_destination(content, label_end + 1)
            if parsed is None:
                index = label_end + 1
                continue
            markdown_end, target = parsed

            while (
                range_index < len(code_ranges)
                and code_ranges[range_index][1] <= markdown_start
            ):
                range_index += 1
            in_code = bool(
                range_index < len(code_ranges)
                and code_ranges[range_index][0]
                <= markdown_start
                < code_ranges[range_index][1]
            )
            yield MarkdownFileLink(
                markdown=content[markdown_start:markdown_end],
                target=target,
                in_code=in_code,
            )
            index = markdown_end

    @staticmethod
    def _find_matching_markdown_bracket(
        content: str,
        start: int,
        opening: str,
        closing: str,
    ) -> Optional[int]:
        depth = 0
        index = start
        while index < len(content):
            char = content[index]
            if char == "\\" and index + 1 < len(content):
                index += 2
                continue
            if char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    return index
            index += 1
        return None

    def _parse_markdown_link_destination(
        self, content: str, opening_paren: int
    ) -> Optional[tuple[int, str]]:
        """Parse one inline-link destination and return end offset plus target."""

        cursor = opening_paren + 1
        while cursor < len(content) and content[cursor].isspace():
            cursor += 1
        if cursor >= len(content):
            return None

        if content[cursor] == "<":
            target_start = cursor
            cursor += 1
            while cursor < len(content):
                if content[cursor] == "\\" and cursor + 1 < len(content):
                    cursor += 2
                    continue
                if content[cursor] == ">":
                    target = content[target_start : cursor + 1]
                    return self._finish_markdown_link_destination(
                        content, cursor + 1, target
                    )
                if content[cursor] in "\r\n":
                    return None
                cursor += 1
            return None

        target_start = cursor
        nested_parens = 0
        while cursor < len(content):
            char = content[cursor]
            if char == "\\" and cursor + 1 < len(content):
                cursor += 2
                continue
            if char == "(":
                nested_parens += 1
                cursor += 1
                continue
            if char == ")":
                if nested_parens == 0:
                    return cursor + 1, content[target_start:cursor]
                nested_parens -= 1
                cursor += 1
                continue
            if char.isspace() and nested_parens == 0:
                return self._finish_markdown_link_destination(
                    content, cursor, content[target_start:cursor]
                )
            cursor += 1
        return None

    def _finish_markdown_link_destination(
        self, content: str, cursor: int, target: str
    ) -> Optional[tuple[int, str]]:
        separator_start = cursor
        while cursor < len(content) and content[cursor].isspace():
            cursor += 1
        if cursor >= len(content):
            return None
        if content[cursor] == ")":
            return cursor + 1, target
        if cursor == separator_start:
            return None

        title_opener = content[cursor]
        title_closer = {"\"": "\"", "'": "'", "(": ")"}.get(title_opener)
        if title_closer is None:
            return None
        cursor += 1
        title_depth = 1
        while cursor < len(content):
            char = content[cursor]
            if char == "\\" and cursor + 1 < len(content):
                cursor += 2
                continue
            if title_opener == "(" and char == "(":
                title_depth += 1
            elif char == title_closer:
                title_depth -= 1
                if title_depth == 0:
                    cursor += 1
                    break
            if char in "\r\n":
                return None
            cursor += 1
        else:
            return None

        while cursor < len(content) and content[cursor].isspace():
            cursor += 1
        if cursor < len(content) and content[cursor] == ")":
            return cursor + 1, target
        return None

    def _markdown_code_ranges(self, content: str) -> List[tuple[int, int]]:
        """Return fenced-block and inline-code ranges using Markdown delimiters."""

        if not content:
            return []

        fenced_ranges: List[tuple[int, int]] = []
        open_fence: Optional[tuple[str, int, int, int, int]] = None
        offset = 0
        for line in content.splitlines(keepends=True):
            body = line.rstrip("\r\n")
            if open_fence is None:
                opener = self._markdown_fence_opener(body)
                if opener is not None:
                    marker_char, marker_len, quote_depth, max_close_indent = opener
                    open_fence = (
                        marker_char,
                        marker_len,
                        offset,
                        quote_depth,
                        max_close_indent,
                    )
            else:
                (
                    marker_char,
                    marker_len,
                    start,
                    quote_depth,
                    max_close_indent,
                ) = open_fence
                if self._is_markdown_fence_closer(
                    body,
                    marker_char=marker_char,
                    marker_len=marker_len,
                    quote_depth=quote_depth,
                    max_indent=max_close_indent,
                ):
                    fenced_ranges.append((start, offset + len(line)))
                    open_fence = None
            offset += len(line)
        if open_fence is not None:
            fenced_ranges.append((open_fence[2], len(content)))

        indented_ranges = self._markdown_indented_code_ranges(
            content, fenced_ranges
        )
        block_ranges = sorted([*fenced_ranges, *indented_ranges])
        inline_ranges: List[tuple[int, int]] = []
        for start, end in self._markdown_inline_blocks(content, block_ranges):
            inline_ranges.extend(self._markdown_inline_code_ranges(content, start, end))

        return sorted([*block_ranges, *inline_ranges])

    @staticmethod
    def _strip_markdown_blockquote_prefix(body: str) -> tuple[int, str]:
        quote_depth = 0
        remaining = body
        while True:
            match = re.match(r" {0,3}>[ \t]?", remaining)
            if match is None:
                break
            quote_depth += 1
            remaining = remaining[match.end() :]
        return quote_depth, remaining

    def _markdown_fence_opener(
        self, body: str
    ) -> Optional[tuple[str, int, int, int]]:
        quote_depth, remaining = self._strip_markdown_blockquote_prefix(body)
        leading_spaces = len(remaining) - len(remaining.lstrip(" "))
        if leading_spaces > 3:
            return None

        candidate = remaining[leading_spaces:]
        list_match = re.match(r"(?:[-+*]|\d{1,9}[.)])[ \t]+", candidate)
        if list_match is not None:
            content_indent = leading_spaces + list_match.end()
            candidate = candidate[list_match.end() :]
            max_close_indent = content_indent + 3
        else:
            max_close_indent = 3

        marker_match = re.match(r"(`{3,}|~{3,})(.*)$", candidate)
        if marker_match is None:
            return None
        marker = marker_match.group(1)
        info = marker_match.group(2)
        if marker.startswith("`") and "`" in info:
            return None
        return marker[0], len(marker), quote_depth, max_close_indent

    def _is_markdown_fence_closer(
        self,
        body: str,
        *,
        marker_char: str,
        marker_len: int,
        quote_depth: int,
        max_indent: int,
    ) -> bool:
        actual_quote_depth, remaining = self._strip_markdown_blockquote_prefix(body)
        if actual_quote_depth != quote_depth:
            return False
        leading_spaces = len(remaining) - len(remaining.lstrip(" "))
        if leading_spaces > max_indent:
            return False
        candidate = remaining[leading_spaces:]
        return bool(
            re.fullmatch(
                rf"{re.escape(marker_char)}{{{marker_len},}}[ \t]*",
                candidate,
            )
        )

    def _markdown_indented_code_ranges(
        self,
        content: str,
        excluded_ranges: List[tuple[int, int]],
    ) -> List[tuple[int, int]]:
        """Return four-column indented code blocks outside fenced blocks."""

        ranges: List[tuple[int, int]] = []
        open_start: Optional[int] = None
        open_end: Optional[int] = None
        open_quote_depth: Optional[int] = None
        previous_line_blank = True
        excluded_index = 0
        offset = 0

        for line in content.splitlines(keepends=True):
            line_end = offset + len(line)
            while (
                excluded_index < len(excluded_ranges)
                and excluded_ranges[excluded_index][1] <= offset
            ):
                excluded_index += 1
            is_excluded = bool(
                excluded_index < len(excluded_ranges)
                and excluded_ranges[excluded_index][0] < line_end
                and offset < excluded_ranges[excluded_index][1]
            )

            body = line.rstrip("\r\n")
            quote_depth, remaining = self._strip_markdown_blockquote_prefix(body)
            is_blank = not remaining.strip()
            is_indented = (
                not is_blank and self._markdown_indentation_width(remaining) >= 4
            )

            if is_excluded:
                if open_start is not None and open_end is not None:
                    ranges.append((open_start, open_end))
                    open_start = None
                    open_end = None
                    open_quote_depth = None
                # A fenced block is already a block boundary, so an indented
                # block may begin immediately after its closing line.
                previous_line_blank = True
                offset = line_end
                continue

            same_container = (
                open_quote_depth is None or quote_depth == open_quote_depth
            )
            if open_start is not None and (is_blank or (is_indented and same_container)):
                open_end = line_end
            else:
                if open_start is not None and open_end is not None:
                    ranges.append((open_start, open_end))
                    open_start = None
                    open_end = None
                    open_quote_depth = None

                if is_indented and previous_line_blank:
                    open_start = offset
                    open_end = line_end
                    open_quote_depth = quote_depth

            previous_line_blank = is_blank
            offset = line_end

        if open_start is not None and open_end is not None:
            ranges.append((open_start, open_end))
        return ranges

    @staticmethod
    def _markdown_indentation_width(text: str) -> int:
        width = 0
        for char in text:
            if char == " ":
                width += 1
            elif char == "\t":
                width += 4 - (width % 4)
            else:
                break
        return width

    @staticmethod
    def _markdown_inline_blocks(
        content: str, code_block_ranges: List[tuple[int, int]]
    ) -> List[tuple[int, int]]:
        available_ranges: List[tuple[int, int]] = []
        cursor = 0
        for start, end in code_block_ranges:
            if cursor < start:
                available_ranges.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < len(content):
            available_ranges.append((cursor, len(content)))

        blocks: List[tuple[int, int]] = []
        for available_start, available_end in available_ranges:
            block_start: Optional[int] = None
            offset = available_start
            for line in content[available_start:available_end].splitlines(
                keepends=True
            ):
                line_end = offset + len(line)
                if line.rstrip("\r\n").strip():
                    if block_start is None:
                        block_start = offset
                elif block_start is not None:
                    blocks.append((block_start, offset))
                    block_start = None
                offset = line_end
            if block_start is not None:
                blocks.append((block_start, available_end))
        return blocks

    @staticmethod
    def _markdown_inline_code_ranges(
        content: str, start: int, end: int
    ) -> List[tuple[int, int]]:
        ranges: List[tuple[int, int]] = []
        index = start
        while index < end:
            if content[index] != "`":
                index += 1
                continue
            if SelfCheckAgent._is_markdown_character_escaped(content, index, start):
                index += 1
                continue
            opener_end = index + 1
            while opener_end < end and content[opener_end] == "`":
                opener_end += 1
            delimiter_len = opener_end - index
            search_at = opener_end
            closing_end: Optional[int] = None
            while search_at < end:
                closing_start = content.find("`", search_at, end)
                if closing_start < 0:
                    break
                candidate_end = closing_start + 1
                while (
                    candidate_end < end and content[candidate_end] == "`"
                ):
                    candidate_end += 1
                if candidate_end - closing_start == delimiter_len:
                    closing_end = candidate_end
                    break
                search_at = candidate_end
            if closing_end is None:
                index = opener_end
                continue
            ranges.append((index, closing_end))
            index = closing_end
        return ranges

    @staticmethod
    def _is_markdown_character_escaped(
        content: str, index: int, range_start: int = 0
    ) -> bool:
        backslash_count = 0
        cursor = index - 1
        while cursor >= range_start and content[cursor] == "\\":
            backslash_count += 1
            cursor -= 1
        return backslash_count % 2 == 1

    def _content_has_structured_tags(self, content: str) -> bool:
        for _tag_name, _raw_payload in self._iter_structured_tag_matches(content):
            return True
        if any(self._iter_questionnaire_fences(content)):
            return True
        return False

    def _structured_tag_names(self, content: str) -> Set[str]:
        tag_names: Set[str] = set()
        for tag_name, _raw_payload in self._iter_structured_tag_matches(content):
            tag_names.add(tag_name)
            if tag_name in QUESTIONNAIRE_TAGS:
                tag_names.add(QUESTIONNAIRE_FAMILY_REQUIREMENT)
        for fence in self._iter_questionnaire_fences(content):
            if fence.supported:
                tag_names.add(fence.tag_name)
            tag_names.add(QUESTIONNAIRE_FAMILY_REQUIREMENT)
        return tag_names

    def _invalid_structured_tag_names(self, content: str) -> Set[str]:
        invalid_names = {
            tag_name
            for tag_name, raw_payload in self._iter_structured_tag_matches(content)
            if self._validate_structured_tag_payload(tag_name, raw_payload)
        }
        for fence, issues in self._fenced_questionnaire_validation_results(content):
            if not issues:
                continue
            invalid_names.add(
                fence.tag_name
                if fence.supported
                else QUESTIONNAIRE_FAMILY_REQUIREMENT
            )
        return invalid_names

    def _structured_tag_pattern(self) -> re.Pattern[str]:
        tag_names = "|".join(re.escape(tag) for tag in STRUCTURED_INLINE_TAGS)
        return re.compile(
            rf"<({tag_names})(?:\s[^>]*)?>([\s\S]*?)<\\?/\1\s*>",
            re.IGNORECASE,
        )

    def _iter_structured_tag_matches(self, content: str):
        if not content:
            return

        candidate_contents = [content]
        unescaped_content = unescape(content)
        if unescaped_content != content:
            candidate_contents.append(unescaped_content)

        pattern = self._structured_tag_pattern()
        seen_spans: Set[tuple[int, int, str]] = set()
        for candidate_content in candidate_contents:
            for match in pattern.finditer(candidate_content):
                tag_name = (match.group(1) or "").lower()
                span_key = (match.start(), match.end(), tag_name)
                if span_key in seen_spans:
                    continue
                seen_spans.add(span_key)
                yield tag_name, match.group(2) or ""

    def _iter_questionnaire_fences(self, content: str):
        if not content:
            return

        markdown_code_ranges = self._markdown_code_ranges(content)
        cursor = 0
        while cursor < len(content):
            opening = QUESTIONNAIRE_FENCE_START_PATTERN.search(content, cursor)
            if opening is None:
                break
            if any(
                range_start < opening.start() < range_end
                for range_start, range_end in markdown_code_ranges
            ):
                cursor = opening.end()
                continue

            payload_start = opening.end()
            if payload_start < len(content) and content[payload_start] == "\n":
                payload_start += 1

            closing = QUESTIONNAIRE_FENCE_END_PATTERN.search(content, payload_start)
            if closing is None:
                end = len(content)
                raw_payload = content[payload_start:]
                closing_fence_length = None
            else:
                end = closing.end()
                raw_payload = content[payload_start : closing.start()]
                closing_fence_length = len(closing.group("fence"))

            tag_name = str(opening.group("tag") or "").lower()
            yield QuestionnaireFence(
                tag_name=tag_name,
                raw_payload=raw_payload,
                start=opening.start(),
                end=end,
                opening_fence_length=len(opening.group("fence")),
                closing_fence_length=closing_fence_length,
                supported=tag_name in QUESTIONNAIRE_TAGS,
            )

            if closing is None:
                break
            cursor = end

    def _fenced_questionnaire_validation_results(
        self, content: str
    ) -> List[tuple[QuestionnaireFence, List[str]]]:
        fences = list(self._iter_questionnaire_fences(content))
        results: List[tuple[QuestionnaireFence, List[str]]] = []
        has_preface = True
        if fences:
            has_preface = self._has_questionnaire_preface(content[: fences[0].start])

        for index, fence in enumerate(fences):
            issues: List[str] = []
            if index == 0 and not has_preface:
                issues.append(
                    f"```{fence.tag_name}``` 不能作为整条回复的唯一内容；"
                    "问卷前必须包含非空的普通说明文字"
                )
            issues.extend(self._validate_fenced_questionnaire(fence))
            results.append((fence, issues))
        return results

    def _has_questionnaire_preface(self, prefix: str) -> bool:
        visible_prefix = self._structured_tag_pattern().sub("", prefix)
        code_ranges = self._markdown_code_ranges(visible_prefix)
        if code_ranges:
            fragments: List[str] = []
            cursor = 0
            for start, end in code_ranges:
                fragments.append(visible_prefix[cursor:start])
                cursor = end
            fragments.append(visible_prefix[cursor:])
            visible_prefix = "".join(fragments)
        return bool(visible_prefix.strip())

    def _validate_structured_tag_payloads(self, content: str) -> List[str]:
        issues: List[str] = []
        for tag_name, raw_payload in self._iter_structured_tag_matches(content):
            issues.extend(self._validate_structured_tag_payload(tag_name, raw_payload))
        for _fence, fence_issues in self._fenced_questionnaire_validation_results(
            content
        ):
            issues.extend(fence_issues)
        return issues

    def _validate_structured_tag_payload(
        self, tag_name: str, raw_payload: str
    ) -> List[str]:
        payload, error = self._parse_json_payload(raw_payload)
        if error:
            return [f"<{tag_name}> 标签内容不是合法 JSON: {error}"]

        if not isinstance(payload, dict):
            return [f"<{tag_name}> 标签内容必须是 JSON 对象"]

        if tag_name in ARTIFACT_TAGS:
            return self._validate_artifacts_payload(tag_name, payload)
        if tag_name in QUESTIONNAIRE_TAGS:
            return self._validate_questionnaire_payload(tag_name, payload)
        if tag_name in QUESTIONNAIRE_RESPONSE_TAGS:
            return self._validate_questionnaire_response_payload(tag_name, payload)
        return []

    def _validate_fenced_questionnaire(
        self, fence: QuestionnaireFence
    ) -> List[str]:
        label = f"```{fence.tag_name}```"
        if not fence.supported:
            supported = ", ".join(QUESTIONNAIRE_TAGS)
            return [
                f"{label} 不是受支持的问卷别名；请使用以下之一: {supported}"
            ]
        if fence.opening_fence_length < 3:
            return [f"{label} 的起始围栏至少需要三个反引号"]
        if fence.closing_fence_length is None:
            return [f"{label} 缺少独占一行的结束围栏"]
        if fence.closing_fence_length < fence.opening_fence_length:
            return [
                f"{label} 的结束围栏不能短于起始围栏"
            ]

        raw_payload = str(fence.raw_payload or "")
        payload_text = raw_payload.strip()
        if not payload_text:
            return [f"{label} 的 YAML 内容不能为空"]
        if payload_text.startswith(("{", "[")):
            return [f"{label} 必须使用块状 YAML，不能放入 JSON 载荷"]
        if NESTED_FENCE_PATTERN.search(raw_payload):
            return [f"{label} 内不能嵌套代码围栏"]
        if yaml is None:
            return [f"{label} 无法校验：当前运行环境缺少 YAML 解析器"]

        try:
            payload = yaml.safe_load(payload_text)
        except Exception as exc:
            return [f"{label} 不是合法 YAML: {self._format_yaml_error(exc)}"]

        if not isinstance(payload, dict):
            return [f"{label} 的 YAML 顶层必须是对象"]
        return self._validate_strict_fenced_questionnaire_payload(
            fence.tag_name, payload
        )

    @staticmethod
    def _format_yaml_error(error: Exception) -> str:
        problem = str(getattr(error, "problem", "") or "").strip()
        mark = getattr(error, "problem_mark", None)
        if problem and mark is not None:
            return f"line {mark.line + 1} column {mark.column + 1}: {problem}"
        return problem or str(error)

    def _validate_strict_fenced_questionnaire_payload(
        self, tag_name: str, payload: Dict[str, Any]
    ) -> List[str]:
        label = f"```{tag_name}```"
        top_level_fields = set(payload.keys())
        allowed_top_level_fields = {"title", "questions"}
        unexpected_top_level_fields = sorted(
            str(field)
            for field in top_level_fields - allowed_top_level_fields
        )
        if unexpected_top_level_fields:
            return [
                f"{label} 顶层包含不允许的字段: "
                f"{', '.join(unexpected_top_level_fields)}"
            ]

        title = payload.get("title")
        if not isinstance(title, str) or not title.strip():
            return [f"{label} 缺少合法的 title 字段"]

        questions = payload.get("questions")
        if not isinstance(questions, list):
            return [f"{label} 缺少合法的 questions 数组"]
        if not questions:
            return [f"{label} questions 不能为空"]

        for index, question in enumerate(questions, start=1):
            issue_prefix = f"{label} questions[{index}]"
            if not isinstance(question, dict):
                return [f"{issue_prefix} 必须是对象"]
            if any(not isinstance(field, str) for field in question):
                return [f"{issue_prefix} 的字段名必须是字符串"]

            question_type = str(question.get("type") or "").strip().lower()
            if question_type not in {
                "single_choice",
                "multi_choice",
                "free_text",
            }:
                return [
                    f"{issue_prefix} 的 type 不受支持: "
                    f"{question_type or '空'}"
                ]

            allowed_fields = {"type", "text", "default"}
            if question_type in {"single_choice", "multi_choice"}:
                allowed_fields.update({"options", "allow_other"})
            unexpected_fields = sorted(set(question) - allowed_fields)
            if unexpected_fields:
                return [
                    f"{issue_prefix} 包含不允许的字段: "
                    f"{', '.join(unexpected_fields)}"
                ]

            text = question.get("text")
            if not isinstance(text, str) or not text.strip():
                return [f"{issue_prefix} 缺少合法的 text 字段"]
            if "default" not in question:
                return [f"{issue_prefix} 缺少 default 字段"]

            if question_type in {"single_choice", "multi_choice"}:
                options = question.get("options")
                if (
                    not isinstance(options, list)
                    or not options
                    or any(
                        not isinstance(option, str) or not option.strip()
                        for option in options
                    )
                ):
                    return [f"{issue_prefix} 的 options 必须是非空字符串数组"]
                allow_other = question.get("allow_other")
                if allow_other is not None and not isinstance(allow_other, bool):
                    return [f"{issue_prefix} 的 allow_other 必须是布尔值"]

                default = question.get("default")
                if question_type == "single_choice":
                    if not isinstance(default, str) or default not in options:
                        return [
                            f"{issue_prefix} 的 default 必须等于一个 options 选项"
                        ]
                else:
                    if not isinstance(default, list) or any(
                        not isinstance(value, str) or value not in options
                        for value in default
                    ):
                        return [
                            f"{issue_prefix} 的 default 必须是 options 的字符串子集"
                        ]
                continue

            if not isinstance(question.get("default"), str):
                return [f"{issue_prefix} 的 default 必须是字符串"]
        return []

    def _validate_artifacts_payload(
        self, tag_name: str, payload: Dict[str, Any]
    ) -> List[str]:
        items = payload.get("items")
        if not isinstance(items, list):
            return [f"<{tag_name}> 缺少合法的 items 数组"]
        if not items:
            return [f"<{tag_name}> items 不能为空"]
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                return [f"<{tag_name}> items[{index}] 必须是对象"]
            path = item.get("path")
            if not isinstance(path, str) or not path.strip():
                return [f"<{tag_name}> items[{index}] 缺少合法的 path 字段"]
        return []

    def _validate_questionnaire_payload(
        self, tag_name: str, payload: Dict[str, Any]
    ) -> List[str]:
        strict_yiii = tag_name == "yiii-questionnaire"
        if strict_yiii:
            title = payload.get("title")
            if not isinstance(title, str) or not title.strip():
                return [f"<{tag_name}> 缺少合法的 title 字段"]
        questions = payload.get("questions")
        if not isinstance(questions, list):
            return [f"<{tag_name}> 缺少合法的 questions 数组"]
        if not questions:
            return [f"<{tag_name}> questions 不能为空"]
        for index, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                return [f"<{tag_name}> questions[{index}] 必须是对象"]
            text = question.get("text")
            if not isinstance(text, str) or not text.strip():
                return [f"<{tag_name}> questions[{index}] 缺少合法的 text 字段"]
            question_type = str(question.get("type") or "").strip().lower()
            if strict_yiii and question_type not in {
                "single_choice",
                "multi_choice",
                "free_text",
            }:
                return [
                    f"<{tag_name}> questions[{index}] 的 type 不受支持: "
                    f"{question_type or '空'}"
                ]
            if question_type in {"single_choice", "multi_choice", "multiple_choice"}:
                options = question.get("options")
                if (
                    not isinstance(options, list)
                    or not options
                    or any(
                        not self._is_valid_questionnaire_option(option)
                        for option in options
                    )
                ):
                    return [
                        f"<{tag_name}> questions[{index}] 的选择题必须提供非空 options"
                    ]
            if strict_yiii:
                if "default" not in question:
                    return [
                        f"<{tag_name}> questions[{index}] 缺少 default 字段"
                    ]
                default = question.get("default")
                if question_type == "multi_choice":
                    if not isinstance(default, list) or any(
                        not isinstance(value, str) for value in default
                    ):
                        return [
                            f"<{tag_name}> questions[{index}] 的 default 必须是字符串数组"
                        ]
                elif not isinstance(default, str):
                    return [
                        f"<{tag_name}> questions[{index}] 的 default 必须是字符串"
                    ]
                allow_other = question.get("allow_other")
                if allow_other is not None and not isinstance(allow_other, bool):
                    return [
                        f"<{tag_name}> questions[{index}] 的 allow_other 必须是布尔值"
                    ]
        return []

    @staticmethod
    def _is_valid_questionnaire_option(option: Any) -> bool:
        if isinstance(option, str):
            return bool(option.strip())
        if not isinstance(option, dict):
            return False
        value = option.get("value")
        label = option.get("label")
        return any(
            isinstance(candidate, str) and bool(candidate.strip())
            for candidate in (value, label)
        )

    def _validate_questionnaire_response_payload(
        self, tag_name: str, payload: Dict[str, Any]
    ) -> List[str]:
        answers = payload.get("answers")
        if not isinstance(answers, list):
            return [f"<{tag_name}> 缺少合法的 answers 数组"]
        return []

    def _extract_artifact_paths(self, content: str) -> Set[str]:
        artifact_paths: Set[str] = set()
        for tag_name, raw_payload in self._iter_structured_tag_matches(content):
            if tag_name not in ARTIFACT_TAGS:
                continue
            payload = self._decode_json_payload(raw_payload)
            if payload is None:
                continue
            artifact_paths.update(self._find_path_fields(payload))
        return artifact_paths

    def _parse_json_payload(self, raw_json: str) -> tuple[Optional[Any], Optional[str]]:
        candidates = []
        text = unescape(str(raw_json or "").strip())
        if not text:
            return None, "内容为空"
        candidates.append(text)
        candidates.append(text.replace(r"\/", "/"))
        if r"\"" in text:
            candidates.append(text.replace(r"\"", '"').replace(r"\\", "\\"))

        last_error = "无法解析 JSON"
        for candidate in candidates:
            try:
                return json.loads(candidate), None
            except json.JSONDecodeError as exc:
                last_error = f"line {exc.lineno} column {exc.colno}: {exc.msg}"
            except Exception as exc:
                last_error = str(exc)
        return None, last_error

    def _decode_json_payload(self, raw_json: str) -> Any:
        payload, _error = self._parse_json_payload(raw_json)
        return payload

    def _find_path_fields(self, value: Any) -> Set[str]:
        paths: Set[str] = set()
        if isinstance(value, dict):
            raw_path = value.get("path")
            if isinstance(raw_path, str) and raw_path.strip():
                paths.add(raw_path)
            for child in value.values():
                paths.update(self._find_path_fields(child))
        elif isinstance(value, list):
            for item in value:
                paths.update(self._find_path_fields(item))
        return paths

    def _dedupe_referenced_file_refs(
        self, referenced_file_refs: Set[FileReference]
    ) -> Set[FileReference]:
        if len(referenced_file_refs) < 2:
            return referenced_file_refs

        grouped: Dict[bool, Set[str]] = {}
        for file_ref in referenced_file_refs:
            grouped.setdefault(file_ref.require_absolute, set()).add(file_ref.path)

        deduped_refs: Set[FileReference] = set()
        for require_absolute, paths in grouped.items():
            for path in self._dedupe_referenced_files(paths):
                deduped_refs.add(
                    FileReference(path=path, require_absolute=require_absolute)
                )
        return deduped_refs

    def _looks_like_file_path(self, path: str) -> bool:
        if not path or path.startswith("#"):
            return False
        if path.startswith("//"):
            return False
        lowered = path.lower()
        if lowered.startswith(
            ("http://", "https://", "file://", "data:", "javascript:")
        ):
            return False
        if path.startswith("/api/"):
            return False
        name = Path(path).name
        if "." not in name:
            return False
        return True

    def _normalize_raw_file_reference(self, raw_path: str) -> str:
        path = str(raw_path or "").strip().strip("`").strip("'\"")
        if not path:
            return path
        if path.startswith("<") and path.endswith(">"):
            path = path[1:-1].strip()
        path = re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~])", r"\1", path)
        if path.startswith("file://"):
            path = re.sub(r"^file:///?", "/", path)
        path = unquote(path)
        if os.name == "nt" and path[:1] in {"/", "\\"}:
            trimmed = path.lstrip("/\\")
            if os.path.isabs(trimmed):
                path = trimmed
        return path

    def _resolve_relative_file_reference(
        self, session_context: SessionContext, file_path: str
    ) -> Optional[str]:
        candidates = [
            getattr(session_context, "sandbox_agent_workspace", None),
            (getattr(session_context, "system_context", {}) or {}).get(
                "private_workspace"
            ),
        ]
        for candidate in candidates:
            if candidate:
                return os.path.abspath(os.path.join(str(candidate), file_path))
        return None

    def _is_absolute_file_reference(self, file_path: str) -> bool:
        return os.path.isabs(file_path)

    def _dedupe_referenced_files(self, referenced_files: Set[str]) -> Set[str]:
        if len(referenced_files) < 2:
            return referenced_files

        deduped_files = set(referenced_files)
        basename_to_paths: Dict[str, List[str]] = {}
        for path in referenced_files:
            basename = Path(path).name
            if basename:
                basename_to_paths.setdefault(basename, []).append(path)

        for paths in basename_to_paths.values():
            concrete_absolute_paths = [
                path
                for path in paths
                if self._is_concrete_absolute_file_reference(path)
            ]
            if not concrete_absolute_paths:
                continue

            for path in paths:
                if path in concrete_absolute_paths:
                    continue
                if self._is_ambiguous_root_file_reference(path) or not os.path.isabs(
                    path
                ):
                    deduped_files.discard(path)

        return deduped_files

    def _is_ambiguous_root_file_reference(self, file_path: str) -> bool:
        return os.path.isabs(file_path) and len(Path(file_path).parts) == 2

    def _is_concrete_absolute_file_reference(self, file_path: str) -> bool:
        return os.path.isabs(file_path) and not self._is_ambiguous_root_file_reference(
            file_path
        )

    def _validate_reference_in_workspace(
        self,
        session_context: SessionContext,
        file_path: str,
        original_file_path: Optional[str] = None,
    ) -> Optional[str]:
        sandbox = session_context.sandbox
        if sandbox is not None and hasattr(sandbox, "is_path_allowed"):
            try:
                if sandbox.is_path_allowed(file_path, operation="read"):
                    return None
                return (
                    "文件路径超出可访问工作区，不能作为最终产物引用: "
                    f"{original_file_path or file_path}"
                )
            except Exception as e:
                logger.warning(
                    f"SelfCheckAgent: sandbox path permission check failed {file_path}: {e}"
                )

        allowed_roots = self._fallback_allowed_roots(session_context)
        if not allowed_roots:
            return None

        normalized = os.path.realpath(os.path.abspath(file_path))
        for root in allowed_roots:
            try:
                if os.path.commonpath([normalized, root]) == root:
                    return None
            except ValueError:
                continue

        return (
            "文件路径超出可访问工作区，不能作为最终产物引用: "
            f"{original_file_path or file_path}"
        )

    def _fallback_allowed_roots(self, session_context: SessionContext) -> List[str]:
        roots: List[str] = []
        candidates = [
            getattr(session_context, "sandbox_agent_workspace", None),
            (getattr(session_context, "system_context", {}) or {}).get(
                "private_workspace"
            ),
        ]
        external_paths = getattr(session_context, "external_paths", None)
        if external_paths is None:
            external_paths = (getattr(session_context, "system_context", {}) or {}).get(
                "external_paths"
            )
        if isinstance(external_paths, str):
            candidates.append(external_paths)
        elif isinstance(external_paths, list):
            candidates.extend(str(path) for path in external_paths if path)

        for candidate in candidates:
            if not candidate:
                continue
            roots.append(os.path.realpath(os.path.abspath(str(candidate))))
        return sorted(set(roots))

    async def _validate_file(
        self,
        session_context: SessionContext,
        file_path: str,
        require_exists: bool,
        original_file_path: Optional[str] = None,
    ) -> List[str]:
        sandbox = session_context.sandbox
        if sandbox is None:
            return [f"无法检查文件，sandbox 不存在: {file_path}"]

        issues: List[str] = []
        exists = await sandbox.file_exists(file_path)
        if not exists:
            if require_exists:
                missing_path = original_file_path or file_path
                return [f"文件不存在: {missing_path}"]
            logger.info(f"SelfCheckAgent: skip missing transient file {file_path}")
            return issues

        suffix = Path(file_path).suffix.lower()
        text_content = await self._safe_read_text(sandbox, file_path)

        if text_content is None:
            return issues

        try:
            if suffix == ".py":
                ast.parse(text_content, filename=file_path)
            elif suffix == ".json":
                json.loads(text_content)
            elif suffix in {".toml"}:
                tomllib.loads(text_content)
            elif suffix in {".yaml", ".yml"} and yaml is not None:
                yaml.safe_load(text_content)
            elif suffix in {".js", ".mjs", ".cjs"}:
                command = f"node --check {shlex.quote(file_path)}"
                result = await sandbox.execute_command(
                    command=command,
                    workdir=session_context.sandbox_agent_workspace,
                    timeout=20,
                )
                if not result.success or result.return_code != 0:
                    stderr = (
                        result.stderr or result.stdout or "unknown syntax error"
                    ).strip()
                    issues.append(f"JavaScript 语法错误: {file_path}\n{stderr}")
        except SyntaxError as e:
            issues.append(f"Python 语法错误: {file_path}:{e.lineno}:{e.offset} {e.msg}")
        except json.JSONDecodeError as e:
            issues.append(f"JSON 语法错误: {file_path}:{e.lineno}:{e.colno} {e.msg}")
        except tomllib.TOMLDecodeError as e:
            issues.append(f"TOML 语法错误: {file_path}: {e}")
        except Exception as e:
            issues.append(f"文件校验失败: {file_path}: {e}")

        return issues

    async def _safe_read_text(self, sandbox: Any, file_path: str) -> Optional[str]:
        try:
            return await sandbox.read_file(file_path, encoding="utf-8")
        except UnicodeDecodeError:
            logger.info(f"SelfCheckAgent: skip non-text file {file_path}")
            return None
        except Exception as e:
            logger.warning(f"SelfCheckAgent: failed to read {file_path}: {e}")
            return None

    def _get_session_language(self, session_context: SessionContext) -> str:
        get_language = getattr(session_context, "get_language", None)
        if callable(get_language):
            try:
                return str(get_language() or "zh")
            except Exception:
                return "zh"
        system_context = getattr(session_context, "system_context", {}) or {}
        response_language = str(system_context.get("response_language") or "").lower()
        if "zh" in response_language or "中文" in response_language:
            return "zh"
        if "pt" in response_language:
            return "pt"
        if "en" in response_language:
            return "en"
        return "zh"

    def _format_failure_message(
        self, issues: List[str], checked_files: List[str], language: str = "zh"
    ) -> str:
        issue_lines = "\n".join(f"- {issue}" for issue in issues[:20])
        checked_lines = "\n".join(f"- {path}" for path in checked_files[:20])
        if str(language or "").lower().startswith("en"):
            return (
                '<runtime_diagnostic source="sage_self_check" generated_by="system">\n'
                "This is an internal Sage repair instruction, not a new user request.\n"
                "The previous final response failed validation. Fix the issues below and output the complete corrected result again.\n"
                "Do not reply only that you are preparing to fix it. If a structured tag failed, output the complete tag again with valid JSON.\n\n"
                "Issues that must be fixed:\n\n"
                "Checked files:\n"
                f"{checked_lines}\n\n"
                "Issues found:\n"
                f"{issue_lines}\n\n"
                "Fix them now and output the complete corrected result.\n"
                "</runtime_diagnostic>"
            )
        if str(language or "").lower().startswith("pt"):
            return (
                '<runtime_diagnostic source="sage_self_check" generated_by="system">\n'
                "Esta e uma instrucao interna de reparo do Sage, nao uma nova solicitacao do usuario.\n"
                "A resposta final anterior falhou na validacao. Corrija os problemas abaixo e produza novamente o resultado corrigido completo.\n"
                "Nao responda apenas que vai preparar a correcao. Se uma tag estruturada falhou, produza novamente a tag completa com JSON valido.\n\n"
                "Problemas que precisam ser corrigidos:\n\n"
                "Arquivos verificados:\n"
                f"{checked_lines}\n\n"
                "Problemas encontrados:\n"
                f"{issue_lines}\n\n"
                "Corrija-os agora e produza o resultado corrigido completo.\n"
                "</runtime_diagnostic>"
            )
        return (
            '<runtime_diagnostic source="sage_self_check" generated_by="system">\n'
            "这是 Sage 内部修复指令，不是新的用户需求。\n"
            "上一轮最终回复未通过校验。请修复以下问题，并重新输出修复后的完整结果。\n"
            "禁止只回复“准备修复”。如果结构化标签校验失败，必须重新输出完整标签，并确保其中的 JSON 合法。\n\n"
            "必须修复的问题：\n\n"
            "已检查文件：\n"
            f"{checked_lines}\n\n"
            "发现的问题：\n"
            f"{issue_lines}\n\n"
            "请立即修复并重新输出完整结果。\n"
            "</runtime_diagnostic>"
        )
