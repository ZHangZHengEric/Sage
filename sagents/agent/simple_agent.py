from sagents.context.messages.message_manager import MessageManager
from sagents.context.messages.token_accounting import (
    ContextOverflowStrategy,
    ContextPolicy,
    ContextViewSpec,
)
from .agent_base import (
    AgentBase,
    PartialStreamConsumedError,
    ProviderContextWindowExceededError,
)
from typing import Any, Dict, List, Optional, AsyncGenerator, Tuple, Union, cast
from sagents.utils.logger import logger
from sagents.context.messages.message import (
    MessageChunk,
    MessageRole,
    MessageType,
    is_execution_error_message_type,
)
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.tool.impl.todo_tool import ToDoTool
from sagents.utils.prompt_manager import PromptManager
from sagents.utils.content_saver import save_agent_response_content
from sagents.tool.tool_baseline import augment_with_baseline_tools
from sagents.tool.tool_expansion import TOOL_EXPAND_TOOLS, should_expose_tool_expansion
from sagents.utils.completion_mode import (
    is_llm_judge_mode,
    is_no_tool_call_mode,
    is_turn_status_mode,
)
from sagents.utils.llm_request_utils import redact_base64_data_urls_in_value
from sagents.utils.i18n import t
import json
import yaml
import uuid
from copy import deepcopy
from dataclasses import dataclass
from html import unescape
import re
import os
from sagents.utils.repeat_pattern import (
    build_loop_signature as _build_loop_signature_util,
    detect_repeat_pattern as _detect_repeat_pattern_util,
    build_self_correction_message as _build_self_correction_message_util,
)


TASK_COMPLETE_TOOL_RESULT_PREVIEW_CHARS = 500
DEFAULT_REPEAT_PATTERN_MAX_HITS = 3
REPEAT_PATTERN_MAX_HITS_ENV = "SAGE_REPEAT_PATTERN_MAX_HITS"
REPEAT_RECOVERY_QUESTION_ID = "loop_recovery_action"
REPEAT_RECOVERY_NOTICE = "repeat_pattern_questionnaire"
MAX_LOOP_NOTICE = "max_loop_questionnaire"
TASK_COMPLETE_TODO_FIELD_MAX_CHARS = 300
OPEN_TODO_ALLOWED_DECISIONS = frozenset({"continue", "need_user_input", "blocked"})
QUESTIONNAIRE_ASYNC_TOOL_NAME = "questionnaire_async"
SAGE_QUESTIONNAIRE_RESPONSE_PATTERN = re.compile(
    r"<(?P<tag>(?:sage-)?questionnaire-response)(?:\s[^>]*)?>"
    r"(?P<payload>[\s\S]*?)<\\?/(?P=tag)\s*>",
    re.IGNORECASE,
)
QUESTIONNAIRE_ASYNC_SUCCESS_STATUSES = frozenset({"validation_passed", "awaiting_user_input"})


@dataclass(frozen=True)
class TaskCompleteDecision:
    task_interrupted: bool
    reason: str = ""


def _get_repeat_pattern_max_hits() -> int:
    raw_value = (os.environ.get(REPEAT_PATTERN_MAX_HITS_ENV) or "").strip()
    if not raw_value:
        return DEFAULT_REPEAT_PATTERN_MAX_HITS
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_REPEAT_PATTERN_MAX_HITS
    return value if value > 0 else DEFAULT_REPEAT_PATTERN_MAX_HITS


def _get_system_prefix(tool_manager: Optional[ToolManager], language: str) -> str:
    """
    根据工具管理器中是否有 todo_write 工具来选择合适的 system prefix

    Args:
        tool_manager: 工具管理器
        language: 语言

    Returns:
        str: 拼接后的 system prefix
    """
    tool_names = []
    if tool_manager:
        # 获取所有工具
        tool_names = tool_manager.list_all_tools_name()
        # tools_json = tool_manager.get_openai_tools(lang=language, fallback_chain=["en"])
        # tool_names = [tool['function']['name'] for tool in tools_json]

    prompt_manager = PromptManager()
    parts = [
        prompt_manager.get_agent_prompt(
            "SimpleAgent",
            "agent_custom_system_base_requirements",
            language=language,
        )
    ]

    if "todo_write" in tool_names:
        parts.append(
            prompt_manager.get_agent_prompt(
                "SimpleAgent",
                "agent_custom_system_task_requirement",
                language=language,
            )
        )

    if is_turn_status_mode():
        parts.append(
            prompt_manager.get_agent_prompt(
                "SimpleAgent",
                "agent_custom_system_turn_status_requirement",
                language=language,
            )
        )

    if is_no_tool_call_mode():
        parts.append(
            prompt_manager.get_agent_prompt(
                "SimpleAgent",
                "agent_custom_system_no_tool_call_requirement",
                language=language,
            )
        )

    return "\n".join(parts)


class SimpleAgent(AgentBase):
    """
    简单智能体

    负责无推理策略的直接任务执行，比ReAct策略更快速。
    适用于不需要推理或早期处理的任务。
    """

    def __init__(
        self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""
    ):
        super().__init__(model, model_config, system_prefix)

        # 循环模式触发阈值：连续命中后触发软纠偏/硬暂停
        self.max_repeat_pattern_hits = _get_repeat_pattern_max_hits()
        self.agent_name = "SimpleAgent"
        self.context_policy = ContextPolicy(
            view_spec=ContextViewSpec(
                policy_id="conversation_persistent_summary",
                persistent_history=True,
            ),
            overflow_strategy=ContextOverflowStrategy.PERSISTENT_SUMMARY,
        )
        self.context_view_policy_id = self.context_policy.view_spec.policy_id
        self.agent_description = """SimpleAgent: 简单智能体，负责无推理策略的直接任务执行，比ReAct策略更快速。适用于不需要推理或早期处理的任务。"""
        logger.debug("SimpleAgent 初始化完成")

    def _build_loop_signature(self, chunks: List[MessageChunk]) -> str:
        """
        为单轮输出构建签名（同时覆盖文本与工具调用/结果）。
        """
        return _build_loop_signature_util(chunks)

    def _detect_repeat_pattern(
        self,
        signatures: List[str],
        max_period: int = 8,
    ) -> Optional[Dict[str, int]]:
        """
        在最近签名序列中检测循环模式，支持:
        - AAAAAAA (period=1)
        - ABABAB / ABBABB (period=2/3)
        - AABBAABB (period=4)
        """
        return _detect_repeat_pattern_util(signatures, max_period=max_period)

    def _resolve_tool_choice(
        self,
        tools_json: List[Dict[str, Any]],
        *,
        force_tool_choice_required: bool = False,
        force_tool_choice_auto: bool = False,
    ) -> Optional[str]:
        if not tools_json:
            return None
        if force_tool_choice_required:
            return "required"
        if force_tool_choice_auto:
            return "auto"
        env_force_required = (
            self._turn_status_enabled()
            and self._allowed_tool_names(tools_json) == {"turn_status"}
            and os.getenv("SAGE_FORCE_TOOL_CHOICE_REQUIRED", "").strip().lower()
            in ("1", "true", "yes", "on")
        )
        return "required" if env_force_required else None

    def _should_escape_required_next_turn(
        self,
        chunks: List[MessageChunk],
        *,
        pattern: Optional[Dict[str, int]] = None,
    ) -> bool:
        if pattern:
            return True
        for chunk in chunks or []:
            if getattr(chunk, "role", None) != MessageRole.TOOL.value:
                continue
            metadata = getattr(chunk, "metadata", None)
            if (
                isinstance(metadata, dict)
                and metadata.get("turn_status_rejected") is True
            ):
                return True
            content = str(getattr(chunk, "content", "") or "").lower()
            if "turn_status" in content and (
                "rejected" in content or "拒绝" in content
            ):
                return True
        return False

    def _build_self_correction_message(
        self, pattern: Dict[str, int], language: str = "en"
    ) -> str:
        template = PromptManager().get_prompt(
            key="repeat_pattern_self_correction_template",
            agent="common",
            language=language,
            default=_build_self_correction_message_util(pattern),
        )
        try:
            return template.format(period=pattern["period"], cycles=pattern["cycles"])
        except Exception:
            return _build_self_correction_message_util(pattern)

    def _build_repeat_recovery_questionnaire(
        self,
        *,
        pattern: Optional[Dict[str, int]] = None,
        language: str = "en",
        stop_reason: str = "repeat_pattern",
        recovery_metadata: Optional[Dict[str, Any]] = None,
    ) -> MessageChunk:
        title = t("runtime.repeat_recovery.title", language)
        notice = t("runtime.repeat_recovery.notice", language)
        question = t("runtime.repeat_recovery.question", language)
        payload = {
            "title": title,
            "ui_text": {
                "answer_title": t("runtime.repeat_recovery.answer_title", language),
                "question_fallback": t(
                    "runtime.repeat_recovery.question_fallback", language
                ),
                "unanswered": t("runtime.repeat_recovery.unanswered", language),
                "answer_separator": t(
                    "runtime.repeat_recovery.answer_separator", language
                ),
            },
            "questions": [
                {
                    "id": REPEAT_RECOVERY_QUESTION_ID,
                    "type": "free_text",
                    "text": question,
                    "default": "",
                }
            ],
        }
        metadata: Dict[str, Any] = {
            "runtime_generated": True,
            "runtime_notice": REPEAT_RECOVERY_NOTICE,
            "stop_reason": stop_reason,
            "needs_user_input": True,
        }
        if pattern:
            metadata["repeat_pattern"] = {
                key: pattern[key]
                for key in (
                    "mode",
                    "period",
                    "cycles",
                    "partial",
                    "suffix_duplicate",
                )
                if key in pattern
            }
        if recovery_metadata:
            metadata.update(recovery_metadata)

        return MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=(
                f"{notice}\n\n"
                f"<questionnaire>{json.dumps(payload, ensure_ascii=False)}</questionnaire>"
            ),
            message_type=MessageType.ASSISTANT_TEXT.value,
            agent_name=self.agent_name,
            metadata=metadata,
        )

    @staticmethod
    def _mark_loop_recovery_pending(session_context: SessionContext) -> None:
        session_context.audit_status["completion_status"] = "need_user_input"
        session_context.audit_status["repeat_recovery_pending"] = True

    def _build_max_loop_questionnaire(
        self, *, max_loop_count: int, language: str = "en"
    ) -> MessageChunk:
        notice = t(
            "runtime.max_loop.notice",
            language,
            params={"max_loop_count": max_loop_count},
        )
        continue_label = t("runtime.max_loop.continue", language)
        payload = {
            "title": t("runtime.max_loop.title", language),
            "questions": [
                {
                    "type": "single_choice",
                    "text": t("runtime.max_loop.question", language),
                    "options": [continue_label],
                    "default": continue_label,
                }
            ],
        }
        questionnaire_yaml = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
        ).strip()
        return MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=f"{notice}\n\n```questionnaire\n{questionnaire_yaml}\n```",
            message_type=MessageType.ASSISTANT_TEXT.value,
            agent_name=self.agent_name,
            metadata={
                "runtime_generated": True,
                "runtime_notice": MAX_LOOP_NOTICE,
                "stop_reason": "max_loop_count",
                "needs_user_input": True,
                "max_loop_count": max_loop_count,
            },
        )

    @staticmethod
    def _latest_user_is_repeat_recovery_response(
        messages: List[MessageChunk],
    ) -> bool:
        for message in reversed(messages or []):
            if message.role != MessageRole.USER.value:
                continue
            content = message.content
            if not isinstance(content, str):
                return False
            for match in SAGE_QUESTIONNAIRE_RESPONSE_PATTERN.finditer(content):
                try:
                    payload = json.loads(match.group("payload"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                answers = payload.get("answers") if isinstance(payload, dict) else None
                if not isinstance(answers, list):
                    continue
                if any(
                    isinstance(answer, dict)
                    and answer.get("question_id") == REPEAT_RECOVERY_QUESTION_ID
                    for answer in answers
                ):
                    return True
            return False
        return False

    async def run_stream(
        self,
        session_context: SessionContext,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        if not session_context.tool_manager:
            raise ValueError("ToolManager is not initialized in SessionContext")
        session_id = session_context.session_id
        if self._should_abort_due_to_session(session_context):
            return
        tool_manager = session_context.tool_manager

        # 从会话管理中，获取消息管理实例
        message_manager = session_context.message_manager
        if self._latest_user_is_repeat_recovery_response(
            getattr(message_manager, "messages", [])
        ):
            clear_loop_signatures = getattr(
                message_manager, "clear_loop_signatures", None
            )
            if callable(clear_loop_signatures):
                clear_loop_signatures()
            session_context.audit_status.pop("completion_status", None)
            session_context.audit_status["repeat_recovery_started"] = True
            logger.info(
                "SimpleAgent: 用户已回答重复执行恢复问卷，清空旧循环签名并开始新的执行窗口"
            )
        # 从消息管理实例中，获取满足context 长度限制的消息
        history_messages = message_manager.extract_all_context_messages(
            recent_turns=20, last_turn_user_only=False
        )

        # 获取后续可能使用到的工具建议
        # 如果 audit_status 中有建议的工具，使用建议的工具；否则使用所有可用工具
        if tool_manager:
            suggested_tools = session_context.audit_status.get("suggested_tools", [])
            if not suggested_tools:
                # 使用所有可用工具名称列表
                try:
                    tools_list = tool_manager.list_tools_simplified()
                    suggested_tools = [
                        t.get("name", "") for t in tools_list if t.get("name")
                    ]
                except Exception:
                    suggested_tools = []
        else:
            suggested_tools = []
        # 准备工具列表
        tools_json = self._prepare_tools(tool_manager, suggested_tools, session_context)
        async for chunks in self._execute_loop(
            messages_input=history_messages,
            tools_json=tools_json,
            tool_manager=tool_manager,  # pyright: ignore[reportArgumentType]
            session_id=session_id or "",
            session_context=session_context,
        ):
            for chunk in chunks:
                chunk.session_id = session_id
            yield chunks

    def _prepare_tools(
        self,
        tool_manager: Optional[Any],
        suggested_tools: List[str],
        session_context: SessionContext,
    ) -> List[Dict[str, Any]]:
        """
        准备工具列表

        Args:
            tool_manager: 工具管理器
            suggested_tools: 建议工具列表
            session_context: 会话上下文

        Returns:
            List[Dict[str, Any]]: 工具配置列表
        """
        logger.debug("SimpleAgent: 准备工具列表")

        if not tool_manager or not suggested_tools:
            logger.warning("SimpleAgent: 未提供工具管理器或建议工具")
            return []

        # 获取所有工具
        tools_json = tool_manager.get_openai_tools(
            lang=session_context.get_language(), fallback_chain=["en"]
        )
        tools_json = self._filter_tools_for_completion_mode(tools_json)

        # 根据建议过滤工具，并补齐基础工作台工具（仅限当前工具管理器真实可用的工具）。
        # 当状态协议启用时，ToolProxy 会把 turn_status 纳入可用工具；协议禁用时，
        # system prefix 也会同步移除 turn_status 契约，避免模型调用未提供的协议工具。
        available_tool_names = [tool["function"]["name"] for tool in tools_json]
        selected_tools = set(
            augment_with_baseline_tools(suggested_tools, available_tool_names)
        )
        if should_expose_tool_expansion(
            suggested_tools, selected_tools, available_tool_names
        ):
            selected_tools.add(TOOL_EXPAND_TOOLS)

        tools_suggest_json = [
            tool for tool in tools_json if tool["function"]["name"] in selected_tools
        ]

        if tools_suggest_json:
            tools_json = tools_suggest_json

        # 与 ToolManager/ToolProxy 一致：再排一次序，保证经过筛选后顺序仍稳定。
        tools_json.sort(key=lambda t: (t.get("function") or {}).get("name") or "")

        tool_names = [tool["function"]["name"] for tool in tools_json]
        logger.debug(f"SimpleAgent: 准备了 {len(tools_json)} 个工具: {tool_names}")

        return tools_json

    @staticmethod
    def _is_inline_questionnaire_name(name: str) -> bool:
        normalized = str(name or "").strip().lower()
        return normalized == "questionnaire" or (
            normalized.endswith("-questionnaire") and normalized != "-questionnaire"
        )

    @classmethod
    def _content_has_inline_questionnaire(cls, content: Any) -> bool:
        """Detect questionnaire request blocks without parsing natural language.

        Supported request markers are XML-style opening tags such as
        ``<movo-questionnaire>`` and fenced blocks such as
        `````movo-questionnaire```. Triple apostrophes are accepted as a
        compatibility spelling because some clients use them to avoid nesting
        Markdown fences. ``*-questionnaire-response`` is intentionally excluded.
        """
        text = cls._extract_text_content_for_judge(content).strip()
        if not text:
            return False
        text = unescape(text)

        # XML-like opening tags. Splitting is sufficient because only the tag
        # name matters; payload validation remains SelfCheckAgent's job.
        for fragment in text.split("<")[1:]:
            raw_tag = fragment.split(">", 1)[0].strip()
            if not raw_tag or raw_tag[0] in "/!?":
                continue
            tag_name = raw_tag.split(None, 1)[0].rstrip("/")
            if cls._is_inline_questionnaire_name(tag_name):
                return True

        # Fenced questionnaire blocks. Require the questionnaire name to be the
        # only info string so response tags and prose mentions do not match.
        for line in text.splitlines():
            stripped = line.strip()
            if len(stripped) < 4 or stripped[0] not in {"`", "'"}:
                continue
            fence_char = stripped[0]
            fence_len = len(stripped) - len(stripped.lstrip(fence_char))
            if fence_len < 3:
                continue
            tag_name = stripped[fence_len:].strip()
            if cls._is_inline_questionnaire_name(tag_name):
                return True
        return False

    @classmethod
    def _latest_assistant_has_inline_questionnaire(
        cls, messages_input: List[MessageChunk]
    ) -> bool:
        for message in reversed(messages_input or []):
            if message.role == MessageRole.ASSISTANT.value:
                return cls._content_has_inline_questionnaire(message.get_content())
            if message.is_user_input_message():
                return False
        return False

    @classmethod
    def _content_has_ling_action(cls, content: Any) -> bool:
        """Detect the Ling optional-action protocol marker.

        ``<ling-action ... />`` is emitted only after the current user-facing
        reply has been closed out. The buttons may start a new user-chosen
        action, but they are not unfinished work in the current execution.
        Match an actual opening tag (including HTML-escaped output), not prose
        that merely mentions the marker name.
        """
        text = cls._extract_text_content_for_judge(content).strip()
        if not text:
            return False
        text = unescape(text)
        for fragment in text.split("<")[1:]:
            raw_tag = fragment.split(">", 1)[0].strip()
            if not raw_tag or raw_tag[0] in "/!?":
                continue
            tag_name = raw_tag.split(None, 1)[0].rstrip("/").lower()
            if tag_name == "ling-action":
                return True
        return False

    @classmethod
    def _latest_assistant_has_ling_action(
        cls, messages_input: List[MessageChunk]
    ) -> bool:
        for message in reversed(messages_input or []):
            if message.role == MessageRole.ASSISTANT.value:
                return cls._content_has_ling_action(message.get_content())
            if message.is_user_input_message():
                return False
        return False

    def _normalize_task_interrupted_decision(
        self,
        reason: str,
        task_interrupted: bool,
    ) -> bool:
        """根据 reason 做轻量一致性兜底，避免输出语义与布尔值矛盾。"""
        reason_text = (reason or "").strip().lower()
        if not reason_text:
            return task_interrupted

        wait_tool_markers = [
            "waiting for tool call",
            "waiting for generation",
            "waiting for tool",
            "missing execution evidence",
            "missing tool evidence",
            "no execution evidence",
            "no tool result",
            "等待工具调用",
            "等待生成",
            "处理中",
            "缺少执行证据",
            "没有执行证据",
            "缺少工具结果",
            "没有工具结果",
            "aguardando chamada de ferramenta",
            "aguardando geração",
            "sem evidência de execução",
            "sem resultado de ferramenta",
        ]
        if any(marker in reason_text for marker in wait_tool_markers):
            return False

        wait_user_markers = [
            "waiting for user",
            "waiting user",
            "need user input",
            "need user confirmation",
            "awaiting user",
            "等待用户",
            "等待用户确认",
            "等待用户输入",
            "需要用户确认",
            "需要用户输入",
            "用户补充",
            "aguardando usuário",
            "aguardando confirmação",
            "entrada do usuário",
            "confirmação do usuário",
        ]
        if any(marker in reason_text for marker in wait_user_markers):
            return True

        return task_interrupted

    def _task_interrupted_from_judge_result(
        self,
        result: Dict[str, Any],
    ) -> bool:
        """Parse the structured outcome, with backward compatibility.

        ``decision`` is preferred because the legacy boolean conflates a
        completed task with a turn that genuinely needs user input.  Old judge
        responses remain supported while models/configurations roll forward.
        """
        raw_decision = result.get("decision")
        decision = raw_decision.strip().lower() if isinstance(raw_decision, str) else ""
        if "decision" in result:
            if decision == "continue":
                return False
            if decision in {"completed", "need_user_input", "blocked"}:
                return True
            logger.warning(
                "SimpleAgent: task_complete_judge 返回非法 decision="
                f"{raw_decision!r}，默认继续执行"
            )
            return False

        task_interrupted = self._parse_task_interrupted_value(
            result.get("task_interrupted", False)
        )
        raw_reason = result.get("reason", "")
        reason = raw_reason if isinstance(raw_reason, str) else ""
        return self._normalize_task_interrupted_decision(reason, task_interrupted)

    @staticmethod
    def _parse_task_interrupted_value(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "true":
                return True
            if normalized == "false":
                return False
        return False

    def _has_recent_assistant_summary(self, messages_input: List[MessageChunk]) -> bool:
        """判断 turn_status 之前是否存在用户可见的 assistant 收口文本。

        turn_status 的契约要求模型先输出总结、提问、确认请求或阻塞说明，
        再调用工具结束本轮。

        合法形态：
        - 上一条 LLM 输出是纯文本（``content`` 非空且无 ``tool_calls``），随后这一次
          LLM 输出只调用 turn_status —— ``messages_input`` 末尾就是该 assistant 文本。

        非法形态（之前会误判通过）：
        - 末尾是 ``tool`` 消息（说明刚跑完工具，模型还没机会写总结）；
        - 倒数第二条 assistant 既有 content 又有 tool_calls（那段文字是「我现在去做 X」
          的过渡话，不是总结）。

        判定规则：从尾部向前扫，
        - 命中 ``system``/控制消息 → 跳过（协议提示不能作为合法收口文本）；
        - 命中 ``tool`` 消息 → False（还有未消化的工具产出）；
        - 命中 assistant：有 ``tool_calls`` → False；content 非空 → True；
          content 为空且无 tool_calls → 继续向前；
        - 命中真实 user 消息 → False。
        """
        if not messages_input:
            return False

        def _content_text(content: Any) -> str:
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                buf = []
                for part in content:
                    if isinstance(part, dict):
                        t = part.get("text") or part.get("content")
                        if isinstance(t, str):
                            buf.append(t)
                return "".join(buf).strip()
            return ""

        for msg in reversed(messages_input):
            role = getattr(msg, "role", None)
            try:
                if msg.is_user_input_message():
                    return False
            except Exception:
                pass

            if role == "tool":
                return False
            if role != "assistant":
                continue

            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                return False

            if _content_text(getattr(msg, "content", None)):
                return True
            # assistant 空消息：继续向前扫描

        return False

    def _turn_status_enabled(self) -> bool:
        return is_turn_status_mode()

    def _filter_tools_for_completion_mode(
        self, tools_json: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if is_turn_status_mode():
            return tools_json
        return [
            tool
            for tool in tools_json or []
            if ((tool.get("function") or {}).get("name") or "") != "turn_status"
        ]

    def _tools_include(self, tools_json: List[Dict[str, Any]], tool_name: str) -> bool:
        for tool in tools_json or []:
            if ((tool.get("function") or {}).get("name") or "") == tool_name:
                return True
        return False

    def _turn_status_tool_names(self) -> set[str]:
        return {"turn_status"}

    def _can_request_turn_status(self, tools_json: List[Dict[str, Any]]) -> bool:
        return self._turn_status_enabled() and any(
            self._tools_include(tools_json, name)
            for name in self._turn_status_tool_names()
        )

    def _has_visible_text_without_tool_calls(self, chunks: List[MessageChunk]) -> bool:
        has_visible_assistant_text = False

        for chunk in chunks or []:
            if (
                chunk.tool_calls
                or chunk.role == MessageRole.TOOL.value
                or chunk.tool_call_id
            ):
                return False
            if chunk.role != MessageRole.ASSISTANT.value:
                continue
            if chunk.matches_message_types(
                [MessageType.REASONING_CONTENT.value, MessageType.EMPTY.value]
            ):
                continue
            content = chunk.content
            if isinstance(content, str) and content.strip():
                has_visible_assistant_text = True
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text") or part.get("content")
                        if isinstance(text, str) and text.strip():
                            has_visible_assistant_text = True
                            break

        return has_visible_assistant_text

    def _turn_status_tools_only(
        self, tools_json: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        status_tools = [
            tool
            for tool in tools_json or []
            if ((tool.get("function") or {}).get("name") or "") == "turn_status"
        ]
        return status_tools

    def _turn_status_from_tool_call(self, tool_call: Dict[str, Any]) -> str:
        raw_arguments = ((tool_call or {}).get("function") or {}).get("arguments") or ""
        try:
            parsed = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else raw_arguments
            )
        except Exception:
            return ""
        if not isinstance(parsed, dict):
            return ""
        return str(parsed.get("status") or "")

    def _allowed_tool_names(self, tools_json: List[Dict[str, Any]]) -> set[str]:
        return {
            ((tool.get("function") or {}).get("name") or "")
            for tool in tools_json or []
            if ((tool.get("function") or {}).get("name") or "")
        }

    def _is_turn_status_only_request(
        self, tools_json: List[Dict[str, Any]], force_tool_choice_required: bool
    ) -> bool:
        return force_tool_choice_required and self._allowed_tool_names(tools_json) == {
            "turn_status"
        }

    def _coerce_invalid_status_only_tool_calls(
        self,
        tool_calls: Dict[str, Any],
        language: str = "en",
    ) -> Tuple[Dict[str, Any], str, List[str]]:
        """状态补调用阶段，模型若试图调用行动工具，则转成 continue_work 状态。

        一些 OpenAI-compatible 后端会在 `tools` 仅包含 turn_status 且
        `tool_choice=required` 时仍返回不在 tools 列表里的旧工具名。这里不执行
        违规工具，而是把"想继续行动"的意图表达为 turn_status(status=continue_work)。

        返回 (改写后的 tool_calls, coerced_turn_status_id, 原始违规工具名列表)。
        调用方可据此在生成的 tool 结果上打 metadata.coerced_from，并通过
        strip_turn_status_from_llm_context 让 LLM 下一轮看到这次改写。
        """
        original_names: List[str] = []
        seen: set = set()
        for tc in tool_calls.values():
            nm = ((tc.get("function") or {}).get("name") or "").strip()
            if nm and nm not in seen:
                seen.add(nm)
                original_names.append(nm)

        original_id = (
            next(iter(tool_calls.keys()), None) or f"turn_status_{uuid.uuid4().hex[:8]}"
        )
        note_template = PromptManager().get_agent_prompt_auto(
            "turn_status_coerced_note", language=language
        )
        try:
            note = note_template.format(tools=", ".join(original_names) or "<unknown>")
        except (KeyError, IndexError):
            note = note_template
        new_tool_calls = {
            original_id: {
                "id": original_id,
                "type": "function",
                "function": {
                    "name": "turn_status",
                    "arguments": json.dumps(
                        {"status": "continue_work", "note": note},
                        ensure_ascii=False,
                    ),
                },
            }
        }
        return new_tool_calls, original_id, original_names

    def _should_request_turn_status_after_text_response(
        self,
        chunks: List[MessageChunk],
        tools_json: List[Dict[str, Any]],
    ) -> bool:
        """纯文本响应之后，下一次请求只允许补 turn_status。

        这里刻意只看消息结构，不看自然语言内容：
        - 有 assistant 可见文本；
        - 没有任何 tool_calls；
        - turn_status 当前可用。

        这更接近 Codex / Claude Code 的收口方式：assistant 已经给出自然语言
        交付时，宿主层要求模型补协议性的 turn_status 标记，
        不再开放行动工具，避免模型继续改 todo 或重复执行。
        """
        if not self._can_request_turn_status(tools_json):
            return False

        return self._has_visible_text_without_tool_calls(chunks)

    async def _must_continue_by_rules(self, messages_input: List[MessageChunk]) -> bool:
        """通过确定性规则判断是否必须继续执行

        返回 True 表示必须继续执行（task_interrupted = False）
        返回 False 表示未命中确定性规则，需要进入 LLM 判断

        这些规则基于客观事实，尽量保证误判率接近 0。

        说明：宽泛的"处理中关键词"规则已下线（多语种下脆弱、且对反问用户场景容易误判导致死循环）。
        现在仅保留高置信度规则：
        - 规则 1：最后一条是 tool 调用结果
        - 规则 2：工具调用失败的过程消息
        - 规则 3：assistant 以「继续标点」结尾且最近一条不是真实 user 消息
        """
        if not messages_input:
            return False

        last_message = messages_input[-1]

        # 规则1：最后一条消息是 tool 调用结果
        if last_message.role == "tool":
            logger.debug(
                "[SimpleAgent] must_continue 规则1命中：最后一条消息是 tool 结果，必须继续"
            )
            return True

        # 规则2：最后一条消息是工具调用错误结果（如参数解析失败等）
        if last_message.matches_message_types(
            [MessageType.AGENT_EXECUTION_ERROR.value]
        ):
            metadata = last_message.metadata or {}
            if metadata.get("runtime_diagnostic_source") == "tool_call_argument_parse":
                logger.debug(
                    "[SimpleAgent] must_continue 规则2命中：工具调用参数解析失败，必须继续"
                )
                return True

        if last_message.matches_message_types([MessageType.DO_SUBTASK_RESULT.value]):
            content = last_message.content or ""
            if any(mark in content for mark in ["参数解析失败", "工具调用失败"]):
                logger.debug(
                    "[SimpleAgent] must_continue 规则2命中：工具调用失败，必须继续"
                )
                return True

        # 规则3：assistant 文本以继续标点结尾时强制继续；
        # 但若最后一条是真实 user 输入则不触发（避免反问用户被误判）
        if (
            last_message.role == MessageRole.ASSISTANT.value
            and (last_message.content or "").strip()  # pyright: ignore[reportAttributeAccessIssue]
        ):
            content = last_message.content
            stripped = content.strip()  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
            if stripped:
                last_char = stripped[-1]
                continue_punctuations = [":", "："]
                if last_char in continue_punctuations or stripped.endswith("..."):
                    logger.debug(
                        "[SimpleAgent] must_continue 规则3命中：assistant 文本以继续标点结尾，必须继续"
                    )
                    return True

        return False

    async def _get_task_complete_decision(
        self,
        messages_input: List[MessageChunk],
        session_id: str,
        tool_manager: Optional[ToolManager],
        session_context: SessionContext,
        tools_json: Optional[List[Dict[str, Any]]] = None,
    ) -> TaskCompleteDecision:
        """判断任务是否应该中断（完成/等待用户）

        两层策略：
        1. 先用确定性规则判断是否必须继续执行；
        2. 如果没有命中规则，再调用 LLM 进行综合判断。
        """
        # Inline Questionnaire 是明确的等待用户协议，比普通继续规则和 LLM
        # judge 优先级更高。即使 Todo 尚未完成，也必须保留 need_user_input。
        if self._latest_assistant_has_inline_questionnaire(messages_input):
            audit_status = getattr(session_context, "audit_status", None)
            if isinstance(audit_status, dict):
                audit_status["completion_status"] = "need_user_input"
            return TaskCompleteDecision(
                task_interrupted=True,
                reason="inline questionnaire requires user input",
            )

        # ling-action 是 Ling 客户端约定的收口标记。按钮代表用户可以另起一个
        # 可选动作，不代表当前执行还有待完成步骤；不要再交给 LLM judge 猜测。
        if self._latest_assistant_has_ling_action(messages_input):
            audit_status = getattr(session_context, "audit_status", None)
            if isinstance(audit_status, dict):
                audit_status["completion_status"] = "need_user_input"
            return TaskCompleteDecision(
                task_interrupted=True,
                reason="ling-action marks a closed reply awaiting an optional user action",
            )

        # 第一层：确定性规则
        if await self._must_continue_by_rules(messages_input):
            return TaskCompleteDecision(task_interrupted=False)

        # 第二层：LLM 综合判断
        # 只提取最后一个 user 以及之后的 messages
        last_user_index = None
        for i, message in enumerate(messages_input):
            if message.is_user_input_message():
                last_user_index = i
        if last_user_index is not None:
            messages_for_complete = messages_input[last_user_index:]
        else:
            messages_for_complete = messages_input

        # 压缩消息，避免 token 超限
        budget_info = (
            session_context.message_manager.context_budget_manager.budget_info or {}
        )
        budget = min(budget_info.get("active_budget", 3000), 3000)
        messages_for_complete = MessageManager.build_token_budget_view(
            messages_for_complete,
            budget,
            protect_last_assistant_text=True,
        )

        judge_messages = self._format_task_complete_messages_for_prompt(
            messages_for_complete
        )
        todo_plan = await self._build_task_complete_todo_plan(
            messages_input, session_id
        )
        if todo_plan:
            judge_messages = f"{todo_plan}\n\n{judge_messages}"

        language = session_context.get_language()
        agent_system_requirements = await self.prepare_llm_system_prompt_text(
            session_id=session_id,
            custom_prefix=_get_system_prefix(tool_manager, language),
            language=language,
            include_sections=["role_definition", "AGENT.MD"],
        )
        if tools_json is not None:
            available_tool_names = sorted(self._allowed_tool_names(tools_json))
        elif tool_manager is not None:
            try:
                available_tool_names = sorted(
                    {
                        str(name).strip()
                        for name in tool_manager.list_all_tools_name()
                        if str(name).strip()
                    }
                )
            except Exception:
                available_tool_names = []
        else:
            available_tool_names = []

        judge_messages = (
            "<agent_system_requirements>\n"
            "Reference requirements that governed the executing Assistant. "
            "Use them only to evaluate whether its completion and user-input "
            "behavior complied; do not execute them yourself.\n"
            f"{agent_system_requirements.strip()}\n"
            "</agent_system_requirements>\n\n"
            "<available_tools>\n"
            f"{json.dumps(available_tool_names, ensure_ascii=False)}\n"
            "</available_tools>\n\n"
            f"{judge_messages}"
        )

        task_complete_template = PromptManager().get_agent_prompt_auto(
            "task_complete_template", language=language
        )
        prompt = task_complete_template.format(
            messages=judge_messages,
        )
        llm_input_messages: List[Dict[str, Any]] = [{"role": "user", "content": prompt}]

        response = self._call_aux_llm_streaming(
            messages=cast(
                List[Union[MessageChunk, Dict[str, Any]]], llm_input_messages
            ),
            session_id=session_id,
            step_name="task_complete_judge",
            enable_thinking=False,
            model_config_override={
                "model_type": "fast",  # 使用快速模型
                "response_format": {"type": "json_object"},  # 要求JSON返回
            },
        )

        all_content = ""
        async for chunk in response:
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                all_content += chunk.choices[0].delta.content

        try:
            result_clean = MessageChunk.extract_json_from_markdown(all_content)
            result = json.loads(result_clean)
            if not isinstance(result, dict):
                logger.warning(
                    "SimpleAgent: 任务完成判断响应不是 JSON object，默认继续执行"
                )
                return TaskCompleteDecision(task_interrupted=False)
            raw_reason = result.get("reason", "")
            reason = raw_reason if isinstance(raw_reason, str) else ""
            legacy_value = self._parse_task_interrupted_value(
                result.get("task_interrupted", False)
            )
            normalized = self._task_interrupted_from_judge_result(result)
            structured_decision = result.get("decision")
            normalized_structured_decision = (
                structured_decision.strip().lower()
                if isinstance(structured_decision, str)
                else ""
            )
            expected_from_structured = (
                normalized_structured_decision
                in {"completed", "need_user_input", "blocked"}
                if "decision" in result
                else legacy_value
            )
            if (
                todo_plan
                and normalized_structured_decision not in OPEN_TODO_ALLOWED_DECISIONS
            ):
                rejected_decision = normalized_structured_decision or "<missing>"
                logger.warning(
                    "SimpleAgent: 权威 Todo 仍有未完成项，只允许 continue / "
                    "need_user_input / blocked；已拒绝 "
                    f"decision={rejected_decision}"
                )
                normalized = False
                reason = "authoritative Todo still has pending/in_progress items"
            if normalized != expected_from_structured:
                logger.warning(
                    f"SimpleAgent: 任务完成判断存在语义冲突，已自动修正。reason={reason}, "
                    f"decision={structured_decision}, task_interrupted={legacy_value} -> {normalized}"
                )
            logger.info(
                f"SimpleAgent: 任务完成 LLM 判断结果: {result}, normalized={normalized}"
            )
            return TaskCompleteDecision(task_interrupted=normalized, reason=reason)
        except json.JSONDecodeError:
            logger.warning(
                "SimpleAgent: 解析任务完成判断响应时JSON解码错误，默认继续执行"
            )
            return TaskCompleteDecision(task_interrupted=False)

    @staticmethod
    def _bounded_todo_field(value: Any) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= TASK_COMPLETE_TODO_FIELD_MAX_CHARS:
            return text
        return text[:TASK_COMPLETE_TODO_FIELD_MAX_CHARS].rstrip() + "... [truncated]"

    @staticmethod
    def _todo_task_status(task: Dict[str, Any]) -> str:
        status = str(task.get("status") or "").strip().lower()
        if not status:
            status = "completed" if task.get("completed") is True else "pending"
        return status

    @classmethod
    def _latest_todo_tasks_from_messages(
        cls, messages: List[MessageChunk]
    ) -> Optional[List[Dict[str, Any]]]:
        todo_call_ids = set()
        for msg in messages:
            for tool_call in msg.tool_calls or []:
                if cls._tool_call_name_for_judge(tool_call) == "todo_write":
                    call_id = cls._tool_call_id_for_judge(tool_call)
                    if call_id:
                        todo_call_ids.add(call_id)

        latest_tasks: Optional[List[Dict[str, Any]]] = None
        for msg in messages:
            if msg.role != MessageRole.TOOL.value:
                continue
            is_todo_result = msg.tool_call_id in todo_call_ids
            if not is_todo_result:
                is_todo_result = cls._tool_result_name_for_judge(msg) == "todo_write"
            if not is_todo_result:
                continue
            raw_content = msg.get_content()
            if not isinstance(raw_content, str):
                continue
            try:
                payload = json.loads(raw_content)
            except (TypeError, json.JSONDecodeError):
                continue
            tasks = payload.get("tasks") if isinstance(payload, dict) else None
            if isinstance(tasks, list):
                latest_tasks = [task for task in tasks if isinstance(task, dict)]
        return latest_tasks

    async def _build_task_complete_todo_plan(
        self, messages: List[MessageChunk], session_id: str
    ) -> str:
        tasks = self._latest_todo_tasks_from_messages(messages)
        source = "latest_todo_write_result"
        if tasks is None:
            source = "current_session_todo"
            try:
                tasks = await ToDoTool().read_tasks(session_id)
            except Exception as exc:
                logger.warning(
                    f"SimpleAgent: task_complete_judge 读取当前 Todo 计划失败: {exc}"
                )
                return ""
        if not isinstance(tasks, list) or not tasks:
            return ""
        if not any(self._todo_task_status(task) != "completed" for task in tasks):
            return ""

        compact_tasks = []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            item = {
                "id": self._bounded_todo_field(task.get("id")),
                "status": self._todo_task_status(task),
                "content": self._bounded_todo_field(
                    task.get("content") or task.get("name") or task.get("title")
                ),
            }
            conclusion = self._bounded_todo_field(task.get("conclusion"))
            if conclusion:
                item["conclusion"] = conclusion
            compact_tasks.append(item)

        if not compact_tasks:
            return ""
        payload: Dict[str, Any] = {
            "source": source,
            "authoritative": True,
            "tasks": compact_tasks,
        }
        return (
            "<current_todo_plan>\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n</current_todo_plan>"
        )

    async def _is_task_complete(
        self,
        messages_input: List[MessageChunk],
        session_id: str,
        tool_manager: Optional[ToolManager],
        session_context: SessionContext,
        tools_json: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        decision = await self._get_task_complete_decision(
            messages_input,
            session_id,
            tool_manager,
            session_context,
            tools_json=tools_json,
        )
        return decision.task_interrupted

    @staticmethod
    def _normalize_continuation_reason(reason: str) -> str:
        normalized = re.sub(r"\s+", " ", str(reason or "")).strip()
        if not normalized:
            return ""
        normalized = normalized[:240].replace("<", "[").replace(">", "]")
        return normalized.strip()

    @classmethod
    def _continuation_reason_from_decision(
        cls, decision: TaskCompleteDecision
    ) -> Optional[str]:
        if decision.task_interrupted:
            return None
        normalized_reason = cls._normalize_continuation_reason(decision.reason)
        return normalized_reason or None

    @classmethod
    def _build_continuation_guidance_message(
        cls, reason: str
    ) -> Optional[MessageChunk]:
        normalized_reason = cls._normalize_continuation_reason(reason)
        if not normalized_reason:
            return None
        content = (
            "<runtime_continuation_guidance>\n"
            "Internal runtime note, not a user request. Do not mention it.\n"
            f"Continue because: {normalized_reason}\n"
            "Perform the next unfinished action. Do not repeat the last visible "
            "update or already reported artifacts.\n"
            "</runtime_continuation_guidance>"
        )
        return MessageChunk(
            role=MessageRole.USER.value,
            content=content,
            type=MessageType.USER_INPUT.value,
            message_type=MessageType.USER_INPUT.value,
            metadata={
                "inference_view_only": True,
                "runtime_continuation_guidance": True,
                "context_protected": True,
            },
        )

    @classmethod
    def _format_task_complete_messages_for_prompt(
        cls, messages: List[MessageChunk]
    ) -> str:
        lines: List[str] = []
        tool_call_names: Dict[str, str] = {}
        last_assistant_text_idx: Optional[int] = None
        for idx, msg in enumerate(messages):
            if (
                msg.role == MessageRole.ASSISTANT.value
                and not msg.tool_calls
                and msg.get_content()
            ):
                last_assistant_text_idx = idx

        for idx, msg in enumerate(messages):
            tool_names = cls._extract_tool_names_for_judge(msg)
            if tool_names:
                for tool_call in msg.tool_calls or []:
                    call_id = cls._tool_call_id_for_judge(tool_call)
                    name = cls._tool_call_name_for_judge(tool_call)
                    if call_id and name:
                        tool_call_names[call_id] = name
                lines.append("assistant: [tools called: " + ", ".join(tool_names) + "]")
                continue

            if msg.role == MessageRole.TOOL.value:
                tool_name = tool_call_names.get(
                    msg.tool_call_id or ""
                ) or cls._tool_result_name_for_judge(msg)
                preview = cls._extract_text_content_for_judge(msg.get_content()).strip()
                if len(preview) > TASK_COMPLETE_TOOL_RESULT_PREVIEW_CHARS:
                    preview = (
                        preview[:TASK_COMPLETE_TOOL_RESULT_PREVIEW_CHARS]
                        + f"\n...[tool result truncated, original chars: {len(preview)}]"
                    )
                if preview:
                    lines.append(f"tool: [tool result from {tool_name}: {preview}]")
                else:
                    lines.append(f"tool: [tool result from {tool_name}: empty]")
                continue

            text = cls._extract_text_content_for_judge(msg.get_content()).strip()
            if not text:
                continue
            if idx != last_assistant_text_idx and len(text) > 2000:
                text = text[:2000] + f"\n...[truncated, original chars: {len(text)}]"
            lines.append(f"{msg.role}: {text}")

        return "\n\n".join(lines)

    @staticmethod
    def _extract_tool_names_for_judge(msg: MessageChunk) -> List[str]:
        tool_names: List[str] = []
        for tool_call in msg.tool_calls or []:
            name = SimpleAgent._tool_call_name_for_judge(tool_call)
            if name:
                tool_names.append(name)
        return tool_names

    @staticmethod
    def _tool_call_id_for_judge(tool_call: Any) -> Optional[str]:
        if isinstance(tool_call, dict):
            call_id = tool_call.get("id")
        else:
            call_id = getattr(tool_call, "id", None)
        return call_id if isinstance(call_id, str) and call_id else None

    @staticmethod
    def _tool_call_name_for_judge(tool_call: Any) -> Optional[str]:
        if isinstance(tool_call, dict):
            function = tool_call.get("function")
            if isinstance(function, dict):
                name = function.get("name")
            else:
                name = getattr(function, "name", None)
        else:
            function = getattr(tool_call, "function", None)
            name = getattr(function, "name", None)
        return name if isinstance(name, str) and name else None

    @staticmethod
    def _tool_result_name_for_judge(msg: MessageChunk) -> str:
        metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
        tool_name = metadata.get("tool_name") or metadata.get("name")
        if isinstance(tool_name, str) and tool_name:
            return tool_name
        return msg.tool_call_id or "unknown"

    @staticmethod
    def _extract_tool_result_payload(content: Any) -> Optional[Dict[str, Any]]:
        """将工具返回内容转成 dict，失败时返回 None。"""
        if content is None:
            return None
        parsed = None
        if isinstance(content, dict):
            return content
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except Exception:
                return None
        else:
            return None

        if not isinstance(parsed, dict):
            return None
        if isinstance(parsed.get("content"), (dict, str)):
            try:
                nested = (
                    parsed["content"]
                    if not isinstance(parsed["content"], str)
                    else json.loads(parsed["content"])
                )
                if isinstance(nested, dict):
                    return nested
            except Exception:
                pass
        return parsed

    @staticmethod
    def _extract_text_content_for_judge(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return redact_base64_data_urls_in_value(content)
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(redact_base64_data_urls_in_value(text))
                elif item.get("type") == "image_url":
                    parts.append("[image attached]")
                else:
                    item_type = item.get("type") or "unknown"
                    parts.append(f"[{item_type} attachment]")
            return "\n".join(parts)
        return ""

    async def _execute_loop(
        self,
        messages_input: List[MessageChunk],
        tools_json: List[Dict[str, Any]],
        tool_manager: Optional[ToolManager],
        session_id: str,
        session_context: SessionContext,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        执行主循环

        Args:
            messages_input: 输入消息列表
            tools_json: 工具配置列表
            tool_manager: 工具管理器
            session_id: 会话ID

        Yields:
            List[MessageChunk]: 执行结果消息块
        """

        if self._should_abort_due_to_session(session_context):
            return
        all_new_response_chunks: List[MessageChunk] = []
        loop_count = 0
        repeat_pattern_hits = 0
        # 连续错误轮次快速熔断：LLM 因温度导致每轮措辞不同，哈希签名无法命中，
        # 但错误内容本身是固定的，可以快速检测。
        consecutive_error_key: Optional[str] = None
        consecutive_error_hits = 0
        # 从session context 获取 max_loop_count；缺失则直接报错，避免静默兜底
        max_loop_count = session_context.agent_config.get("max_loop_count")
        if max_loop_count is None:
            raise ValueError(
                "SimpleAgent requires session_context.agent_config.max_loop_count"
            )
        logger.info(f"SimpleAgent: 开始执行主循环，最大循环次数：{max_loop_count}")

        # 从 MessageManager 加载跨调用的签名历史，支持检测跨 SimpleAgent 调用的循环模式
        message_manager = session_context.message_manager
        recent_signatures: List[str] = message_manager.get_recent_loop_signatures()
        logger.debug(f"SimpleAgent: 加载历史签名 {len(recent_signatures)} 个")
        force_tool_choice_auto_next = False
        force_tool_choice_required_next = False
        turn_status_only_next = False
        consecutive_plain_text_direct_responses = 0
        pending_continuation_reason: Optional[str] = None
        while True:
            if self._should_abort_due_to_session(session_context):
                break
            loop_count += 1
            logger.info(f"SimpleAgent: 循环计数: {loop_count}")

            if loop_count > max_loop_count:
                logger.warning(f"SimpleAgent: 循环次数超过 {max_loop_count}，终止循环")
                questionnaire = self._build_max_loop_questionnaire(
                    max_loop_count=max_loop_count,
                    language=session_context.get_language(),
                )
                self._mark_loop_recovery_pending(session_context)
                yield [questionnaire]
                break

            # 先把上一轮 assistant/tool 结果合并进本轮请求视图。
            # 注入消息只用这个请求视图判断 tool_call 是否闭合，避免把已落盘的
            # tool result 再写回 session ledger 造成重复。
            messages_input = MessageManager.merge_new_messages_to_old_messages(
                cast(
                    List[Union[MessageChunk, Dict[str, Any]]], all_new_response_chunks
                ),
                cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input),
            )
            all_new_response_chunks = []

            # Drain "运行期注入的引导用户消息"：在本轮 LLM 请求之前消费掉。
            # 持久注入会写入 message_manager；transient 注入只进入本轮 LLM 请求，不 yield 给 SSE。
            injected = self._consume_user_injections(
                session_context, ledger_messages=messages_input
            )
            if injected:
                messages_input = list(messages_input) + list(injected)
                visible_injected = self._visible_user_injections(injected)
                if visible_injected:
                    yield visible_injected

            current_turn_status_only = turn_status_only_next
            turn_status_only_next = False
            current_force_tool_choice_required = force_tool_choice_required_next
            force_tool_choice_required_next = False
            current_continuation_reason = pending_continuation_reason
            pending_continuation_reason = None
            if current_turn_status_only:
                logger.info(
                    "SimpleAgent: 上一轮纯文本无工具调用，本轮仅开放 turn_status 并启用 tool_choice=required"
                )

            if (
                session_context.audit_status.pop("tools_expanded", False)
                and tool_manager
            ):
                refreshed_suggested_tools = session_context.audit_status.get(
                    "suggested_tools", []
                )
                if not refreshed_suggested_tools:
                    try:
                        tools_list = tool_manager.list_tools_simplified()
                        refreshed_suggested_tools = [
                            t.get("name", "") for t in tools_list if t.get("name")
                        ]
                    except Exception:
                        refreshed_suggested_tools = []
                tools_json = self._prepare_tools(
                    tool_manager, refreshed_suggested_tools, session_context
                )
                logger.info(
                    "SimpleAgent: 工具扩展后已刷新本轮工具列表: "
                    f"{[tool['function']['name'] for tool in tools_json]}"
                )

            # 调用LLM
            should_break = False
            current_tools_json = (
                self._turn_status_tools_only(tools_json)
                if current_turn_status_only
                else tools_json
            )
            direct_response_state = {"had_tool_calls": False}
            async for chunks, is_complete in self._call_llm_and_process_response(
                messages_input=messages_input,
                tools_json=current_tools_json,
                tool_manager=tool_manager,
                session_id=session_id,
                force_tool_choice_required=(
                    current_turn_status_only or current_force_tool_choice_required
                ),
                force_tool_choice_auto=force_tool_choice_auto_next,
                direct_response_state=direct_response_state,
                continuation_reason=current_continuation_reason,
            ):
                non_empty_chunks = [
                    c for c in chunks if (c.message_type != MessageType.EMPTY.value)
                ]
                if len(non_empty_chunks) > 0:
                    all_new_response_chunks.extend(deepcopy(non_empty_chunks))
                yield chunks
                if is_complete:
                    should_break = True
                    break

            force_tool_choice_auto_next = False

            if should_break:
                break

            if self._should_request_turn_status_after_text_response(
                all_new_response_chunks, tools_json
            ):
                if current_turn_status_only:
                    logger.warning(
                        "SimpleAgent: turn_status-only 阶段模型仍未调用 turn_status，暂停避免循环"
                    )
                    questionnaire = self._build_repeat_recovery_questionnaire(
                        language=session_context.get_language(),
                        stop_reason="turn_status_protocol_loop",
                    )
                    self._mark_loop_recovery_pending(session_context)
                    yield [questionnaire]
                    break
                turn_status_only_next = True

            # 检查是否应该停止
            if self._should_stop_execution(all_new_response_chunks):
                logger.info("SimpleAgent: 检测到停止条件，终止执行")
                break

            # 快速错误熔断：LLM 温度导致签名哈希不同，但错误内容固定可直接比对。
            # 根据错误类型设置不同的容忍阈值：
            #   TOOL_REJECTED（工具调用被拒绝）→ 1次即熔断，根本无法执行无需重试
            #   其他错误（超时/参数错误/未知）→ 连续2次熔断，给一次重试机会
            error_chunks_this_turn = [
                c
                for c in all_new_response_chunks
                if is_execution_error_message_type(c.message_type)
                and (c.content or "").strip()  # pyright: ignore[reportAttributeAccessIssue]
            ]
            if error_chunks_this_turn:
                error_key = "|".join(
                    (c.content or "").strip()[:120]  # pyright: ignore[reportAttributeAccessIssue]
                    for c in error_chunks_this_turn  # pyright: ignore[reportAttributeAccessIssue]
                )
                # 识别错误类别
                error_category = self._classify_error_category(error_chunks_this_turn)
                fuse_threshold = 2

                if error_key == consecutive_error_key:
                    consecutive_error_hits += 1
                else:
                    consecutive_error_key = error_key
                    consecutive_error_hits = 1

                if consecutive_error_hits >= fuse_threshold:
                    logger.warning(
                        f"SimpleAgent: [{error_category}] 连续 {consecutive_error_hits} 轮出现相同错误，熔断停止。"
                        f"错误摘要: {error_key[:80]}"
                    )
                    questionnaire = self._build_repeat_recovery_questionnaire(
                        language=session_context.get_language(),
                        stop_reason="consecutive_execution_error",
                        recovery_metadata={
                            "error_category": error_category,
                            "consecutive_error_hits": consecutive_error_hits,
                        },
                    )
                    self._mark_loop_recovery_pending(session_context)
                    yield [questionnaire]
                    break
            else:
                consecutive_error_key = None
                consecutive_error_hits = 0

            # 检测循环模式：支持文本与工具调用/结果混合重复
            loop_signature = self._build_loop_signature(all_new_response_chunks)
            recent_signatures.append(loop_signature)
            # 同时保存到 MessageManager，支持跨 SimpleAgent 调用检测
            message_manager.add_loop_signature(loop_signature)
            if len(recent_signatures) > 24:
                recent_signatures = recent_signatures[-24:]

            pattern = self._detect_repeat_pattern(recent_signatures)
            if pattern:
                repeat_pattern_hits += 1
                force_tool_choice_auto_next = self._should_escape_required_next_turn(
                    all_new_response_chunks,
                    pattern=pattern,
                )
                correction_message = self._build_self_correction_message(
                    pattern,
                    language=session_context.get_language(),
                )
                logger.warning(
                    f"SimpleAgent: 检测到循环模式 period={pattern['period']} cycles={pattern['cycles']} "
                    f"(hit={repeat_pattern_hits}/{self.max_repeat_pattern_hits})"
                )

                if repeat_pattern_hits >= self.max_repeat_pattern_hits:
                    logger.warning(
                        "SimpleAgent: 重复循环已达到熔断上限，停止执行并请求用户提供恢复指令。"
                    )
                    questionnaire = self._build_repeat_recovery_questionnaire(
                        pattern=pattern,
                        language=session_context.get_language(),
                    )
                    all_new_response_chunks.append(questionnaire)
                    self._mark_loop_recovery_pending(session_context)
                    yield [questionnaire]
                    break

                # 记录纠偏提示，但只允许它进入紧接着的一次 LLM 请求。
                correction_chunk = MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content=correction_message,
                    type=MessageType.AGENT_EXECUTION_ERROR.value,
                    agent_name=self.agent_name,
                    metadata=self._next_request_runtime_metadata(
                        runtime_diagnostic_source="repeat_pattern_correction"
                    ),
                )
                all_new_response_chunks.append(correction_chunk)
                # 内部有序 batch：由 FlowExecutor 先写入 ledger，再依据 metadata
                # 从所有客户端出口过滤。Team/Fibre 会等待该 batch 的落盘确认。
                yield [correction_chunk]
            else:
                repeat_pattern_hits = 0

            had_direct_tool_activity = direct_response_state.get(
                "had_tool_calls", False
            )
            plain_text_direct_response = (
                not had_direct_tool_activity
            ) and self._has_visible_text_without_tool_calls(all_new_response_chunks)

            messages_input = MessageManager.merge_new_messages_to_old_messages(
                cast(
                    List[Union[MessageChunk, Dict[str, Any]]], all_new_response_chunks
                ),
                cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input),
            )
            all_new_response_chunks = []

            if self._should_abort_due_to_session(session_context):
                break
            # 检查任务是否完成
            # 状态工具启用时由模型主动调用 turn_status 工具报告本轮状态，
            # 不再走老的 LLM 任务完成判定，避免重复消耗 token 且与状态协议互相冲突。
            # 仅在 llm_judge 模式回退到旧路径；turn_status / no_tool_call
            # 都有自己的结束信号，避免多消耗一次完成判定请求。
            if is_llm_judge_mode():
                if had_direct_tool_activity:
                    consecutive_plain_text_direct_responses = 0
                    logger.info(
                        "SimpleAgent: 本轮 direct LLM response 包含工具调用，跳过 task_complete_judge，继续让模型消费工具结果"
                    )
                elif plain_text_direct_response:
                    consecutive_plain_text_direct_responses += 1
                    if (
                        consecutive_plain_text_direct_responses >= 3
                        and not self._latest_assistant_has_inline_questionnaire(
                            messages_input
                        )
                    ):
                        logger.info(
                            "SimpleAgent: 连续三轮 direct LLM 纯文本无工具调用，终止执行"
                        )
                        questionnaire = self._build_repeat_recovery_questionnaire(
                            language=session_context.get_language(),
                            stop_reason="plain_text_no_progress",
                        )
                        self._mark_loop_recovery_pending(session_context)
                        yield [questionnaire]
                        break
                    decision = await self._get_task_complete_decision(
                        messages_input,
                        session_id,
                        tool_manager,
                        session_context,
                        tools_json=current_tools_json,
                    )
                    if decision.task_interrupted:
                        logger.info("SimpleAgent: 任务完成，终止执行")
                        break
                    pending_continuation_reason = (
                        self._continuation_reason_from_decision(decision)
                    )
                    force_tool_choice_required_next = True
                else:
                    decision = await self._get_task_complete_decision(
                        messages_input,
                        session_id,
                        tool_manager,
                        session_context,
                        tools_json=current_tools_json,
                    )
                    consecutive_plain_text_direct_responses = 0
                    if decision.task_interrupted:
                        logger.info("SimpleAgent: 任务完成，终止执行")
                        break
                    pending_continuation_reason = (
                        self._continuation_reason_from_decision(decision)
                    )

    async def _call_llm_and_process_response(
        self,
        messages_input: List[MessageChunk],
        tools_json: List[Dict[str, Any]],
        tool_manager: Optional[ToolManager],
        session_id: str,
        force_tool_choice_required: bool = False,
        force_tool_choice_auto: bool = False,
        direct_response_state: Optional[Dict[str, bool]] = None,
        continuation_reason: Optional[str] = None,
    ) -> AsyncGenerator[tuple[List[MessageChunk], bool], None]:
        try:
            live_context = self._get_live_session_context(session_id)
            language = live_context.get_language() if live_context else "en"
        except Exception:
            language = "en"

        tools_json = self._filter_tools_for_completion_mode(tools_json)
        continuation_guidance = self._build_continuation_guidance_message(
            continuation_reason or ""
        )

        async def build_complete_request(
            history_view: List[MessageChunk],
        ) -> List[MessageChunk]:
            request_messages = await self.prepare_llm_request_messages(
                session_id=session_id,
                history_messages=history_view,
                custom_prefix=_get_system_prefix(tool_manager, language),
                language=language,
            )
            if continuation_guidance is not None:
                request_messages = list(request_messages) + [continuation_guidance]
            return request_messages

        # 准备消息：提取可用消息 -> 检查压缩 -> 执行压缩
        # 通过生成器获取中间结果（tool_calls/tool result）和最终结果。
        prepared_messages = None
        try:
            prepared_iterator = self._prepare_messages_for_llm(
                messages_input,
                session_id,
                request_builder=build_complete_request,
                request_tools=tools_json,
                step_name="direct_execution",
            )
        except TypeError as exc:
            # Compatibility for custom/test subclasses overriding the historical
            # two-argument hook. Provider overflow still returns to the session
            # recovery loop; the provider boundary does not trim message roles.
            if "unexpected keyword argument" not in str(exc):
                raise
            prepared_iterator = self._prepare_messages_for_llm(
                messages_input, session_id
            )
        async for messages_chunk, is_final in prepared_iterator:
            if is_final:
                # 最终结果
                prepared_messages = messages_chunk
                break
            else:
                # 中间结果（tool_calls 或 tool result），yield 出去让上层处理
                yield (messages_chunk, False)

        if prepared_messages is None:
            logger.error("SimpleAgent: 准备消息失败，没有获得最终消息列表")
            return

        prepared_history_messages = prepared_messages
        prepared_messages = await build_complete_request(prepared_history_messages)

        logger.info(f"SimpleAgent: 准备了 {len(prepared_messages)} 条消息用于LLM")

        # 准备模型配置覆盖，包含工具信息
        model_config_override = {}

        if len(tools_json) > 0:
            model_config_override["tools"] = tools_json
            force_tool_choice_auto = (
                force_tool_choice_auto
                or self._should_escape_required_next_turn(
                    messages_input,
                    pattern=None,
                )
            )
            tool_choice = self._resolve_tool_choice(
                tools_json,
                force_tool_choice_required=force_tool_choice_required,
                force_tool_choice_auto=force_tool_choice_auto,
            )
            if tool_choice:
                model_config_override["tool_choice"] = tool_choice
        is_turn_status_only_request = self._is_turn_status_only_request(
            tools_json,
            force_tool_choice_required,
        )

        async def stream_with_context_recovery():
            nonlocal prepared_history_messages, prepared_messages
            recovery_source = prepared_history_messages
            llm_compression_attempts = 0

            while True:
                response = self._call_llm_streaming(
                    messages=cast(
                        List[Union[MessageChunk, Dict[str, Any]]], prepared_messages
                    ),
                    session_id=session_id,
                    step_name="direct_execution",
                    model_config_override=model_config_override,
                )
                try:
                    async for provider_chunk in response:
                        yield (True, provider_chunk)
                    return
                except ProviderContextWindowExceededError:
                    llm_compression_attempts += 1
                    if llm_compression_attempts > 20:
                        logger.error(
                            "SimpleAgent: provider 上下文超限恢复超过 20 次，保留原始错误"
                        )
                        raise
                    logger.warning(
                        "SimpleAgent: provider 上下文超限，启动会话级恢复；"
                        "使用大模型历史压缩，"
                        f"attempt={llm_compression_attempts}"
                    )
                    recovered_history = None
                    recovery_iterator = self._prepare_context_messages_for_llm(
                        recovery_source,
                        session_id,
                        request_builder=build_complete_request,
                        request_tools=tools_json,
                        step_name="direct_execution",
                        provider_overflow_recovery=True,
                    )
                    async for recovery_messages, is_final in recovery_iterator:
                        if is_final:
                            recovered_history = recovery_messages
                        else:
                            yield (False, (recovery_messages, False))

                    if recovered_history is None:
                        raise

                    recovery_source = recovered_history
                    prepared_history_messages = recovered_history
                    prepared_messages = await build_complete_request(
                        prepared_history_messages
                    )

        tool_calls: Dict[str, Any] = {}
        if direct_response_state is not None:
            direct_response_state["had_tool_calls"] = False
        response_message_id = str(uuid.uuid4())
        last_tool_call_id = None
        full_content_accumulator = ""
        suppressed_status_only_content = ""
        emitted_tool_call_stream = False
        # 处理流式响应块
        try:
            async for is_provider_chunk, event in stream_with_context_recovery():
                if not is_provider_chunk:
                    yield event
                    continue
                chunk = event
                # print(chunk)
                if chunk is None:
                    logger.warning(
                        f"Received None chunk from LLM response, skipping... chunk: {chunk}"
                    )
                    continue
                if chunk.choices is None:
                    logger.warning(
                        f"Received chunk with None choices, skipping... chunk: {chunk}"
                    )
                    continue
                if len(chunk.choices) == 0:
                    continue

                # 由于 AgentBase._call_llm_streaming 已经处理了 asyncio.sleep(0) 的让权
                # 这里不需要重复让权，减少不必要的调度开销

                if chunk.choices[0].delta.tool_calls:
                    self._handle_tool_calls_chunk(
                        chunk, tool_calls, last_tool_call_id or ""
                    )
                    if direct_response_state is not None:
                        direct_response_state["had_tool_calls"] = True
                    # 更新last_tool_call_id
                    for tool_call in chunk.choices[0].delta.tool_calls:
                        if tool_call.id is not None and len(tool_call.id) > 0:
                            last_tool_call_id = tool_call.id

                    emit_on_complete = (
                        os.environ.get(
                            "SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false"
                        ).lower()
                        == "true"
                    )
                    if not emit_on_complete:
                        emitted_tool_call_stream = True
                        yield (
                            [
                                MessageChunk(
                                    role=MessageRole.ASSISTANT.value,
                                    tool_calls=chunk.choices[0].delta.tool_calls,
                                    message_id=response_message_id,
                                    message_type=MessageType.TOOL_CALL.value,
                                    agent_name=self.agent_name,
                                )
                            ],
                            False,
                        )

                elif chunk.choices[0].delta.content:
                    if len(chunk.choices[0].delta.content) > 0:
                        content_piece = chunk.choices[0].delta.content
                        if is_turn_status_only_request:
                            suppressed_status_only_content += content_piece
                            continue
                        full_content_accumulator += content_piece
                        output_messages = [
                            MessageChunk(
                                role="assistant",
                                content=content_piece,
                                message_id=response_message_id,
                                message_type=MessageType.DO_SUBTASK_RESULT.value,
                                agent_name=self.agent_name,
                            )
                        ]
                        yield (output_messages, False)
                else:
                    # 先判断chunk.choices[0].delta 是否有reasoning_content 这个变量，并且不是none
                    if (
                        hasattr(chunk.choices[0].delta, "reasoning_content")
                        and chunk.choices[0].delta.reasoning_content is not None
                    ):
                        output_messages = [
                            MessageChunk(
                                role="assistant",
                                reasoning_content=chunk.choices[
                                    0
                                ].delta.reasoning_content,
                                message_id=response_message_id,
                                message_type=MessageType.REASONING_CONTENT.value,
                                agent_name=self.agent_name,
                            )
                        ]
                        yield (output_messages, False)
        except PartialStreamConsumedError as exc:
            if direct_response_state is not None:
                direct_response_state["had_tool_calls"] = bool(tool_calls)
            recovery_messages: List[MessageChunk] = []
            if emitted_tool_call_stream:
                for tool_call_id, tool_call in tool_calls.items():
                    real_tool_call_id = tool_call.get("id") or tool_call_id
                    if not real_tool_call_id or real_tool_call_id.startswith(
                        "__tool_call_index_"
                    ):
                        continue
                    tool_name = (tool_call.get("function") or {}).get("name") or ""
                    recovery_messages.append(
                        MessageChunk(
                            role=MessageRole.TOOL.value,
                            content=json.dumps(
                                {
                                    "success": False,
                                    "status": "discarded",
                                    "error": "Partial streamed tool call discarded because the LLM stream ended before a complete response.",
                                },
                                ensure_ascii=False,
                            ),
                            tool_call_id=real_tool_call_id,
                            message_type=MessageType.TOOL_CALL_RESULT.value,
                            agent_name=self.agent_name,
                            metadata={
                                "tool_name": tool_name,
                                "partial_stream_discarded": True,
                            },
                        )
                    )
            recovery_messages.append(
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content=(
                        "The model stream was interrupted while generating a tool call. "
                        "The incomplete tool call was discarded to avoid corrupting the conversation history. "
                        "Please retry the current operation."
                    ),
                    message_type=MessageType.AGENT_EXECUTION_ERROR.value,
                    agent_name=self.agent_name,
                    metadata={"partial_stream_discarded": True, "error": str(exc)},
                )
            )
            yield (recovery_messages, True)
            return

        # 处理完所有chunk后，尝试保存内容
        if direct_response_state is not None:
            direct_response_state["had_tool_calls"] = bool(tool_calls)

        if full_content_accumulator:
            try:
                save_agent_response_content(full_content_accumulator, session_id)
            except Exception as e:
                logger.error(f"SimpleAgent: Failed to save response content: {e}")

        if is_turn_status_only_request and not tool_calls:
            if suppressed_status_only_content.strip():
                logger.warning(
                    "SimpleAgent: turn_status-only 阶段模型只返回了自然语言，已隐藏该文本并暂停避免循环"
                )
            live_context = self._get_live_session_context(session_id)
            questionnaire = self._build_repeat_recovery_questionnaire(
                language=(
                    live_context.get_language() if live_context is not None else "en"
                ),
                stop_reason="turn_status_protocol_loop",
            )
            if live_context is not None:
                self._mark_loop_recovery_pending(live_context)
            yield ([questionnaire], True)
            return

        # 处理工具调用
        if len(tool_calls) > 0:
            allowed_tool_names = self._allowed_tool_names(tools_json)
            invalid_tool_names = {
                (tool_call.get("function") or {}).get("name") or ""
                for tool_call in tool_calls.values()
                if ((tool_call.get("function") or {}).get("name") or "")
                not in allowed_tool_names
            }
            coerced_turn_status_id: Optional[str] = None
            coerced_from_names: List[str] = []
            if invalid_tool_names:
                if self._is_turn_status_only_request(
                    tools_json, force_tool_choice_required
                ):
                    logger.warning(
                        f"SimpleAgent: turn_status-only 阶段模型返回了未提供的工具 {sorted(invalid_tool_names)}，"
                        "已改写为 turn_status(status=continue_work)"
                    )
                    live_ctx_for_coerce = self._get_live_session_context(session_id)
                    coerce_lang = (
                        live_ctx_for_coerce.get_language()
                        if live_ctx_for_coerce is not None
                        else "en"
                    )
                    tool_calls, coerced_turn_status_id, coerced_from_names = (
                        self._coerce_invalid_status_only_tool_calls(
                            tool_calls, language=coerce_lang
                        )
                    )
                else:
                    logger.warning(
                        f"SimpleAgent: 模型返回未提供的工具 {sorted(invalid_tool_names)}，拒绝执行"
                    )
                    streamed_rejections = (
                        self._create_streamed_tool_rejection_results(
                            tool_calls,
                            code="tool_not_available_in_request",
                        )
                        if os.environ.get(
                            "SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false"
                        ).lower()
                        != "true"
                        else []
                    )
                    yield (
                        [
                            *streamed_rejections,
                            self._create_unavailable_tool_runtime_message(
                                sorted(invalid_tool_names)
                            ),
                        ],
                        False,
                    )
                    return

            # 识别是否包含结束/状态工具调用
            termination_tool_ids = set()
            turn_status_tool_ids = set()
            continue_turn_status_ids = set()
            for tool_call_id, tool_call in tool_calls.items():
                tname = tool_call["function"]["name"]
                if tname in ["complete_task"]:
                    termination_tool_ids.add(tool_call_id)
                # 非 turn_status 模式不会下发该工具；如果历史上下文或兼容模型仍主动调用，
                # 这里继续按协议结果处理，避免拒绝→错误→循环→文本重复。
                if tname in self._turn_status_tool_names():
                    turn_status_tool_ids.add(tool_call_id)
                    if self._turn_status_from_tool_call(tool_call) == "continue_work":
                        continue_turn_status_ids.add(tool_call_id)

            # turn_status 调用契约：本「轮」（自最近一次 user 消息以后）必须已经
            # 出现过非空的 assistant 自然语言文本。情况包括：
            #   (a) 当前 LLM 调用本身就既输出了总结也调用了 turn_status；
            #   (b) 上一次 LLM 调用先产出总结，本次只单独调用 turn_status。
            # 之前只看 (a) 会把 (b) 误杀，导致模型反复被拒绝。
            has_summary = bool((full_content_accumulator or "").strip())
            if turn_status_tool_ids and not has_summary:
                has_summary = self._has_recent_assistant_summary(messages_input)
            reject_turn_status_ids = (
                turn_status_tool_ids
                if (turn_status_tool_ids and not has_summary)
                else set()
            )
            accept_turn_status_ids = (
                turn_status_tool_ids - reject_turn_status_ids - continue_turn_status_ids
            )

            emit_on_complete = (
                os.environ.get("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false").lower()
                == "true"
            )
            async for chunk in self._handle_tool_calls(
                tool_calls=tool_calls,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id or "",
                emit_tool_call_message=emit_on_complete,
                tool_call_message_id=response_message_id,
            ):
                # chunk 是 (messages, is_complete)
                messages, is_complete = chunk

                # 终止类工具：complete_task / 通过校验且非 continue_work 的 turn_status → 标记完成
                if (termination_tool_ids or accept_turn_status_ids) and not is_complete:
                    for msg in messages:
                        if msg.role == MessageRole.TOOL.value and (
                            msg.tool_call_id in termination_tool_ids
                            or msg.tool_call_id in accept_turn_status_ids
                        ):
                            logger.info(
                                f"SimpleAgent: 终止类工具 {msg.tool_call_id} 执行完成，标记本轮结束"
                            )
                            is_complete = True
                            break

                # 未通过总结校验的 turn_status：把工具结果改写为拒绝消息，并保持未完成。
                # metadata.turn_status_rejected 让 strip_turn_status_from_llm_context 放行这对 pair，
                # 模型在下一轮才能看到拒绝原因；SSE 侧仍按 tool_call_id 隐藏（_redact_hidden_tools_from_chunk）。
                if reject_turn_status_ids and not is_complete:
                    live_ctx = self._get_live_session_context(session_id)
                    rejection_lang = (
                        live_ctx.get_language() if live_ctx is not None else "en"
                    )
                    rejection = PromptManager().get_agent_prompt_auto(
                        "turn_status_rejection_message", language=rejection_lang
                    )
                    for msg in messages:
                        if (
                            msg.role == MessageRole.TOOL.value
                            and msg.tool_call_id in reject_turn_status_ids
                        ):
                            logger.warning(
                                f"SimpleAgent: turn_status 调用 {msg.tool_call_id} 缺少前置说明，已改写为拒绝消息"
                            )
                            msg.content = rejection
                            msg.metadata = {
                                **(msg.metadata or {}),
                                "turn_status_rejected": True,
                            }

                # status-only 补轮里被改写的 turn_status：在 tool 结果上打 metadata.coerced_from，
                # 让 strip_turn_status_from_llm_context 保留这对 pair，模型下一轮就能明白
                # "上次调 X 被忽略，所以现在 should_end=false"。SSE 侧仍按 tool_call_id 隐藏。
                if coerced_turn_status_id and not is_complete:
                    coerced_from_label = ",".join(coerced_from_names) or "<unknown>"
                    for msg in messages:
                        if (
                            msg.role == MessageRole.TOOL.value
                            and msg.tool_call_id == coerced_turn_status_id
                        ):
                            logger.info(
                                f"SimpleAgent: 标记 coerced turn_status 工具结果 {msg.tool_call_id} "
                                f"coerced_from={coerced_from_label}"
                            )
                            msg.metadata = {
                                **(msg.metadata or {}),
                                "coerced_from": coerced_from_label,
                            }

                yield (messages, is_complete)

        else:
            # 发送换行消息（也包含usage信息）
            output_messages = [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="\n",
                    message_id=response_message_id,
                    message_type=MessageType.DO_SUBTASK_RESULT.value,
                    agent_name=self.agent_name,
                )
            ]
            yield (output_messages, is_no_tool_call_mode())

    def _classify_error_category(self, error_chunks: List[MessageChunk]) -> str:
        """
        根据错误 chunk 内容识别错误类别，用于差异化熔断阈值和日志。

        返回值:
            "TOOL_REJECTED"  - 模型调用了未提供的工具被拒绝
            "TURN_STATUS"    - turn_status 相关拒绝
            "TIMEOUT"        - 工具执行超时
            "INVALID_ARGS"   - 工具参数非法
            "OTHER"          - 其他未分类错误
        """
        combined = " ".join((c.content or "") for c in error_chunks).lower()  # pyright: ignore[reportArgumentType,reportCallIssue]
        if (
            "未提供的工具" in combined
            or "违规工具" in combined
            or "tool not provided" in combined
        ):
            return "TOOL_REJECTED"
        if "turn_status" in combined:
            return "TURN_STATUS"
        if "timeout" in combined or "超时" in combined:
            return "TIMEOUT"
        if "参数" in combined or "argument" in combined or "invalid" in combined:
            return "INVALID_ARGS"
        return "OTHER"

    def _should_stop_execution(
        self, all_new_response_chunks: List[MessageChunk]
    ) -> bool:
        """
        判断是否应该停止执行

        Args:
            all_new_response_chunks: 响应块列表

        Returns:
            bool: 是否应该停止执行
        """
        validation_call_ids: Dict[str, str] = {}
        for msg in all_new_response_chunks:
            if msg.role != MessageRole.ASSISTANT.value:
                continue
            for tool_call in msg.tool_calls or []:
                call_id = self._tool_call_id_for_judge(tool_call)
                if not call_id:
                    continue
                tool_name = self._tool_call_name_for_judge(tool_call)
                if tool_name:
                    validation_call_ids[call_id] = tool_name

        if validation_call_ids:
            for msg in all_new_response_chunks:
                if (
                    msg.role != MessageRole.TOOL.value
                    or not msg.tool_call_id
                    or validation_call_ids.get(msg.tool_call_id)
                    != QUESTIONNAIRE_ASYNC_TOOL_NAME
                ):
                    continue
                payload = self._extract_tool_result_payload(msg.get_content())
                if not isinstance(payload, dict):
                    continue
                if payload.get("success") is True and (
                    payload.get("validation_passed") is True
                    or payload.get("status") in QUESTIONNAIRE_ASYNC_SUCCESS_STATUSES
                    or payload.get("should_end") is True
                ):
                    logger.info(
                        "SimpleAgent: questionnaire_async 参数通过，终止本轮会话"
                    )
                    return True

        if len(all_new_response_chunks) == 0:
            logger.info("SimpleAgent: 没有更多响应块，停止执行")
            return True

        # 如果所有响应块都没有工具调用且没有内容，就停止执行
        if all(
            item.tool_calls is None and (item.content is None or item.content == "")
            for item in all_new_response_chunks
        ):
            logger.info("SimpleAgent: 没有更多响应块，停止执行")
            return True

        return False

    async def _prepare_messages_for_llm(
        self,
        messages_input: List[MessageChunk],
        session_id: str,
        request_builder=None,
        request_tools=None,
        step_name: str = "llm_call",
        provider_overflow_recovery: bool = False,
    ) -> AsyncGenerator[tuple[List[MessageChunk], bool], None]:
        """
        准备用于 LLM 的消息列表
        包括：提取可用消息 -> 检查是否需要压缩 -> 执行压缩 -> 必要时调用工具压缩

        通过 yield 返回中间结果（tool_calls 和 tool 结果）以及最终结果

        Args:
            messages_input: 输入消息列表
            session_id: 会话ID

        Yields:
            tuple[List[MessageChunk], bool]: (消息列表, 是否是最终结果)
                - 可能 yield 压缩工具的 tool_calls (is_final=False)
                - 可能 yield 压缩工具的 tool result (is_final=False)
                - 最后 yield 最终的消息列表 (is_final=True)
        """
        async for messages_chunk, is_final in self._prepare_context_messages_for_llm(
            messages_input,
            session_id,
            request_builder=request_builder,
            request_tools=request_tools,
            step_name=step_name,
            provider_overflow_recovery=provider_overflow_recovery,
        ):
            yield (messages_chunk, is_final)
