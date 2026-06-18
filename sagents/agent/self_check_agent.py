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

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
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


class SelfCheckAgent(AgentBase):
    """
    执行后的确定性自检 Agent。

    当前聚焦最终输出里引用到的结果文件是否真实存在，
    并要求最终消息中的 Markdown 文件链接必须使用绝对路径。
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

        referenced_file_refs = self._collect_recent_file_references(session_context)
        logger.info(
            "SelfCheckAgent: collected "
            f"{len(referenced_file_refs)} referenced files for validation"
        )

        if not referenced_file_refs:
            self._mark_passed(
                session_context, summary="skip: no candidate files detected"
            )
            return

        issues: List[str] = []
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
            audit_status["self_check_passed"] = False
            # 强制下一轮重新进入执行链，而不是被上一次 completion_status 卡住。
            audit_status["completion_status"] = "in_progress"
            audit_status["task_completed"] = False

            content = self._format_failure_message(issues, checked_files)
            yield [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content=content,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.AGENT_EXECUTION_ERROR.value,
                    agent_name=self.agent_name,
                    metadata={
                        "self_check_passed": False,
                        "checked_files": checked_files,
                        "error_type": MessageType.AGENT_EXECUTION_ERROR.value,
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
        if checked_files is not None:
            session_context.audit_status["self_check_checked_files"] = checked_files

    def _collect_recent_referenced_files(
        self, session_context: SessionContext
    ) -> Set[str]:
        return {
            file_ref.path
            for file_ref in self._collect_recent_file_references(session_context)
        }

    def _collect_recent_file_references(
        self, session_context: SessionContext
    ) -> Set[FileReference]:
        messages = session_context.message_manager.messages
        if not messages:
            return set()

        last_user_index = 0
        for i, message in enumerate(messages):
            if message.is_user_input_message():
                last_user_index = i

        referenced_file_refs: Set[FileReference] = set()
        markdown_link_pattern = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")

        latest_assistant_message = None
        for message in messages[last_user_index:]:
            if (
                message.role == MessageRole.ASSISTANT.value
                and isinstance(message.content, str)
                and message.content.strip()
            ):
                latest_assistant_message = message

        if latest_assistant_message is None:
            return referenced_file_refs

        content = latest_assistant_message.content

        for raw_path in markdown_link_pattern.findall(content):  # pyright: ignore[reportArgumentType,reportCallIssue]
            normalized_path = self._normalize_raw_file_reference(raw_path)
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

    def _extract_artifact_paths(self, content: str) -> Set[str]:
        artifact_paths: Set[str] = set()
        artifact_tag_pattern = re.compile(
            r"<(movo-artifacts|ling-artifacts|sage-artifacts|artifacts)(?:\s[^>]*)?>"
            r"([\s\S]*?)<\\?/\1\s*>",
            re.IGNORECASE,
        )

        candidate_contents = [content]
        unescaped_content = unescape(content)
        if unescaped_content != content:
            candidate_contents.append(unescaped_content)

        for candidate_content in candidate_contents:
            for match in artifact_tag_pattern.finditer(candidate_content):
                payload = self._decode_json_payload(match.group(2) or "")
                if payload is None:
                    continue
                artifact_paths.update(self._find_path_fields(payload))

        return artifact_paths

    def _decode_json_payload(self, raw_json: str) -> Any:
        candidates = []
        text = unescape(str(raw_json or "").strip())
        if text:
            candidates.append(text)
            candidates.append(text.replace(r"\/", "/"))
            if r"\"" in text:
                candidates.append(text.replace(r"\"", '"').replace(r"\\", "\\"))

        for candidate in candidates:
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

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

    def _format_failure_message(
        self, issues: List[str], checked_files: List[str]
    ) -> str:
        issue_lines = "\n".join(f"- {issue}" for issue in issues[:20])
        checked_lines = "\n".join(f"- {path}" for path in checked_files[:20])
        return (
            "自检发现以下问题，需要先修复后再继续：\n\n"
            "已检查文件：\n"
            f"{checked_lines}\n\n"
            "发现的问题：\n"
            f"{issue_lines}\n\n"
            "请优先修复这些问题，然后重新完成任务。"
        )
