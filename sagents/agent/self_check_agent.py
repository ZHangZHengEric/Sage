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

    当前聚焦两类高价值检查：
    1. 最终输出里引用到的结果文件是否真实存在
    2. 最近一轮涉及的常见代码/数据文件是否满足基础语法约束
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

        modified_files = self._collect_recent_modified_files(session_context)
        referenced_files = self._collect_recent_referenced_files(session_context)
        candidate_files = modified_files | referenced_files
        logger.info(
            "SelfCheckAgent: collected "
            f"{len(candidate_files)} candidate files for validation "
            f"(modified={len(modified_files)}, referenced={len(referenced_files)})"
        )

        if not candidate_files:
            self._mark_passed(session_context, summary="skip: no candidate files detected")
            return

        issues: List[str] = []
        checked_files: List[str] = []

        for original_file_path in sorted(candidate_files):
            file_path = await self._resolve_file_path(session_context, original_file_path)
            checked_files.append(file_path)
            file_issues = await self._validate_file(
                session_context,
                file_path,
                require_exists=original_file_path in referenced_files,
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

    def _collect_recent_modified_files(self, session_context: SessionContext) -> Set[str]:
        messages = session_context.message_manager.messages
        if not messages:
            return set()

        last_user_index = 0
        for i, message in enumerate(messages):
            if message.is_user_input_message():
                last_user_index = i

        relevant_messages = messages[last_user_index:]
        changed_files: Set[str] = set()

        for message in relevant_messages:
            if message.role != MessageRole.ASSISTANT.value or not message.tool_calls:
                continue

            for tool_call in message.tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                function_info = tool_call.get("function", {})
                tool_name = function_info.get("name")
                if tool_name not in {"file_write", "file_update"}:
                    continue

                raw_args = function_info.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args)
                except Exception:
                    logger.warning(f"SelfCheckAgent: failed to parse tool args for {tool_name}")
                    continue

                file_path = args.get("file_path")
                if isinstance(file_path, str) and file_path.strip():
                    changed_files.add(file_path.strip())

        return changed_files

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

        for message in messages[last_user_index:]:
            if message.role != MessageRole.ASSISTANT.value:
                continue
            if not isinstance(message.content, str) or not message.content.strip():
                continue

            for raw_path in markdown_link_pattern.findall(message.content):
                normalized_path = self._normalize_raw_file_reference(raw_path)
                if self._looks_like_file_path(normalized_path):
                    referenced_files.add(normalized_path)

        return referenced_files

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
        return path

    async def _resolve_file_path(self, session_context: SessionContext, file_path: str) -> str:
        sandbox = session_context.sandbox
        if sandbox is None:
            return file_path

        normalized_path = self._normalize_raw_file_reference(file_path)
        if not normalized_path:
            return file_path

        for candidate in self._build_file_candidates(session_context, normalized_path):
            try:
                if await sandbox.file_exists(candidate):
                    return candidate
            except Exception:
                continue

        return self._build_file_candidates(session_context, normalized_path)[0]

    def _build_file_candidates(self, session_context: SessionContext, file_path: str) -> List[str]:
        workspace_roots: List[str] = []
        for candidate_root in [
            session_context.system_context.get("task_workspace"),
            session_context.system_context.get("private_workspace"),
            session_context.sandbox_agent_workspace,
        ]:
            if isinstance(candidate_root, str) and candidate_root.strip():
                root = candidate_root.rstrip("/")
                if root and root not in workspace_roots:
                    workspace_roots.append(root)

        candidates: List[str] = []

        def add_candidate(candidate: str) -> None:
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        if os.path.isabs(file_path):
            add_candidate(file_path)
            relative_path = file_path.lstrip("/")
            for root in workspace_roots:
                add_candidate(os.path.join(root, relative_path))
                basename = os.path.basename(file_path)
                if basename:
                    add_candidate(os.path.join(root, basename))
        else:
            relative_path = file_path.lstrip("./")
            for root in workspace_roots:
                add_candidate(os.path.join(root, relative_path))
            add_candidate(file_path)

        return candidates or [file_path]

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
