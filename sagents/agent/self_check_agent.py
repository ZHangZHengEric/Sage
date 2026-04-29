from __future__ import annotations

import ast
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
    import tomli as tomllib  # Python 3.10 compatibility

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext
from sagents.utils.logger import logger

from .agent_base import AgentBase

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None


class SelfCheckAgent(AgentBase):
    """
    执行后的确定性自检 Agent。

    当前聚焦最终输出里引用到的结果文件是否真实存在，
    并要求最终消息中的 Markdown 文件链接必须使用绝对路径。
    """

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "SelfCheckAgent"
        self.agent_description = "执行后自检智能体，负责验证产物存在性与基础语法可靠性"

    async def run_stream(self, session_context: SessionContext) -> AsyncGenerator[List[MessageChunk], None]:
        if self._should_abort_due_to_session(session_context):
            return

        audit_status = session_context.audit_status
        audit_status["self_check_attempts"] = int(audit_status.get("self_check_attempts", 0)) + 1

        sandbox = session_context.sandbox
        if sandbox is None:
            logger.warning("SelfCheckAgent: sandbox unavailable, skip self-check")
            self._mark_passed(session_context, summary="skip: no sandbox")
            return

        referenced_files = self._collect_recent_referenced_files(session_context)
        logger.info(
            "SelfCheckAgent: collected "
            f"{len(referenced_files)} referenced files for validation"
        )

        if not referenced_files:
            self._mark_passed(session_context, summary="skip: no candidate files detected")
            return

        issues: List[str] = []
        checked_files: List[str] = []

        for original_file_path in sorted(referenced_files):
            normalized_path = self._normalize_raw_file_reference(original_file_path)
            if not self._is_absolute_file_reference(normalized_path):
                issues.append(
                    "最终回复中的文件链接必须使用绝对路径 Markdown 链接，"
                    f"请将 `{original_file_path}` 改为类似 "
                    "`[filename](file:///absolute/path/to/file)` 的格式。"
                )
                continue

            file_path = normalized_path
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
                    message_type=MessageType.OBSERVATION.value,
                    agent_name=self.agent_name,
                    metadata={"self_check_passed": False, "checked_files": checked_files},
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

    def _collect_recent_referenced_files(self, session_context: SessionContext) -> Set[str]:
        messages = session_context.message_manager.messages
        if not messages:
            return set()

        last_user_index = 0
        for i, message in enumerate(messages):
            if message.is_user_input_message():
                last_user_index = i

        referenced_files: Set[str] = set()
        markdown_link_pattern = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")

        latest_assistant_message = None
        for message in messages[last_user_index:]:
            if message.role == MessageRole.ASSISTANT.value and isinstance(message.content, str) and message.content.strip():
                latest_assistant_message = message

        if latest_assistant_message is None:
            return referenced_files

        for raw_path in markdown_link_pattern.findall(latest_assistant_message.content):
            normalized_path = self._normalize_raw_file_reference(raw_path)
            if self._looks_like_file_path(normalized_path):
                referenced_files.add(normalized_path)

        return self._dedupe_referenced_files(referenced_files)

    def _looks_like_file_path(self, path: str) -> bool:
        if not path or path.startswith("#"):
            return False
        if path.startswith("//"):
            return False
        lowered = path.lower()
        if lowered.startswith(("http://", "https://", "file://", "data:", "javascript:")):
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
                path for path in paths if self._is_concrete_absolute_file_reference(path)
            ]
            if not concrete_absolute_paths:
                continue

            for path in paths:
                if path in concrete_absolute_paths:
                    continue
                if self._is_ambiguous_root_file_reference(path) or not os.path.isabs(path):
                    deduped_files.discard(path)

        return deduped_files

    def _is_ambiguous_root_file_reference(self, file_path: str) -> bool:
        return os.path.isabs(file_path) and len(Path(file_path).parts) == 2

    def _is_concrete_absolute_file_reference(self, file_path: str) -> bool:
        return os.path.isabs(file_path) and not self._is_ambiguous_root_file_reference(file_path)

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
                    stderr = (result.stderr or result.stdout or "unknown syntax error").strip()
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

    def _format_failure_message(self, issues: List[str], checked_files: List[str]) -> str:
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
