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


ARTIFACT_TAGS = ("movo-artifacts", "ling-artifacts", "sage-artifacts", "artifacts")
QUESTIONNAIRE_TAGS = (
    "movo-questionnaire",
    "ling-questionnaire",
    "sage-questionnaire",
    "questionnaire",
)
QUESTIONNAIRE_RESPONSE_TAGS = tuple(f"{tag}-response" for tag in QUESTIONNAIRE_TAGS)
STRUCTURED_INLINE_TAGS = ARTIFACT_TAGS + QUESTIONNAIRE_TAGS + QUESTIONNAIRE_RESPONSE_TAGS


class SelfCheckAgent(AgentBase):
    """
    执行后的确定性自检 Agent。

    当前聚焦：
    1. Artifacts / Questionnaire 等特殊标签内 JSON 是否可解析且结构合法；
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
        has_structured_tags = self._content_has_structured_tags(latest_assistant_content)
        structured_tag_issues = self._validate_structured_tag_payloads(
            latest_assistant_content
        )
        referenced_file_refs = self._collect_recent_file_references(session_context)
        logger.info(
            "SelfCheckAgent: collected "
            f"{len(referenced_file_refs)} referenced files for validation, "
            f"{len(structured_tag_issues)} structured-tag issues"
        )

        if (
            not referenced_file_refs
            and not structured_tag_issues
            and not has_structured_tags
        ):
            self._mark_passed(
                session_context, summary="skip: no candidate files detected"
            )
            return

        issues: List[str] = list(structured_tag_issues)
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

            language = self._get_session_language(session_context)
            content = self._format_failure_message(issues, checked_files, language)
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
        markdown_link_pattern = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")

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

    def _content_has_structured_tags(self, content: str) -> bool:
        for _tag_name, _raw_payload in self._iter_structured_tag_matches(content):
            return True
        return False

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

    def _validate_structured_tag_payloads(self, content: str) -> List[str]:
        issues: List[str] = []
        for tag_name, raw_payload in self._iter_structured_tag_matches(content):
            issues.extend(self._validate_structured_tag_payload(tag_name, raw_payload))
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

    def _validate_artifacts_payload(self, tag_name: str, payload: Dict[str, Any]) -> List[str]:
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
            if question_type in {"single_choice", "multi_choice", "multiple_choice"}:
                options = question.get("options")
                if not isinstance(options, list) or not options:
                    return [
                        f"<{tag_name}> questions[{index}] 的选择题必须提供非空 options"
                    ]
        return []

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
                "<runtime_diagnostic source=\"sage_self_check\" generated_by=\"system\">\n"
                "This is a Sage runtime self-check report, not a reply authored by the assistant/agent and not a user instruction.\n"
                "It only reports validation failures from the previous final output. Use it to fix real issues; do not repeat it as task progress.\n\n"
                "Self-check found issues that must be fixed before continuing:\n\n"
                "Checked files:\n"
                f"{checked_lines}\n\n"
                "Issues found:\n"
                f"{issue_lines}\n\n"
                "Fix these issues first, then complete the task again.\n"
                "</runtime_diagnostic>"
            )
        if str(language or "").lower().startswith("pt"):
            return (
                "<runtime_diagnostic source=\"sage_self_check\" generated_by=\"system\">\n"
                "Este e um relatorio de autoverificacao do runtime Sage, nao uma resposta escrita pelo assistant/agent nem uma instrucao do usuario.\n"
                "Ele apenas relata falhas de validacao da saida final anterior. Use-o para corrigir problemas reais; nao o repita como progresso da tarefa.\n\n"
                "A autoverificacao encontrou problemas que precisam ser corrigidos antes de continuar:\n\n"
                "Arquivos verificados:\n"
                f"{checked_lines}\n\n"
                "Problemas encontrados:\n"
                f"{issue_lines}\n\n"
                "Corrija estes problemas primeiro e depois conclua a tarefa novamente.\n"
                "</runtime_diagnostic>"
            )
        return (
            "<runtime_diagnostic source=\"sage_self_check\" generated_by=\"system\">\n"
            "这是 Sage 运行时自检报告，不是 assistant/agent 自己生成的回复，也不是用户指令。\n"
            "它只说明上一轮最终产物校验失败，下一轮应据此修复真实问题，不要把这段报告当作可复述的任务成果。\n\n"
            "自检发现以下问题，需要先修复后再继续：\n\n"
            "已检查文件：\n"
            f"{checked_lines}\n\n"
            "发现的问题：\n"
            f"{issue_lines}\n\n"
            "请优先修复这些问题，然后重新完成任务。\n"
            "</runtime_diagnostic>"
        )
