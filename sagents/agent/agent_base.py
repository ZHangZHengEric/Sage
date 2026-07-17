from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union, AsyncGenerator, Sequence, cast
import datetime
import json
import uuid
import asyncio
import hashlib
import re
from copy import deepcopy
from sagents.utils.logger import logger
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_progress import (
    bind_tool_progress_context as _bind_tool_progress_context,
    emit_tool_progress_closed as _emit_tool_progress_closed,
)
from sagents.context.session_context import SessionContext
from sagents.context.messages.message import (
    MessageChunk,
    MessageRole,
    MessageType,
    is_message_client_visible,
)
from sagents.utils.prompt_manager import prompt_manager
from sagents.context.messages.message_manager import MessageManager
from sagents.llm.sage_openai import SageAsyncOpenAI
from sagents.llm.capabilities import create_chat_completion_with_fallback
from sagents.llm.model_capabilities import (
    build_llm_extra_body,
)
from sagents.utils.llm_request_utils import (
    format_api_error_details,
    is_unsupported_input_format_error,
)
from sagents.utils.multimodal_image import (
    process_multimodal_content as _process_multimodal_content_util,
    resolve_local_sage_url as _resolve_local_sage_url_util,
    get_mime_type as _get_mime_type_util,
)
from sagents.utils.message_sanitizer import (
    remove_orphan_tool_calls as _remove_orphan_tool_calls_util,
    drop_invalid_tool_calls as _drop_invalid_tool_calls_util,
    drop_orphan_tool_messages as _drop_orphan_tool_messages_util,
    repair_interleaved_tool_messages as _repair_interleaved_tool_messages_util,
    strip_content_when_tool_calls as _strip_content_when_tool_calls_util,
)
from sagents.utils.stream_merger import (
    merge_chat_completion_chunks as _merge_chunks_util,
)
from sagents.utils.stream_tag_parser import (
    judge_delta_content_type as _judge_delta_content_type_util,
)
from sagents.utils.i18n import t
from sagents.utils.agent_session_helper import (
    get_live_session as _get_live_session_util,
    get_live_session_context as _get_live_session_context_util,
    should_abort_due_to_session as _should_abort_due_to_session_util,
)
import traceback
import time
import os
from openai import AsyncOpenAI, APIError, RateLimitError, APIConnectionError
import httpx
from openai.types.chat import chat_completion_chunk

TOOL_CALL_CONCURRENCY_LIMIT = 10


class PartialStreamConsumedError(RuntimeError):
    """Raised when a streamed LLM response fails after chunks were yielded."""

    def __init__(self, message: str, original_error: Exception):
        super().__init__(message)
        self.original_error = original_error


def _model_config_log_summary(model_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(model_config, dict):
        return {}
    keys = (
        "base_url",
        "model",
        "max_tokens",
        "temperature",
        "top_p",
        "presence_penalty",
        "max_model_len",
        "supports_multimodal",
        "supports_structured_output",
        "fast_base_url",
        "fast_model_name",
    )
    return {key: model_config.get(key) for key in keys if key in model_config}


class AgentBase(ABC):
    """
    智能体基类

    为所有智能体提供通用功能和接口，包括消息处理、工具转换、
    流式处理和内容解析等核心功能。
    """

    RUNTIME_CONTEXT_SYSTEM_SECTIONS = {"system_context", "workspace_files"}
    RUNTIME_CONTEXT_HIDDEN_SYSTEM_CONTEXT_KEYS = {
        "sandbox_approval_mode",
        "command_policy",
    }
    FROZEN_USER_INFERENCE_METADATA_KEY = "frozen_user_inference"
    FROZEN_USER_INFERENCE_VERSION = 3

    def __init__(
        self,
        model: Optional[AsyncOpenAI] = None,
        model_config: Optional[Dict[str, Any]] = None,
        system_prefix: str = "",
    ):
        """
        初始化智能体基类

        Args:
            model: 可执行的语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        self.model = model
        self.model_config = model_config if model_config is not None else {}
        self.system_prefix = system_prefix
        self.agent_description = f"{self.__class__.__name__} agent"
        self.agent_name = self.__class__.__name__

        # 设置最大输入长度（用于安全检查，防止消息过长）
        # 实际的上下文长度由 SessionContext 中的 context_budget_manager 动态管理
        # 这里只是作为兜底的安全阈值

        configured_max_input = None
        configured_max_model = None
        if isinstance(model_config, dict):
            configured_max_input = model_config.get("max_model_input_len")
            configured_max_model = model_config.get("max_model_len")
        max_model_len = int(configured_max_model or 128000)
        requested_max_input = int(configured_max_input or max_model_len)
        self.max_model_input_len = min(requested_max_input, max_model_len)

        logger.debug(
            f"AgentBase: 初始化 {self.__class__.__name__}，模型配置: {_model_config_log_summary(model_config)}, 最大输入长度（安全阈值）: {self.max_model_input_len}"
        )

    def _get_live_session(self, session_id: Optional[str]):
        return _get_live_session_util(session_id, log_prefix=self.__class__.__name__)

    def _get_live_session_context(self, session_id: Optional[str]):
        return _get_live_session_context_util(
            session_id, log_prefix=self.__class__.__name__
        )

    @staticmethod
    def _timezone_from_current_time(value: Any) -> Optional[datetime.timezone]:
        if not isinstance(value, str):
            return None

        _, _, offset = value.rpartition(" ")
        if len(offset) != 5 or offset[0] not in "+-" or not offset[1:].isdigit():
            return None

        hours = int(offset[1:3])
        minutes = int(offset[3:5])
        if hours > 23 or minutes > 59:
            return None

        sign = 1 if offset[0] == "+" else -1
        delta = datetime.timedelta(hours=hours, minutes=minutes)
        return datetime.timezone(sign * delta)

    def _consume_user_injections(
        self,
        session_context: Optional[SessionContext],
        ledger_messages: Optional[List[Union[MessageChunk, Dict[str, Any]]]] = None,
    ) -> List[MessageChunk]:
        """Drain SessionContext 上的 pending 引导消息。

        - flush 已经把消息写入 ``message_manager``，因此返回值仅用于上层 yield 给 SSE 通道，
          以及当次 LLM 请求的 ``messages_input.extend(...)``。
        - 任何异常都吞掉，避免影响主流程。
        """
        if session_context is None:
            return []
        try:
            return session_context.flush_user_injections(ledger_messages=ledger_messages)
        except Exception as exc:
            logger.warning(
                f"{self.__class__.__name__}: flush user injections 失败: {exc}"
            )
            return []

    @staticmethod
    def _visible_user_injections(chunks: List[MessageChunk]) -> List[MessageChunk]:
        """Return injected messages that should be emitted to clients."""
        return [chunk for chunk in chunks if is_message_client_visible(chunk)]

    @staticmethod
    def _transient_user_injections(chunks: List[MessageChunk]) -> List[MessageChunk]:
        """Return injected messages that are request-only and not persisted."""
        return [
            chunk
            for chunk in chunks
            if (
                (chunk.metadata or {}).get("persist") is False
                or (chunk.metadata or {}).get("transient") is True
            )
        ]

    @staticmethod
    def _next_request_runtime_metadata(
        **extra: Any,
    ) -> Dict[str, Any]:
        """Metadata for hidden audit messages consumed by one LLM request."""

        return {
            **extra,
            "hidden_from_chat": True,
            "hide_from_chat": True,
            "sse_visible": False,
            "llm_scope": "next_request",
            "llm_state": "pending",
            "llm_consumed_by": None,
            "llm_consumed_at": None,
        }

    def _create_unavailable_tool_runtime_message(
        self,
        tool_names: Sequence[str],
    ) -> MessageChunk:
        names = sorted({name for name in tool_names if name})
        return MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=json.dumps(
                {
                    "code": "tool_not_available_in_request",
                    "tool_names": names,
                    "next_action": {
                        "tool": "tool_expand_tools",
                        "arguments": {"tool_names": names},
                    },
                },
                ensure_ascii=False,
            ),
            type=MessageType.AGENT_EXECUTION_ERROR.value,
            agent_name=self.agent_name,
            metadata=self._next_request_runtime_metadata(
                runtime_notice="unavailable_tool_rejected"
            ),
        )

    def _create_streamed_tool_rejection_results(
        self,
        tool_calls: Dict[str, Any],
        *,
        code: str,
    ) -> List[MessageChunk]:
        """Close provisional tool cards emitted by low-latency streaming mode."""

        results: List[MessageChunk] = []
        for fallback_id, tool_call in tool_calls.items():
            tool_call_id = tool_call.get("id") or fallback_id
            if not tool_call_id or str(tool_call_id).startswith("__tool_call_index_"):
                continue
            tool_name = (tool_call.get("function") or {}).get("name") or ""
            results.append(
                MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=json.dumps(
                        {
                            "status": "rejected",
                            "code": code,
                            "tool_name": tool_name,
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=str(tool_call_id),
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                    agent_name=self.agent_name,
                    metadata={
                        "tool_name": tool_name,
                        "streamed_tool_rejected": True,
                    },
                )
            )
        return results

    @abstractmethod
    async def run_stream(
        self,
        session_context: SessionContext,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        流式处理消息的抽象方法

        Args:
            session_context: 会话上下文
            tool_manager: 可选的工具管理器
            session_id: 会话ID

        Yields:
            List[MessageChunk]: 流式输出的消息块
        """
        if False:
            yield []

    def _remove_tool_call_without_id(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """移除 tool_calls 没有对应 tool 回复的 assistant 消息。详见
        ``sagents.utils.message_sanitizer.remove_orphan_tool_calls``。
        """
        return _remove_orphan_tool_calls_util(messages)

    def _drop_orphan_tool_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """移除没有归属 assistant tool_calls 的孤儿 tool 消息。详见
        ``sagents.utils.message_sanitizer.drop_orphan_tool_messages``。
        """
        return _drop_orphan_tool_messages_util(messages)

    def _drop_invalid_tool_calls(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """移除 ``function.arguments`` 不是合法 JSON 的 tool_call。详见
        ``sagents.utils.message_sanitizer.drop_invalid_tool_calls``。
        """
        return _drop_invalid_tool_calls_util(messages)

    def _repair_interleaved_tool_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """修复被 user/system/assistant 插队的 tool result。详见
        ``sagents.utils.message_sanitizer.repair_interleaved_tool_messages``。
        """
        return _repair_interleaved_tool_messages_util(messages)

    def _remove_content_if_tool_calls(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """assistant 消息带 tool_calls 时移除 content 字段。详见
        ``sagents.utils.message_sanitizer.strip_content_when_tool_calls``。
        """
        return _strip_content_when_tool_calls_util(messages)

    async def _process_multimodal_content(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        """处理多模态消息内容（本地图片转 base64、压缩到最大 512x512）。详见
        ``sagents.utils.multimodal_image.process_multimodal_content``。
        """
        return await _process_multimodal_content_util(msg)

    @staticmethod
    def _maybe_resolve_local_sage_url(url: str) -> Optional[str]:
        """桌面端 sidecar 的 ``http://127.0.0.1/api/oss/file/...`` 反解为本地路径。详见
        ``sagents.utils.multimodal_image.resolve_local_sage_url``。
        """
        return _resolve_local_sage_url_util(url)

    def _get_mime_type(self, file_extension: str) -> str:
        """根据文件扩展名获取 MIME 类型。详见
        ``sagents.utils.multimodal_image.get_mime_type``。
        """
        return _get_mime_type_util(file_extension)

    @staticmethod
    def _refresh_current_time(
        previous_current_time: Optional[str] = None,
    ) -> str:
        """Return the current time, preserving an existing system-context offset."""

        now = datetime.datetime.now()
        if previous_current_time:
            try:
                previous_dt = datetime.datetime.strptime(
                    previous_current_time,
                    "%a, %d %b %Y %H:%M:%S %z",
                )
                if previous_dt.tzinfo is not None:
                    return now.astimezone(previous_dt.tzinfo).strftime(
                        "%a, %d %b %Y %H:%M:%S %z"
                    )
            except ValueError:
                pass

        return now.astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")

    def _resolve_raw_context_limit(
        self, session_context: Optional[SessionContext] = None
    ) -> int:
        configured_max_input = None
        configured_max_model = None
        if isinstance(self.model_config, dict):
            configured_max_input = self.model_config.get("max_model_input_len")
            configured_max_model = self.model_config.get("max_model_len")
        max_model_len = int(configured_max_model or 128000)
        requested_limit = int(configured_max_input or self.max_model_input_len)
        return min(requested_limit, max_model_len)

    def _resolve_persistent_compression_threshold(
        self,
        session_context: Optional[SessionContext],
        raw_context_limit: int,
    ) -> int:
        configured_max_model = (
            self.model_config.get("max_model_len", 128000)
            if isinstance(self.model_config, dict)
            else 128000
        )
        upper_limit = min(raw_context_limit, int(configured_max_model or 128000))
        return max(1, int(upper_limit * 0.85))

    @staticmethod
    def _compression_chunks_succeeded(chunks: List[MessageChunk]) -> bool:
        for chunk in chunks:
            metadata = chunk.metadata if isinstance(chunk.metadata, dict) else {}
            if (
                chunk.role == MessageRole.TOOL.value
                and metadata.get("tool_name") == "compress_conversation_history"
                and metadata.get("status") == "success"
            ):
                return True
        return False

    async def _compress_messages_with_tool(
        self,
        messages: List[MessageChunk],
        session_id: str,
        source_message_ids: Optional[List[str]] = None,
        source_start_message_id: Optional[str] = None,
        source_end_message_id: Optional[str] = None,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        tool_call_id = f"auto_compress_{uuid.uuid4().hex[:8]}"
        source_message_ids = source_message_ids or [
            msg.message_id for msg in messages if msg.message_id
        ]
        source_start_message_id = source_start_message_id or (
            source_message_ids[0] if source_message_ids else None
        )
        source_end_message_id = source_end_message_id or (
            source_message_ids[-1] if source_message_ids else None
        )
        try:
            assistant_tool_call = MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content="",
                tool_calls=[
                    {
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": "compress_conversation_history",
                            "arguments": json.dumps({"session_id": session_id}),
                        },
                    }
                ],
                type=MessageType.TOOL_CALL.value,
                metadata={
                    "tool_name": "compress_conversation_history",
                    "auto_generated": True,
                    "compression_anchor": True,
                    "source_start_message_id": source_start_message_id,
                    "source_end_message_id": source_end_message_id,
                    "source_message_ids": source_message_ids,
                    "source_message_count": len(source_message_ids),
                },
            )
            logger.info(f"{self.agent_name}: yield 压缩工具的 tool_calls")
            yield [assistant_tool_call]

            from sagents.tool.impl.compress_history_tool import CompressHistoryTool

            tool = CompressHistoryTool()
            result = await tool.compress_conversation_history(
                messages,
                session_id,
                source_message_ids=source_message_ids,
                source_start_message_id=source_start_message_id,
                source_end_message_id=source_end_message_id,
            )

            compression_result = MessageChunk(
                role=MessageRole.TOOL.value,
                content=result.get("message", ""),
                tool_call_id=tool_call_id,
                type=MessageType.TOOL_CALL_RESULT.value,
                metadata={
                    "tool_name": "compress_conversation_history",
                    "auto_generated": True,
                    "status": result.get("status", "unknown"),
                    "compression_anchor": result.get("status") == "success",
                    "source_start_message_id": source_start_message_id,
                    "source_end_message_id": source_end_message_id,
                    "source_message_ids": source_message_ids,
                    "source_message_count": len(source_message_ids),
                },
            )
            if result.get("status") == "success":
                logger.info(f"{self.agent_name}: yield 压缩工具的 tool result")
            else:
                logger.warning(
                    f"{self.agent_name}: 工具压缩失败 - {result.get('message', '未知错误')}"
                )
            yield [compression_result]

        except Exception as exc:
            logger.error(f"{self.agent_name}: 调用压缩工具失败: {exc}")
            logger.error(traceback.format_exc())
            yield [
                MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=f"Compression failed: {str(exc)}",
                    tool_call_id=tool_call_id,
                    type=MessageType.TOOL_CALL_RESULT.value,
                    metadata={
                        "tool_name": "compress_conversation_history",
                        "auto_generated": True,
                        "status": "error",
                        "compression_anchor": False,
                        "source_start_message_id": source_start_message_id,
                        "source_end_message_id": source_end_message_id,
                        "source_message_ids": source_message_ids,
                        "source_message_count": len(source_message_ids),
                    },
                )
            ]

    @staticmethod
    def _insert_chunks_after_message_id(
        messages: List[MessageChunk],
        message_id: Optional[str],
        chunks: List[MessageChunk],
    ) -> List[MessageChunk]:
        if not message_id:
            return list(messages)
        for idx, message in enumerate(messages):
            if message.message_id == message_id:
                return (
                    list(messages[: idx + 1]) + list(chunks) + list(messages[idx + 1 :])
                )
        return list(messages)

    def _context_artifact_root(
        self, session_context: Optional[SessionContext]
    ) -> Optional[str]:
        workspace = None
        if session_context is not None:
            workspace = getattr(
                session_context, "sandbox_agent_workspace", None
            ) or getattr(session_context, "system_context", {}).get("private_workspace")
        if not workspace:
            return None
        return os.path.join(str(workspace), ".sage", "context", "artifacts")

    @staticmethod
    def _without_system_messages(
        messages: Optional[List[MessageChunk]],
    ) -> List[MessageChunk]:
        """Return only conversation/history messages.

        System messages are generated fresh for every LLM request and must not be
        reused from history, compression views, or caller-provided message lists.
        """
        return [
            message
            for message in (messages or [])
            if message.role != MessageRole.SYSTEM.value
        ]

    @classmethod
    def _stable_system_sections_for_runtime_user(
        cls, include_sections: Optional[List[str]]
    ) -> List[str]:
        if include_sections is None:
            return [
                "role_definition",
                "active_skill",
                "available_skills",
                "AGENT.MD",
            ]
        return [
            section
            for section in include_sections
            if section not in cls.RUNTIME_CONTEXT_SYSTEM_SECTIONS
        ]

    async def prepare_llm_request_messages(
        self,
        *,
        session_id: Optional[str] = None,
        history_messages: Optional[List[MessageChunk]] = None,
        extra_messages: Optional[List[MessageChunk]] = None,
        custom_prefix: Optional[str] = None,
        language: Optional[str] = None,
        system_prefix_override: Optional[str] = None,
        include_sections: Optional[List[str]] = None,
    ) -> List[MessageChunk]:
        """Build a final LLM request as fresh system + non-system payload.

        ``MessageManager`` owns only the non-system ledger. Any system messages
        found in ``history_messages`` or ``extra_messages`` are treated as stale
        request artifacts and dropped before fresh system segments are prepended.
        """
        effective_include_sections = include_sections
        runtime_in_user = (
            os.environ.get("SAGE_RUNTIME_CONTEXT_IN_USER", "true").lower() != "false"
        )
        if runtime_in_user:
            effective_include_sections = self._stable_system_sections_for_runtime_user(
                effective_include_sections
            )

        system_messages = await self.prepare_unified_system_messages(
            session_id=session_id,
            custom_prefix=custom_prefix,
            language=language,
            system_prefix_override=system_prefix_override,
            include_sections=effective_include_sections,
        )
        payload_messages = self._without_system_messages(
            history_messages
        ) + self._without_system_messages(extra_messages)
        if session_id and runtime_in_user:
            payload_messages = await self._inject_latest_user_runtime_context(
                payload_messages,
                session_id=session_id,
                language=language,
            )
        return list(system_messages) + payload_messages

    async def _build_runtime_context_text(
        self,
        *,
        session_id: str,
        language: Optional[str] = None,
    ) -> str:
        segments = await self._build_system_segments(
            session_id=session_id,
            language=language,
            include_sections=["system_context", "workspace_files"],
        )
        volatile = (segments.get("volatile") or "").strip()
        if not volatile:
            return ""
        return f"<runtime_context>\n{volatile}\n</runtime_context>"

    async def _read_active_todo_list_for_context(
        self, session_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        if not session_id:
            return []
        try:
            from sagents.tool.impl.todo_tool import ToDoTool

            return await ToDoTool().read_active_tasks(session_id)
        except Exception as exc:
            logger.warning(
                f"{self.__class__.__name__}: failed to read active todo context: {exc}"
            )
            return []

    @staticmethod
    def _wrap_message_with_runtime_context(
        message: MessageChunk,
        runtime_context: str,
    ) -> MessageChunk:
        if not runtime_context.strip():
            return message
        copied = MessageChunk.from_dict(message.to_dict())
        content = copied.content
        context_text = runtime_context.strip()
        if isinstance(content, list):
            copied.content = (
                [{"type": "text", "text": f"{context_text}\n\n<user_request>\n"}]
                + content
                + [{"type": "text", "text": "\n</user_request>"}]
            )
        else:
            original = str(content or "")
            copied.content = (
                f"{context_text}\n\n<user_request>\n{original}\n</user_request>"
                if original
                else f"{context_text}\n\n<user_request>\n</user_request>"
            )
        metadata = dict(copied.metadata or {})
        metadata["runtime_context_injected"] = True
        metadata["inference_view_only"] = True
        copied.metadata = metadata
        return copied

    @classmethod
    def _get_frozen_user_inference(
        cls, message: MessageChunk
    ) -> Optional[Dict[str, Any]]:
        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        frozen = metadata.get(cls.FROZEN_USER_INFERENCE_METADATA_KEY)
        return frozen if isinstance(frozen, dict) else None

    @classmethod
    def _apply_frozen_user_inference(
        cls,
        message: MessageChunk,
        frozen: Dict[str, Any],
    ) -> MessageChunk:
        copied = MessageChunk.from_dict(message.to_dict())
        copied.content = frozen.get("content", copied.content)
        copied.content = cls._strip_skill_tags_from_content(copied.content)
        metadata = dict(copied.metadata or {})
        frozen_metadata = frozen.get("metadata")
        if isinstance(frozen_metadata, dict):
            metadata.update(frozen_metadata)
        metadata.pop("persist", None)
        metadata["runtime_context_injected"] = True
        metadata["inference_view_only"] = True
        copied.metadata = metadata
        return copied

    @classmethod
    def _apply_frozen_historical_user_time_context(
        cls,
        message: MessageChunk,
        frozen: Dict[str, Any],
    ) -> MessageChunk:
        current_time_context = cls._extract_current_time_context_tag(
            frozen.get("content")
        )
        stripped = cls._strip_skill_tags_from_message(message)
        if not current_time_context:
            return stripped
        runtime_context = f"<runtime_context>\n{current_time_context}\n</runtime_context>"
        return cls._wrap_message_with_runtime_context(stripped, runtime_context)

    @staticmethod
    def _extract_current_time_context_tag(content: Any) -> Optional[str]:
        text_parts: List[str] = []
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
                    continue
                part_content = part.get("content")
                if isinstance(part_content, str):
                    text_parts.append(part_content)

        for text in text_parts:
            current_time_context = AgentBase._extract_current_time_from_runtime_text(
                text
            )
            if current_time_context:
                return current_time_context
        return None

    @staticmethod
    def _extract_current_time_from_runtime_text(text: str) -> Optional[str]:
        runtime_match = re.search(
            r"<runtime_context\b[^>]*>(.*?)</runtime_context>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not runtime_match:
            return None

        runtime_body = runtime_match.group(1)
        system_match = re.search(
            r"<system_context\b[^>]*>(.*?)</system_context>",
            runtime_body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        trusted_body = system_match.group(1) if system_match else runtime_body
        match = re.search(
            r"<current_time\b[^>]*>.*?</current_time>",
            trusted_body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return match.group(0).strip() if match else None

    @classmethod
    def _strip_skill_tags_from_text(cls, text: str) -> str:
        cleaned = re.sub(
            r"<skill>\s*[^<]*?\s*</skill>",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if cleaned == text:
            return text
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @classmethod
    def _strip_skill_tags_from_content(cls, content: Any) -> Any:
        if isinstance(content, str):
            return cls._strip_skill_tags_from_text(content)
        if isinstance(content, list):
            sanitized = []
            changed = False
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    next_part = dict(part)
                    original_text = str(next_part.get("text", ""))
                    next_text = cls._strip_skill_tags_from_text(original_text)
                    next_part["text"] = next_text
                    changed = changed or next_text != original_text
                    sanitized.append(next_part)
                else:
                    sanitized.append(part)
            return sanitized if changed else content
        return content

    @classmethod
    def _strip_skill_tags_from_message(cls, message: MessageChunk) -> MessageChunk:
        sanitized_content = cls._strip_skill_tags_from_content(message.content)
        if sanitized_content is message.content:
            return message
        copied = MessageChunk.from_dict(message.to_dict())
        copied.content = sanitized_content
        return copied

    def _save_frozen_user_inference_to_message(
        self,
        *,
        session_id: str,
        source_message: MessageChunk,
        frozen: Dict[str, Any],
    ) -> None:
        source_metadata = dict(source_message.metadata or {})
        source_metadata[self.FROZEN_USER_INFERENCE_METADATA_KEY] = frozen
        source_message.metadata = source_metadata
        try:
            session_context = self._get_live_session_context(session_id)
            message_manager = getattr(session_context, "message_manager", None)
            for ledger_message in getattr(message_manager, "messages", []):
                if ledger_message.message_id != source_message.message_id:
                    continue
                ledger_metadata = dict(ledger_message.metadata or {})
                ledger_metadata[self.FROZEN_USER_INFERENCE_METADATA_KEY] = frozen
                ledger_message.metadata = ledger_metadata
                if hasattr(message_manager, "stats"):
                    message_manager.stats["last_updated"] = (
                        datetime.datetime.now().isoformat()
                    )
                break
        except Exception as exc:
            logger.debug(
                f"{self.__class__.__name__}: failed to persist frozen user inference: {exc}"
            )

    def _find_frozen_user_inference_in_ledger(
        self, session_id: str, message: MessageChunk
    ) -> Optional[Dict[str, Any]]:
        if not message.message_id:
            return None
        try:
            session_context = self._get_live_session_context(session_id)
            message_manager = getattr(session_context, "message_manager", None)
            for ledger_message in getattr(message_manager, "messages", []):
                if ledger_message.message_id != message.message_id:
                    continue
                return self._get_frozen_user_inference(ledger_message)
        except Exception as exc:
            logger.debug(
                f"{self.__class__.__name__}: failed to load frozen user inference from ledger: {exc}"
            )
        return None

    async def _inject_latest_user_runtime_context(
        self,
        messages: List[MessageChunk],
        *,
        session_id: str,
        language: Optional[str],
    ) -> List[MessageChunk]:
        if not messages:
            return messages
        latest_user_idx = None
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].role == MessageRole.USER.value:
                latest_user_idx = idx
                break
        if latest_user_idx is None:
            return messages
        injected = list(messages)
        for idx, message in enumerate(injected):
            if message.role != MessageRole.USER.value:
                continue
            if idx == latest_user_idx:
                continue
            frozen = self._get_frozen_user_inference(message)
            if not frozen:
                frozen = self._find_frozen_user_inference_in_ledger(session_id, message)
            if frozen:
                injected[idx] = self._apply_frozen_historical_user_time_context(
                    message, frozen
                )

        latest_user = injected[latest_user_idx]
        latest_frozen = self._get_frozen_user_inference(messages[latest_user_idx])
        if not latest_frozen:
            latest_frozen = self._find_frozen_user_inference_in_ledger(
                session_id, messages[latest_user_idx]
            )
        if latest_frozen is not None:
            injected[latest_user_idx] = self._apply_frozen_user_inference(
                messages[latest_user_idx], latest_frozen
            )
        else:
            parts: List[str] = []
            try:
                runtime_context = await self._build_runtime_context_text(
                    session_id=session_id, language=language
                )
            except Exception as exc:
                logger.debug(
                    f"{self.__class__.__name__}: skip runtime context injection: {exc}"
                )
                runtime_context = ""
            if runtime_context:
                parts.append(runtime_context)
            runtime_text = "\n\n".join(parts)
            if runtime_text.strip():
                latest_user = self._strip_skill_tags_from_message(latest_user)
                latest_user = self._wrap_message_with_runtime_context(
                    latest_user, runtime_text
                )
                frozen = {
                    "content": latest_user.content,
                    "metadata": {
                        "runtime_context_injected": True,
                        "inference_view_only": True,
                        "frozen_user_inference": True,
                        "frozen_user_inference_version": self.FROZEN_USER_INFERENCE_VERSION,
                    },
                }
                self._save_frozen_user_inference_to_message(
                    session_id=session_id,
                    source_message=messages[latest_user_idx],
                    frozen=frozen,
                )
                injected[latest_user_idx] = latest_user
        return injected

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest()

    def _build_prompt_cache_observation(
        self,
        messages: List[Union[MessageChunk, Dict[str, Any]]],
        tools: Any,
    ) -> Dict[str, Any]:
        stable = ""
        semi_stable = ""
        for msg in messages:
            if not isinstance(msg, MessageChunk):
                continue
            if msg.role != MessageRole.SYSTEM.value:
                continue
            metadata = msg.metadata if isinstance(msg.metadata, dict) else {}
            segment = metadata.get("cache_segment")
            content = msg.get_content()
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, default=str)
            if segment == "stable":
                stable += content
            elif segment == "semi_stable":
                semi_stable += content
        observation = {
            "stable_system_hash": self._hash_text(stable) if stable else None,
            "semi_stable_system_hash": self._hash_text(semi_stable)
            if semi_stable
            else None,
            "inference_message_count": len(messages),
        }
        if tools:
            observation["tools_schema_hash"] = self._canonical_hash(tools)
        return observation

    async def prepare_llm_system_prompt_text(
        self,
        *,
        session_id: Optional[str] = None,
        custom_prefix: Optional[str] = None,
        language: Optional[str] = None,
        system_prefix_override: Optional[str] = None,
        include_sections: Optional[List[str]] = None,
    ) -> str:
        """Build fresh system prompt text for judge prompts that embed it."""
        system_messages = await self.prepare_unified_system_messages(
            session_id=session_id,
            custom_prefix=custom_prefix,
            language=language,
            system_prefix_override=system_prefix_override,
            include_sections=include_sections,
        )
        return "".join(message.content or "" for message in system_messages)

    @staticmethod
    def _message_role_for_request_guard(
        message: Union[MessageChunk, Dict[str, Any]],
    ) -> Optional[str]:
        if isinstance(message, MessageChunk):
            return message.role
        if isinstance(message, dict):
            role = message.get("role")
            return str(role) if role is not None else None
        return None

    @classmethod
    def _validate_llm_request_system_messages(
        cls,
        messages: List[Union[MessageChunk, Dict[str, Any]]],
    ) -> None:
        seen_non_system = False
        for message in messages:
            role = cls._message_role_for_request_guard(message)
            if role != MessageRole.SYSTEM.value:
                seen_non_system = True
                continue
            if isinstance(message, dict):
                raise ValueError(
                    "Raw dict system messages are not accepted by _call_llm_streaming; "
                    "build fresh MessageChunk system messages via prepare_llm_request_messages."
                )
            if seen_non_system:
                raise ValueError(
                    "System messages must be the leading request prefix; "
                    "build requests via prepare_llm_request_messages."
                )

    @staticmethod
    def _language_from_session_context(
        session_context: Optional[SessionContext],
    ) -> Optional[str]:
        if session_context is None:
            return None
        try:
            return session_context.get_language()
        except Exception:
            return None

    def _context_over_limit_error_chunk(
        self, current_tokens: int, limit: int, language: Optional[str] = None
    ) -> MessageChunk:
        return MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=t(
                "runtime.context_over_limit",
                language,
                {"current_tokens": current_tokens, "limit": limit},
            ),
            type=MessageType.AGENT_EXECUTION_ERROR.value,
            agent_name=self.agent_name,
        )

    async def _prepare_context_messages_for_llm(
        self,
        messages_input: List[MessageChunk],
        session_id: str,
    ) -> AsyncGenerator[tuple[List[MessageChunk], bool], None]:
        try:
            session_context = self._get_live_session_context(session_id)
        except Exception:
            session_context = None
        message_manager = (
            session_context.message_manager if session_context is not None else None
        )
        max_model_len = int(
            self.model_config.get("max_model_len", 128000)
            if isinstance(self.model_config, dict)
            else 128000
        )
        trigger_limit = int(max_model_len * 0.85)
        artifact_root = self._context_artifact_root(session_context)
        working_messages = list(messages_input)

        for _ in range(20):
            view = MessageManager.build_inference_view(
                working_messages,
                session_id=session_id,
                max_model_len=max_model_len,
                artifact_root=artifact_root,
                apply_rule_compression=True,
            )
            if message_manager is not None:
                message_manager.store_inference_messages(view)
            current_tokens = MessageManager.calculate_messages_token_length(view)
            if current_tokens <= trigger_limit:
                yield (view, True)
                return

            segment = MessageManager.select_llm_compression_segment(
                working_messages,
                max_model_len=max_model_len,
                active_protection_count=12,
            )
            if not segment:
                logger.warning(
                    f"{self.agent_name}: 无可压缩历史段，当前上下文仍为 {current_tokens} tokens"
                )
                yield (
                    [
                        self._context_over_limit_error_chunk(
                            current_tokens,
                            trigger_limit,
                            self._language_from_session_context(session_context),
                        )
                    ],
                    False,
                )
                return

            source_ids = [msg.message_id for msg in segment if msg.message_id]
            source_start = source_ids[0] if source_ids else None
            source_end = source_ids[-1] if source_ids else None
            emitted_chunks: List[MessageChunk] = []
            async for messages_chunk in self._compress_messages_with_tool(
                segment,
                session_id,
                source_message_ids=source_ids,
                source_start_message_id=source_start,
                source_end_message_id=source_end,
            ):
                emitted_chunks.extend(messages_chunk)
                yield (messages_chunk, False)

            if not self._compression_chunks_succeeded(emitted_chunks):
                logger.warning(f"{self.agent_name}: 大模型压缩失败，停止继续压缩")
                view = MessageManager.build_inference_view(
                    working_messages,
                    session_id=session_id,
                    max_model_len=max_model_len,
                    artifact_root=artifact_root,
                    apply_rule_compression=True,
                )
                if message_manager is not None:
                    message_manager.store_inference_messages(view)
                yield (view, True)
                return

            working_messages = self._insert_chunks_after_message_id(
                working_messages, source_end, emitted_chunks
            )
            if message_manager is not None and source_end:
                message_manager.insert_messages_after(source_end, emitted_chunks)

        logger.warning(f"{self.agent_name}: 大模型压缩达到最大轮数，返回当前上下文")
        final_view = MessageManager.build_inference_view(
            working_messages,
            session_id=session_id,
            max_model_len=max_model_len,
            artifact_root=artifact_root,
            apply_rule_compression=True,
        )
        if message_manager is not None:
            message_manager.store_inference_messages(final_view)
        final_tokens = MessageManager.calculate_messages_token_length(final_view)
        if final_tokens > trigger_limit:
            yield (
                [
                    self._context_over_limit_error_chunk(
                        final_tokens,
                        trigger_limit,
                        self._language_from_session_context(session_context),
                    )
                ],
                False,
            )
            return
        yield (final_view, True)

    @staticmethod
    def _chunks_contain_tool_calls(chunks: List[Any]) -> bool:
        for chunk in chunks:
            choices = (
                chunk.get("choices", [])
                if isinstance(chunk, dict)
                else getattr(chunk, "choices", [])
            ) or []
            for choice in choices:
                if isinstance(choice, dict):
                    finish_reason = choice.get("finish_reason")
                    delta = choice.get("delta") or {}
                    tool_calls = (
                        delta.get("tool_calls")
                        if isinstance(delta, dict)
                        else getattr(delta, "tool_calls", None)
                    )
                else:
                    finish_reason = getattr(choice, "finish_reason", None)
                    delta = getattr(choice, "delta", None)
                    tool_calls = getattr(delta, "tool_calls", None)
                if finish_reason == "tool_calls" or tool_calls:
                    return True
        return False

    async def _call_llm_streaming(
        self,
        messages: List[Union[MessageChunk, Dict[str, Any]]],
        session_id: Optional[str] = None,
        step_name: str = "llm_call",
        model_config_override: Optional[Dict[str, Any]] = None,
        enable_thinking: Optional[bool] = None,
    ):
        """
        通用的流式模型调用方法，有这个封装，主要是为了将
        模型调用和日志记录等功能统一起来，以及token 的记录等，方便后续的维护和扩展。

        Args:
            messages: 输入消息列表
            session_id: 会话ID（用于请求记录）
            step_name: 步骤名称（用于请求记录）
            model_config_override: 覆盖模型配置（用于工具调用等），可包含response_format等参数
            enable_thinking: 是否启用思考模式，优先使用此参数，为None时使用deep_thinking配置。
                           对于OpenAI推理模型(o3-mini, GPT-5.2等)，会转换为reasoning_effort参数

        Returns:
            Generator: 语言模型的流式响应
        """
        if session_id:
            session = self._get_live_session(session_id)
            if session is None:
                logger.warning(
                    f"{self.__class__.__name__}: session is None for session_id={session_id}"
                )
            elif session.is_interrupted():
                logger.info(
                    f"{self.__class__.__name__}: 跳过模型调用，session已中断，会话ID: {session_id}"
                )
                return
        self._validate_llm_request_system_messages(messages)
        # 确定最终的模型配置
        final_config = {**self.model_config}
        if model_config_override:
            final_config.update(model_config_override)

        model_name = (
            cast(str, final_config.pop("model"))
            if "model" in final_config
            else "gpt-3.5-turbo"
        )
        model_type = final_config.get("model_type")
        supports_sage_model_type = isinstance(
            self.model, SageAsyncOpenAI
        ) or isinstance(getattr(self.model, "_model", None), SageAsyncOpenAI)
        fast_model_name = getattr(self.model, "fast_model_name", None)
        if model_type == "fast" and supports_sage_model_type and fast_model_name:
            model_name = fast_model_name
        # 移除不是OpenAI API标准参数的配置项
        final_config.pop("max_model_len", None)
        final_config.pop("api_key", None)
        final_config.pop("maxTokens", None)
        final_config.pop("base_url", None)
        # 移除快速模型相关配置（这些是我们内部使用的参数）
        final_config.pop("fast_api_key", None)
        final_config.pop("fast_base_url", None)
        final_config.pop("fast_model_name", None)
        # 只有当 model 不是 SageAsyncOpenAI 类型时，才移除 model_type
        # SageAsyncOpenAI 需要 model_type 来选择使用哪个客户端
        if not supports_sage_model_type:
            final_config.pop("model_type", None)
        all_chunks = []
        attempt_chunks = []

        logical_request_id = f"llm_{uuid.uuid4().hex}"
        candidate_next_request_message_ids = set(
            MessageManager.pending_next_request_message_ids(messages)
        )
        if messages and all(isinstance(m, MessageChunk) for m in messages):
            messages = MessageManager.strip_rejected_tool_calls_from_llm_context(  # pyright: ignore[reportAssignmentType]
                list(messages)  # pyright: ignore[reportArgumentType]
            )
            messages = MessageManager.strip_turn_status_from_llm_context(  # pyright: ignore[reportAssignmentType]
                list(messages)  # pyright: ignore[reportArgumentType]
            )
        messages = MessageManager.filter_messages_for_llm_scope(messages)  # pyright: ignore[reportAssignmentType]
        pending_next_request_message_ids: List[str] = []
        llm_scope_finalized = False

        # A logical request owns one immutable provider payload. Network retries
        # reuse this snapshot; only the explicit structured-output fallback may
        # change response_format while keeping the message payload unchanged.
        request_messages_snapshot: Optional[List[Dict[str, Any]]] = None
        response_format = final_config.pop("response_format", None)

        # 重试配置 - 增加重试次数以应对网络不稳定情况
        max_retries = 8
        retry_count = 0
        last_exception = None
        structured_output_fallback_used = False
        partial_stream_aborted = False
        stream_succeeded = False

        while retry_count < max_retries:
            attempt_yielded_chunks = False
            retrying_logical_request = False
            try:
                attempt_chunks = []
                first_token_time = None
                partial_stream_aborted = False
                if self.model is None:
                    raise ValueError("Model is not initialized")

                prompt_cache_observation = self._build_prompt_cache_observation(
                    messages,
                    final_config.get("tools"),
                )

                # 发起LLM请求
                # 将 MessageChunk 对象转换为字典，以便进行 JSON 序列化
                start_request_time = time.time()
                first_token_time = None
                cache_segments: List[Optional[str]] = []
                if request_messages_snapshot is not None:
                    serializable_messages = deepcopy(request_messages_snapshot)
                else:
                    serializable_messages = []
                    for msg in messages:
                        if isinstance(msg, MessageChunk):
                            msg_dict = (
                                MessageManager.convert_message_to_dict_for_request(msg)
                            )
                            if msg_dict is None:
                                continue
                            if msg.message_id:
                                msg_dict["_sage_message_id"] = msg.message_id
                            msg_dict = await self._process_multimodal_content(msg_dict)
                            serializable_messages.append(msg_dict)
                            seg = None
                            if isinstance(getattr(msg, "metadata", None), dict):
                                seg = msg.metadata.get("cache_segment")  # pyright: ignore[reportOptionalMemberAccess]
                            cache_segments.append(seg)
                        else:
                            msg_copy = msg.copy()
                            raw_message_id = MessageChunk.from_dict(msg).message_id
                            if raw_message_id:
                                msg_copy["_sage_message_id"] = raw_message_id
                            msg_copy = await self._process_multimodal_content(msg_copy)
                            serializable_messages.append(msg_copy)
                            cache_segments.append(None)
                    # 只保留 model.chat.completions.create 需要的 message key。
                    serializable_messages = [
                        {
                            k: v
                            for k, v in msg.items()
                            if k
                            in [
                                "role",
                                "content",
                                "tool_calls",
                                "tool_call_id",
                                "_sage_message_id",
                            ]
                        }
                        for msg in serializable_messages
                    ]

                # === 注入 shell completion 事件作为 <system_reminder> 消息 ===
                # 后台 shell 命令完成后，watcher 会把事件写入 ExecuteCommandTool._COMPLETION_EVENTS。
                # 这里在每次 LLM 请求前 flush 一次，作为 role=user + <system_reminder> 文本注入。
                # 选 role=user 而非 system 的原因：
                #   1) Anthropic 不允许中段 system 消息；
                #   2) 不破坏 OpenAI tool_call 严格交替序列；
                #   3) 不污染 system prompt cache。
                # await_shell 显式拿到 completed 时会 consume 对应 task_id 的事件，
                # 因此被显式消费过的不会在这里重复出现。
                if session_id and request_messages_snapshot is None:
                    try:
                        from sagents.tool.impl.execute_command_tool import (
                            ExecuteCommandTool,
                        )

                        completion_events = ExecuteCommandTool.pop_completion_events(
                            session_id
                        )
                    except Exception as _e:
                        logger.warning(f"flush shell completion events 失败: {_e}")
                        completion_events = []
                    if completion_events:
                        # 取 session 语言，用于 reminder 文本国际化
                        _reminder_lang = "en"
                        try:
                            _sc = self._get_live_session_context(session_id)
                            if _sc is not None:
                                _reminder_lang = _sc.get_language()
                        except Exception:
                            pass
                        _is_zh = str(_reminder_lang).lower().startswith("zh")

                    for ev in completion_events:
                        tail = ev.get("tail", "") or ""
                        if _is_zh:
                            tail_section = (
                                f"最后几行输出:\n{tail}" if tail else "（无输出）"
                            )
                            note = (
                                f"注意：这只是完成通知，输出已截断。"
                                f'如需完整 stdout，请调用 await_shell(task_id="{ev.get("task_id")}")。'
                            )
                        else:
                            tail_section = (
                                f"tail (last few lines):\n{tail}"
                                if tail
                                else "(no output captured)"
                            )
                            note = (
                                f"Note: This is a brief notification only. "
                                f'Call await_shell(task_id="{ev.get("task_id")}") to retrieve the full stdout if needed.'
                            )
                        reminder_text = (
                            "<system_reminder>\n"
                            f"[shell completion] task_id={ev.get('task_id')} "
                            f"exit_code={ev.get('exit_code')} elapsed_ms={ev.get('elapsed_ms')}\n"
                            f"command: {ev.get('command', '')}\n"
                            f"{tail_section}\n"
                            f"{note}\n"
                            "</system_reminder>"
                        )
                        serializable_messages.append(
                            {"role": "user", "content": reminder_text}
                        )
                        cache_segments.append(None)
                    if completion_events:
                        logger.info(
                            f"{self.__class__.__name__}: 注入 {len(completion_events)} 条 shell completion reminder"
                        )

                # 统计图片数量
                image_count = 0
                for msg in serializable_messages:
                    content = msg.get("content")
                    if isinstance(content, list):
                        for item in content:
                            if (
                                isinstance(item, dict)
                                and item.get("type") == "image_url"
                            ):
                                image_count += 1
                if image_count > 0:
                    logger.info(f"[LLM请求] 包含 {image_count} 张图片")

                # print("serializable_messages:",serializable_messages)
                # 确保所有的messages 中都包含role 和 content
                for msg in serializable_messages:
                    if "role" not in msg:
                        msg["role"] = MessageRole.USER.value
                    if "content" not in msg:
                        msg["content"] = ""

                # 先修复被运行中 guidance/user 消息插队的 tool result，再清理仍不完整的 pair。
                serializable_messages = self._repair_interleaved_tool_messages(
                    serializable_messages
                )
                # 保留原始 ledger 中被打断的 tool_call 记录，但下一轮 LLM 请求不能携带
                # 残缺/非 JSON 的 function.arguments，否则部分供应商会直接 400。
                serializable_messages = self._drop_invalid_tool_calls(
                    serializable_messages
                )
                # 需要处理 serializable_messages 中，如果有tool call ，但是没有后续的tool call id,需要去掉这条消息
                serializable_messages = self._remove_tool_call_without_id(
                    serializable_messages
                )
                # 反向保证：去掉没有归属 assistant tool_calls 的孤儿 tool 消息，
                # 避免压缩覆盖/offload/上一步丢弃多调用 assistant 后触发 OpenAI 400
                # "messages with role 'tool' must be a response to a preceeding message with 'tool_calls'"
                serializable_messages = self._drop_orphan_tool_messages(
                    serializable_messages
                )
                # 如果针对带有 tool_calls 的assistant 的消息，要删除content 这个字段
                serializable_messages = self._remove_content_if_tool_calls(
                    serializable_messages
                )
                if request_messages_snapshot is None:
                    proposed_next_request_message_ids = [
                        str(msg["_sage_message_id"])
                        for msg in serializable_messages
                        if msg.get("_sage_message_id")
                        in candidate_next_request_message_ids
                    ]
                    pending_next_request_message_ids = list(
                        dict.fromkeys(proposed_next_request_message_ids)
                    )
                    if session_id and pending_next_request_message_ids:
                        session_context = self._get_live_session_context(session_id)
                        claim_messages = getattr(
                            session_context,
                            "claim_llm_messages_for_request",
                            None,
                        )
                        if callable(claim_messages):
                            pending_next_request_message_ids = list(
                                claim_messages(
                                    pending_next_request_message_ids,
                                    logical_request_id,
                                )
                            )
                            claimed_ids = set(pending_next_request_message_ids)
                            serializable_messages = [
                                msg
                                for msg in serializable_messages
                                if msg.get("_sage_message_id")
                                not in candidate_next_request_message_ids
                                or msg.get("_sage_message_id") in claimed_ids
                            ]
                    for msg in serializable_messages:
                        msg.pop("_sage_message_id", None)
                    request_messages_snapshot = deepcopy(serializable_messages)

                # Provider clients may normalize/mutate request dictionaries, so
                # every attempt receives a fresh copy of the frozen snapshot.
                serializable_messages = deepcopy(request_messages_snapshot)
                final_config = {k: v for k, v in final_config.items() if v is not None}

                # 根据 enable_thinking 参数或 deep_thinking 配置决定是否启用思考模式
                # 优先使用传入的 enable_thinking 参数
                final_enable_thinking = False
                if enable_thinking is not None:
                    final_enable_thinking = enable_thinking
                elif session is not None:
                    deep_thinking = session.session_context.agent_config.get(
                        "deep_thinking", False
                    )
                    # 处理字符串 "auto" 的情况，默认为 False
                    if isinstance(deep_thinking, str):
                        final_enable_thinking = deep_thinking.lower() == "true"
                    else:
                        final_enable_thinking = bool(deep_thinking)

                # 构建 extra_body（与压缩等旁路请求共用同一套模型分支逻辑）
                extra_body = build_llm_extra_body(
                    model_name,
                    enable_thinking=final_enable_thinking,
                    step_name=step_name,
                    reasoning_effort_off_env=os.environ.get("SAGE_REASONING_EFFORT_OFF"),
                )

                stream = await create_chat_completion_with_fallback(
                    self.model,
                    model=model_name,
                    messages=cast(List[Any], serializable_messages),
                    model_config=final_config,
                    response_format=response_format,
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body=extra_body,
                    **final_config,
                )
                async for chunk in stream:
                    # print(chunk)
                    # 记录首token时间
                    if first_token_time is None:
                        first_token_time = time.time()
                    attempt_chunks.append(chunk)

                    # 显式让出控制权，确保在高吞吐量时不会饿死事件循环（如心跳检测）
                    await asyncio.sleep(0)

                    attempt_yielded_chunks = True
                    yield chunk

                # 成功完成，跳出重试循环
                all_chunks = attempt_chunks
                if session_id and pending_next_request_message_ids:
                    session_context = self._get_live_session_context(session_id)
                    if session_context is not None:
                        if attempt_chunks and not self._chunks_contain_tool_calls(
                            attempt_chunks
                        ):
                            session_context.mark_llm_messages_consumed(
                                pending_next_request_message_ids,
                                logical_request_id,
                            )
                        else:
                            release_claims = getattr(
                                session_context,
                                "release_llm_message_claims",
                                None,
                            )
                            if callable(release_claims):
                                release_claims(
                                    pending_next_request_message_ids,
                                    logical_request_id,
                                )
                    llm_scope_finalized = True
                stream_succeeded = True
                break

            except (
                RateLimitError,
                APIError,
                APIConnectionError,
                httpx.ReadTimeout,
                httpx.ConnectTimeout,
                httpx.ReadError,
            ) as e:
                if (
                    response_format is not None
                    and not structured_output_fallback_used
                    and is_unsupported_input_format_error(e)
                ):
                    structured_output_fallback_used = True
                    response_format = None
                    retry_count += 1
                    last_exception = e
                    logger.warning(
                        f"{self.__class__.__name__}: structured output not supported in this runtime shape, retrying without response_format: {e}"
                    )
                    await asyncio.sleep(0)
                    retrying_logical_request = True
                    continue
                retry_count += 1
                last_exception = e
                error_message = str(e).lower()

                # 检查是否是限流错误
                is_rate_limit = (
                    isinstance(e, RateLimitError)
                    or "rate limit" in error_message
                    or "too many requests" in error_message
                )
                # 检查是否是网络连接错误（包括连接中断、超时等）
                is_connection_error = (
                    isinstance(e, APIConnectionError)
                    or "connection" in error_message
                    or "incomplete chunked read" in error_message
                )
                # 检查是否是超时错误
                is_timeout = (
                    isinstance(e, (httpx.ReadTimeout, httpx.ConnectTimeout))
                    or "timeout" in error_message
                    or "read timeout" in error_message
                )
                # 检查是否是读取错误
                is_read_error = (
                    isinstance(e, httpx.ReadError) or "read error" in error_message
                )
                # 检查是否是 token 超限错误
                is_token_limit_error = (
                    "range of input length" in error_message
                    or "token" in error_message
                    and "exceed" in error_message
                )

                if attempt_yielded_chunks:
                    message = (
                        f"{self.__class__.__name__}: 流式响应已向上游输出部分 chunk，"
                        f"遇到{('超时' if is_timeout else '网络/读取')}错误后不再透明重试，避免污染工具调用参数: {e}"
                    )
                    logger.warning(message)
                    raise PartialStreamConsumedError(message, e) from e

                if retry_count < max_retries and (
                    is_rate_limit or is_connection_error or is_timeout or is_read_error
                ):
                    wait_time = 2**retry_count  # 指数退避: 2, 4, 8 秒
                    if is_rate_limit:
                        error_type = "限流"
                    elif is_timeout:
                        error_type = "超时"
                        wait_time = min(wait_time, 10)  # 超时错误最多等待10秒
                    else:
                        error_type = "网络连接"
                    if attempt_chunks:
                        logger.warning(
                            f"{self.__class__.__name__}: 流式响应已输出 {len(attempt_chunks)} 个chunk后遇到{error_type}错误，"
                            "停止本次请求避免 retry 拼接半截 tool_call"
                        )
                        partial_stream_aborted = True
                        break
                    logger.warning(
                        f"{self.__class__.__name__}: 遇到{error_type}错误，等待 {wait_time} 秒后重试 ({retry_count}/{max_retries}): {e}"
                    )
                    await asyncio.sleep(wait_time)
                    retrying_logical_request = True
                elif is_token_limit_error:
                    # token 超限错误，直接抛出，由上层处理压缩逻辑
                    logger.error(
                        f"{self.__class__.__name__}: Token 超限错误，需要压缩消息: {e}"
                    )
                    raise
                else:
                    # 非可重试错误或已达到最大重试次数
                    if isinstance(e, APIError):
                        logger.error(
                            f"{self.__class__.__name__}: LLM流式调用失败: {format_api_error_details(e)}\n{traceback.format_exc()}"
                        )
                    else:
                        logger.error(
                            f"{self.__class__.__name__}: LLM流式调用失败: {e}\n{traceback.format_exc()}"
                        )
                    all_chunks.append(
                        chat_completion_chunk.ChatCompletionChunk(
                            id="",
                            object="chat.completion.chunk",
                            created=0,
                            model="",
                            choices=[
                                chat_completion_chunk.Choice(
                                    index=0,
                                    delta=chat_completion_chunk.ChoiceDelta(
                                        content=traceback.format_exc(),
                                        tool_calls=None,
                                    ),
                                    finish_reason="stop",
                                )
                            ],
                            usage=None,
                        )
                    )
                    raise e

            except Exception as e:
                # 其他非API错误，检查是否是网络相关错误
                retry_count += 1
                last_exception = e
                error_message = str(e).lower()

                # 检查是否是网络相关错误（如 httpx.RemoteProtocolError, httpx.ReadTimeout 等）
                is_network_error = any(
                    keyword in error_message
                    for keyword in [
                        "connection",
                        "incomplete chunked read",
                        "peer closed",
                        "remoteprotocolerror",
                        "timeout",
                        "read timeout",
                        "connect timeout",
                        "read error",
                    ]
                )
                # 检查是否是 httpx 特定的超时或读取错误
                is_httpx_error = isinstance(
                    e,
                    (
                        httpx.ReadTimeout,
                        httpx.ConnectTimeout,
                        httpx.ReadError,
                        httpx.ConnectError,
                    ),
                )

                if attempt_yielded_chunks:
                    message = (
                        f"{self.__class__.__name__}: 流式响应已向上游输出部分 chunk，"
                        f"遇到网络异常后不再透明重试，避免污染工具调用参数: {e}"
                    )
                    logger.warning(message)
                    raise PartialStreamConsumedError(message, e) from e

                if (is_network_error or is_httpx_error) and retry_count < max_retries:
                    # 使用指数退避 + 随机抖动，避免同时重试
                    import random

                    wait_time = min(
                        2**retry_count + random.uniform(0, 1), 30
                    )  # 最大30秒
                    error_type = "HTTP超时" if is_httpx_error else "网络"
                    if attempt_chunks:
                        logger.warning(
                            f"{self.__class__.__name__}: 流式响应已输出 {len(attempt_chunks)} 个chunk后遇到{error_type}错误，"
                            "停止本次请求避免 retry 拼接半截 tool_call"
                        )
                        partial_stream_aborted = True
                        break
                    logger.warning(
                        f"{self.__class__.__name__}: 遇到{error_type}错误，等待 {wait_time:.1f} 秒后重试 ({retry_count}/{max_retries}): {e}"
                    )
                    await asyncio.sleep(wait_time)
                    retrying_logical_request = True
                    continue  # 继续重试循环
                else:
                    # 非网络错误或已达到最大重试次数
                    if isinstance(e, APIError):
                        logger.error(
                            f"{self.__class__.__name__}: LLM流式调用失败: {format_api_error_details(e)}\n{traceback.format_exc()}"
                        )
                    else:
                        logger.error(
                            f"{self.__class__.__name__}: LLM流式调用失败: {e}\n{traceback.format_exc()}"
                        )
                    all_chunks.append(
                        chat_completion_chunk.ChatCompletionChunk(
                            id="",
                            object="chat.completion.chunk",
                            created=0,
                            model="",
                            choices=[
                                chat_completion_chunk.Choice(
                                    index=0,
                                    delta=chat_completion_chunk.ChoiceDelta(
                                        content=traceback.format_exc(),
                                        tool_calls=None,
                                    ),
                                    finish_reason="stop",
                                )
                            ],
                            usage=None,
                        )
                    )
                    raise e
            finally:
                if (
                    pending_next_request_message_ids
                    and not llm_scope_finalized
                    and not retrying_logical_request
                    and session_id
                ):
                    session_context = self._get_live_session_context(session_id)
                    if session_context is not None and attempt_yielded_chunks:
                        session_context.mark_llm_messages_consumed(
                            pending_next_request_message_ids,
                            logical_request_id,
                        )
                    elif session_context is not None:
                        release_claims = getattr(
                            session_context,
                            "release_llm_message_claims",
                            None,
                        )
                        if callable(release_claims):
                            release_claims(
                                pending_next_request_message_ids,
                                logical_request_id,
                            )
                    llm_scope_finalized = True
                # 只有在成功完成或最终失败时才记录。
                # 重试后成功也必须落盘（stream_succeeded），不能只看 retry_count==0。
                if (
                    stream_succeeded
                    or partial_stream_aborted
                    or retry_count >= max_retries
                    or (
                        last_exception
                        and not isinstance(last_exception, (RateLimitError, APIError))
                    )
                ):
                    # 将次请求记录在session context 中的llm调用记录中
                    total_time = time.time() - start_request_time
                    first_token_latency = (
                        first_token_time - start_request_time
                        if first_token_time
                        else None
                    )
                    first_token_str = (
                        f"{first_token_latency:.3f}s" if first_token_latency else "N/A"
                    )
                    chunks_for_record = (
                        [] if partial_stream_aborted else (all_chunks or attempt_chunks)
                    )
                    logger.info(
                        f"{self.__class__.__name__} | {step_name}: 调用语言模型进行流式生成，总耗时: {total_time:.3f}s, 首token延迟: {first_token_str}, 返回{len(chunks_for_record)}个chunk"
                    )
                    if session_id:
                        session_context = self._get_live_session_context(session_id)

                        # final_config 在前面已经把 'model' pop 走了，这里把模型名补回，
                        # 让 SessionContext 的 per-request tokens 统计能拿到 model 字段。
                        model_config_for_record = {**final_config, "model": model_name}
                        llm_request = {
                            "logical_request_id": logical_request_id,
                            "step_name": step_name,
                            "model_config": model_config_for_record,
                            "model": model_name,
                            "messages": serializable_messages,
                            "prompt_cache_observation": prompt_cache_observation,
                            "started_at": start_request_time,
                            "first_token_time": first_token_time,
                            "ttfb_sec": (first_token_time - start_request_time)
                            if first_token_time
                            else None,
                            "duration_sec": total_time,
                        }
                        # 将流式的chunk，进行合并成非流式的response，保存下chunk所有的记录
                        try:
                            llm_response = (
                                self.merge_stream_response_to_non_stream_response(
                                    chunks_for_record
                                )
                            )
                        except Exception:
                            logger.error(
                                f"{self.__class__.__name__}: 合并流式响应失败: {traceback.format_exc()}"
                            )
                            logger.error(
                                f"{self.__class__.__name__}: 合并流式响应失败: {all_chunks}"
                            )
                            llm_response = None
                        if session_context:
                            session_context.add_llm_request(llm_request, llm_response)  # pyright: ignore[reportArgumentType]

                            if llm_response and llm_response.usage:
                                components = (
                                    MessageManager.calculate_message_token_components(
                                        messages
                                    )
                                )
                                input_chars = components["text_chars"]
                                image_tokens = components["image_tokens"]
                                actual_tokens = llm_response.usage.prompt_tokens

                                session_context.message_manager.update_token_ratio(
                                    input_chars,
                                    actual_tokens,
                                    image_token_count=image_tokens,
                                )
                        else:
                            logger.warning(
                                f"{self.__class__.__name__}: session_context is None for session_id={session_id}, skip add_llm_request"
                            )

    async def _build_system_segments(
        self,
        session_id: Optional[str] = None,
        custom_prefix: Optional[str] = None,
        language: Optional[str] = None,
        system_prefix_override: Optional[str] = None,
        include_sections: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """构建按缓存稳定度切分的 system 文本段。

        返回 dict 形如 ``{"stable": str, "semi_stable": str, "volatile": str}``。
        命名按"自上而下越来越易变"排列，便于上层保持稳定前缀，交给供应商侧
        被动 prompt cache 自然命中：

        - ``stable``：role_definition + IDENTITY/AGENT/SOUL/USER/MEMORY md（按会话生命周期基本不变）
        - ``semi_stable``：available_skills 列表 + active_skills 内容 + skills_usage_hint
        - ``volatile``：system_context（含时间戳等动态字段）+ workspace_files + external_paths
        """
        if include_sections is None:
            include_sections = [
                "role_definition",
                "system_context",
                "active_skill",
                "workspace_files",
                "available_skills",
                "AGENT.MD",
            ]

        stable_buf = ""
        semi_buf = ""
        volatile_buf = ""

        session_context = None
        if session_id:
            session_context = self._get_live_session_context(session_id)

        # 1. Role Definition  → stable
        use_identity = False
        if "role_definition" in include_sections:
            role_content = ""
            if system_prefix_override:
                role_content = system_prefix_override
            elif hasattr(self, "SYSTEM_PREFIX_FIXED"):
                role_content = self.SYSTEM_PREFIX_FIXED  # pyright: ignore[reportAttributeAccessIssue]
            elif self.system_prefix:
                role_content = self.system_prefix
            else:
                if session_context and session_context.sandbox:
                    identity_path = os.path.join(  # pyright: ignore[reportCallIssue]
                        session_context.sandbox_agent_workspace,  # pyright: ignore[reportArgumentType]
                        "IDENTITY.md",  # pyright: ignore[reportArgumentType]
                    )
                    try:
                        if await session_context.sandbox.file_exists(identity_path):
                            role_content = await session_context.sandbox.read_file(
                                identity_path
                            )
                            use_identity = True
                    except Exception as e:
                        logger.warning(f"AgentBase: Failed to read IDENTITY.md: {e}")

                if not role_content:
                    role_content = prompt_manager.get_prompt(
                        "agent_intro_template",
                        agent="common",
                        language=language,  # pyright: ignore[reportArgumentType]
                    )

            if custom_prefix:
                role_content += f"\n\n{custom_prefix}"

            stable_buf += f"<role_definition>\n{role_content}\n</role_definition>\n"

            # system_reminder 标签语义说明：注入到 stable 段以保持高 cache 命中率
            if language and str(language).lower().startswith("zh"):
                reminder_hint = (
                    "当对话中出现 <system_reminder>...</system_reminder> 包裹的内容时，"
                    "请视为系统级状态通知（非用户输入），仅作为参考信息推进任务即可，"
                    "不需要回复或感谢这条提醒。典型场景：后台 shell 命令完成事件。"
                )
            else:
                reminder_hint = (
                    "When you see content wrapped in <system_reminder>...</system_reminder>, "
                    "treat it as a system-level status notification (not user input). "
                    "Use it as context to drive the next step; do not reply to or acknowledge the reminder itself. "
                    "A common case is background shell command completion events."
                )
            stable_buf += (
                f"<system_reminder_hint>\n{reminder_hint}\n</system_reminder_hint>\n"
            )
            if language and str(language).lower().startswith("zh"):
                runtime_context_hint = (
                    "当 user 消息中同时出现 <runtime_context>...</runtime_context> 与 "
                    "<user_request>...</user_request> 时，<runtime_context> 是系统注入的运行状态，"
                    "不是用户指令；只将 <user_request> 内的内容视为用户当前请求。"
                )
            else:
                runtime_context_hint = (
                    "When a user message contains both <runtime_context>...</runtime_context> "
                    "and <user_request>...</user_request>, treat <runtime_context> as "
                    "system-provided runtime state, not user instructions. Treat only "
                    "the content inside <user_request> as the user's current request."
                )
            stable_buf += f"<runtime_context_hint>\n{runtime_context_hint}\n</runtime_context_hint>\n"

        if session_context:
            current_time_str = self._refresh_current_time(
                session_context.system_context.get("current_time")
            )
            session_context.system_context["current_time"] = current_time_str
            system_context_info = session_context.system_context.copy()
            use_claw_mode = (
                os.environ.get("SAGE_USE_CLAW_MODE", "true").lower() == "true"
            )
            if "use_claw_mode" in system_context_info:
                use_claw_mode = system_context_info.get("use_claw_mode", use_claw_mode)
                if isinstance(use_claw_mode, str):
                    use_claw_mode = use_claw_mode.lower() == "true"
            if (
                "AGENT.MD" in include_sections
                and use_claw_mode
                and session_context.sandbox
            ):
                # 各种 .md 文件 → stable
                workspace = session_context.sandbox_agent_workspace

                try:
                    agent_md_content = await session_context.sandbox.read_file(
                        os.path.join(workspace, "AGENT.md")  # pyright: ignore[reportArgumentType,reportCallIssue]
                    )
                    if agent_md_content:
                        stable_buf += f"<agent_md>\n{agent_md_content}\n</agent_md>\n"
                except Exception as e:
                    logger.debug(f"AgentBase: AGENT.md not found or error reading: {e}")

                try:
                    soul_content = await session_context.sandbox.read_file(
                        os.path.join(workspace, "SOUL.md")  # pyright: ignore[reportArgumentType,reportCallIssue]
                    )
                    if soul_content:
                        if len(soul_content) > 300:
                            soul_content = soul_content[:300] + "……"
                        stable_buf += f"<soul>\n{soul_content}\n</soul>\n"
                except Exception as e:
                    logger.debug(f"AgentBase: SOUL.md not found or error reading: {e}")

                try:
                    user_content = await session_context.sandbox.read_file(
                        os.path.join(workspace, "USER.md")  # pyright: ignore[reportArgumentType,reportCallIssue]
                    )
                    if user_content:
                        stable_buf += f"<user>\n{user_content}\n</user>\n"
                except Exception as e:
                    logger.debug(f"AgentBase: USER.md not found or error reading: {e}")

                try:
                    memory_content = await session_context.sandbox.read_file(
                        os.path.join(workspace, "MEMORY.md")  # pyright: ignore[reportArgumentType,reportCallIssue]
                    )
                    if memory_content:
                        stable_buf += f"<memory>\n{memory_content}\n</memory>\n"
                except Exception as e:
                    logger.debug(
                        f"AgentBase: MEMORY.md not found or error reading: {e}"
                    )

                if not use_identity:
                    try:
                        identity_content = await session_context.sandbox.read_file(
                            os.path.join(workspace, "IDENTITY.md")  # pyright: ignore[reportArgumentType,reportCallIssue]
                        )
                        if identity_content:
                            if len(identity_content) > 300:
                                identity_content = identity_content[:300] + "……"
                            identity_hint = prompt_manager.get_prompt(
                                "agent_identity_extension_hint",
                                agent="common",
                                language=language or "en",
                            )
                            stable_buf += (
                                "<agent_identity_extension>\n"
                                f"{identity_hint}\n\n"
                                f"{identity_content}\n"
                                "</agent_identity_extension>\n"
                            )
                    except Exception as e:
                        logger.debug(
                            f"AgentBase: IDENTITY.md not found or error reading: {e}"
                        )

            active_skills = None
            if "active_skills" in system_context_info:
                active_skills = system_context_info.pop("active_skills")

            # 2. System Context  → volatile（含时间戳/动态字段）
            if "system_context" in include_sections:
                system_context_info.pop("todo_list", None)
                active_todos = await self._read_active_todo_list_for_context(session_id)
                if active_todos:
                    system_context_info["todo_list"] = active_todos
                volatile_buf += "<system_context>\n"
                excluded_keys = {
                    "active_skills",
                    "active_skill_instruction",
                    "可以访问的其他路径文件夹",
                    "external_paths",
                    *self.RUNTIME_CONTEXT_HIDDEN_SYSTEM_CONTEXT_KEYS,
                }
                for key, value in system_context_info.items():
                    if key in excluded_keys:
                        continue
                    if isinstance(value, (dict, list, tuple)):
                        if isinstance(value, tuple):
                            value = list(value)
                        formatted_val = json.dumps(value, ensure_ascii=False, indent=2)
                        volatile_buf += f"  <{key}>\n{formatted_val}\n  </{key}>\n"
                    else:
                        volatile_buf += f"  <{key}>{str(value)}</{key}>\n"
                volatile_buf += "</system_context>\n"

            # 3. Active Skills  → semi_stable
            if "active_skill" in include_sections and active_skills:
                semi_buf += "<active_skills>\n"
                for skill in sorted(
                    active_skills,
                    key=lambda item: str(item.get("skill_name", "unknown")),
                ):
                    skill_name = skill.get("skill_name", "unknown")
                    skill_content = skill.get("skill_content", "")
                    skill_content_escaped = (
                        str(skill_content)
                        .replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )
                    semi_buf += f"  <{skill_name}>\n{skill_content_escaped}\n  </{skill_name}>\n"
                semi_buf += "</active_skills>\n"

            # 4. Workspace Files  → volatile
            if "workspace_files" in include_sections:
                if hasattr(session_context, "sandbox") and session_context.sandbox:
                    workspace_name = session_context.system_context.get(
                        "private_workspace", ""
                    )
                    volatile_buf += "<workspace_files>\n"
                    workspace_files = prompt_manager.get_prompt(
                        "workspace_files_label",
                        agent="common",
                        language=language,  # pyright: ignore[reportArgumentType]
                    )
                    volatile_buf += workspace_files.format(workspace=workspace_name)

                    try:
                        file_tree = await session_context.sandbox.get_file_tree(
                            include_hidden=True, max_depth=2, max_items_per_dir=5
                        )
                        if not file_tree:
                            no_files = prompt_manager.get_prompt(
                                "no_files_message",
                                agent="common",
                                language=language,  # pyright: ignore[reportArgumentType]
                            )
                            volatile_buf += no_files
                        else:
                            volatile_buf += file_tree
                    except Exception as e:
                        logger.error(f"AgentBase: 获取工作空间文件树时出错: {e}")
                        no_files = prompt_manager.get_prompt(
                            "no_files_message",
                            agent="common",
                            language=language,  # pyright: ignore[reportArgumentType]
                        )
                        volatile_buf += no_files

                    volatile_buf += "</workspace_files>\n"

                external_paths = session_context.system_context.get("external_paths")
                if (
                    external_paths
                    and isinstance(external_paths, list)
                    and hasattr(session_context, "sandbox")
                    and session_context.sandbox
                ):
                    volatile_buf += "<external_paths>\n"
                    ext_paths_intro = prompt_manager.get_prompt(
                        "external_paths_intro",
                        agent="common",
                        language=language,  # pyright: ignore[reportArgumentType]
                    )
                    volatile_buf += ext_paths_intro
                    for ext_path in external_paths:
                        if isinstance(ext_path, str):
                            volatile_buf += f"Path: {ext_path}\n"
                            try:
                                ext_tree = await session_context.sandbox.get_file_tree(
                                    root_path=ext_path,
                                    include_hidden=True,
                                    max_depth=2,
                                    max_items_per_dir=5,
                                )
                                if ext_tree:
                                    volatile_buf += ext_tree
                                else:
                                    volatile_buf += "(Empty)\n"
                            except Exception as e:
                                volatile_buf += f"(Error listing files: {e})\n"
                            volatile_buf += "\n"
                    volatile_buf += "</external_paths>\n"

            # 5. Available Skills  → semi_stable
            if "available_skills" in include_sections:
                sm = session_context.effective_skill_manager
                if sm:
                    if hasattr(sm, "load_new_skills"):
                        try:
                            sm.load_new_skills()
                        except Exception as e:
                            logger.warning(f"Failed to load new skills: {e}")

                    skill_infos = sorted(
                        sm.list_skill_info(),
                        key=lambda skill: getattr(skill, "name", ""),
                    )
                    if skill_infos:
                        semi_buf += "<available_skills>\n"
                        for skill in skill_infos:
                            semi_buf += f"<skill>\n<skill_name>{skill.name}</skill_name>\n<skill_description>{skill.description[:50] + '...' if len(skill.description) > 50 else skill.description}</skill_description>\n</skill>\n"
                        semi_buf += "</available_skills>\n"

                        skills_hint = prompt_manager.get_prompt(
                            "skills_usage_hint",
                            agent="common",
                            language=language,  # pyright: ignore[reportArgumentType]
                            default="",
                        )
                        if skills_hint:
                            semi_buf += (
                                f"<skill_usage>\n{skills_hint}\n</skill_usage>\n"
                            )

        return {
            "stable": stable_buf,
            "semi_stable": semi_buf,
            "volatile": volatile_buf,
        }

    async def prepare_unified_system_message(
        self,
        session_id: Optional[str] = None,
        custom_prefix: Optional[str] = None,
        language: Optional[str] = None,
        system_prefix_override: Optional[str] = None,
        include_sections: Optional[List[str]] = None,
    ) -> MessageChunk:
        """单条 system message（向后兼容）。

        内部调用 ``_build_system_segments`` 后把三段顺序拼接成一条 system，保持
        和旧版完全一致的行为；新接入方应优先使用 ``prepare_unified_system_messages``
        以拿到分段结构，便于观察稳定 system / volatile system 的边界。
        """
        segments = await self._build_system_segments(
            session_id=session_id,
            custom_prefix=custom_prefix,
            language=language,
            system_prefix_override=system_prefix_override,
            include_sections=include_sections,
        )
        merged = segments["stable"] + segments["semi_stable"] + segments["volatile"]
        return MessageChunk(
            role=MessageRole.SYSTEM.value,
            content=merged,
            type=MessageType.SYSTEM.value,
            agent_name=self.agent_name,
        )

    async def prepare_unified_system_messages(
        self,
        session_id: Optional[str] = None,
        custom_prefix: Optional[str] = None,
        language: Optional[str] = None,
        system_prefix_override: Optional[str] = None,
        include_sections: Optional[List[str]] = None,
    ) -> List[MessageChunk]:
        """按稳定度切分的多段 system message。

        - 返回顺序固定为 ``[stable, semi_stable, volatile]``，空段会被过滤掉
        - 每条 ``MessageChunk.metadata["cache_segment"]`` 标注所属段，便于观测
          prompt 结构稳定性
        """
        segments = await self._build_system_segments(
            session_id=session_id,
            custom_prefix=custom_prefix,
            language=language,
            system_prefix_override=system_prefix_override,
            include_sections=include_sections,
        )

        out: List[MessageChunk] = []
        for seg_name in ("stable", "semi_stable", "volatile"):
            seg_text = segments.get(seg_name) or ""
            if not seg_text.strip():
                continue
            out.append(
                MessageChunk(
                    role=MessageRole.SYSTEM.value,
                    content=seg_text,
                    type=MessageType.SYSTEM.value,
                    agent_name=self.agent_name,
                    metadata={"cache_segment": seg_name},
                )
            )
        # 至少保留一条空 stable，避免下游 history 为空时 LLM 直接拒绝
        if not out:
            out.append(
                MessageChunk(
                    role=MessageRole.SYSTEM.value,
                    content="",
                    type=MessageType.SYSTEM.value,
                    agent_name=self.agent_name,
                    metadata={"cache_segment": "stable"},
                )
            )
        return out

    def _judge_delta_content_type(
        self,
        delta_content: str,
        all_tokens_str: str,
        tag_type: Optional[List[str]] = None,
    ) -> str:
        """根据已累积的输出，判断当前 delta 所属的 tag 类型。详见
        ``sagents.utils.stream_tag_parser.judge_delta_content_type``。
        """
        return _judge_delta_content_type_util(delta_content, all_tokens_str, tag_type)

    def _handle_tool_calls_chunk(
        self, chunk, tool_calls: Dict[str, Any], last_tool_call_id: str
    ) -> None:
        """
        处理工具调用数据块

        Args:
            chunk: LLM响应块
            tool_calls: 工具调用字典
            last_tool_call_id: 最后的工具调用ID
        """
        if not chunk.choices or not chunk.choices[0].delta.tool_calls:
            return

        for tool_call in chunk.choices[0].delta.tool_calls:
            tc_id = (
                tool_call.id
                if tool_call.id is not None and len(tool_call.id) > 0
                else ""
            )
            tc_index = getattr(tool_call, "index", None)
            temp_key = f"__tool_call_index_{tc_index}" if tc_index is not None else None

            target_key = None
            if tc_id and tc_id in tool_calls:
                target_key = tc_id
            elif tc_index is not None:
                # 优先按 index 复用已有的 tool_call，避免多 tool 场景下串台
                for existing_key, existing_value in tool_calls.items():
                    if (
                        isinstance(existing_value, dict)
                        and existing_value.get("index") == tc_index
                    ):
                        target_key = existing_key
                        break
                if target_key is None and temp_key and temp_key in tool_calls:
                    target_key = temp_key
                if target_key is None and tc_id:
                    target_key = tc_id
                if target_key is None and temp_key:
                    target_key = temp_key
                if (
                    target_key is None
                    and last_tool_call_id
                    and last_tool_call_id in tool_calls
                ):
                    target_key = last_tool_call_id
                if target_key is None and tool_calls:
                    target_key = next(reversed(tool_calls))
            elif last_tool_call_id and last_tool_call_id in tool_calls:
                target_key = last_tool_call_id
            elif tc_id:
                target_key = tc_id
            elif tool_calls:
                target_key = next(reversed(tool_calls))

            if target_key is None:
                continue

            entry = tool_calls.get(target_key)
            if entry is None:
                logger.info(
                    f"{self.agent_name}: 检测到新工具调用: "
                    f"{tc_id or target_key}, index={tc_index}, 工具名称: {tool_call.function.name}"
                )
                entry = {
                    "id": tc_id or "",
                    "index": tc_index,
                    "type": tool_call.type or "function",
                    "function": {
                        "name": tool_call.function.name or "",
                        "arguments": tool_call.function.arguments or "",
                    },
                }
                tool_calls[target_key] = entry
            else:
                if tc_id and not entry.get("id"):
                    entry["id"] = tc_id
                    if target_key != tc_id:
                        tool_calls[tc_id] = entry
                        del tool_calls[target_key]
                        target_key = tc_id
                if tc_index is not None and entry.get("index") is None:
                    entry["index"] = tc_index
                if tool_call.function.name:
                    logger.info(
                        f"{self.agent_name}: 更新工具调用: {entry.get('id') or target_key}, "
                        f"index={tc_index}, 工具名称: {tool_call.function.name}"
                    )
                    entry["function"]["name"] = tool_call.function.name
                if tool_call.function.arguments:
                    entry["function"]["arguments"] += tool_call.function.arguments

    def _create_tool_call_error_message(
        self,
        tool_name: str,
        raw_arguments: str,
        error_reason: Optional[str] = None,
        language: Optional[str] = None,
    ) -> MessageChunk:
        """
        创建工具调用错误消息，当JSON解析失败时保留给后续 LLM 修正

        Args:
            tool_name: 工具名称
            raw_arguments: 原始参数字符串
            error_reason: 错误原因
            language: 响应语言

        Returns:
            MessageChunk: 错误消息块
        """
        # 分析参数长度，给出优化建议
        param_length = len(raw_arguments)
        suggestions = []

        if param_length > 2000:
            suggestions.append(
                t("runtime.tool_call_parse.suggestion.too_long_split", language)
            )
            suggestions.append(
                t("runtime.tool_call_parse.suggestion.too_long_file", language)
            )

        if "{" in raw_arguments and raw_arguments.count("{") != raw_arguments.count(
            "}"
        ):
            suggestions.append(t("runtime.tool_call_parse.suggestion.braces", language))

        if '"' in raw_arguments:
            quote_count = raw_arguments.count('"')
            if quote_count % 2 != 0:
                suggestions.append(
                    t("runtime.tool_call_parse.suggestion.quotes", language)
                )

        if "\\" in raw_arguments:
            suggestions.append(
                t("runtime.tool_call_parse.suggestion.backslash", language)
            )

        if not suggestions:
            suggestions.append(
                t("runtime.tool_call_parse.suggestion.check_json", language)
            )
            suggestions.append(
                t("runtime.tool_call_parse.suggestion.double_quotes", language)
            )
            suggestions.append(t("runtime.tool_call_parse.suggestion.commas", language))

        # 截断过长的参数显示
        display_args = (
            raw_arguments[:200] + "..." if len(raw_arguments) > 200 else raw_arguments
        )
        error_reason = error_reason or t("runtime.tool_call_parse.reason", language)

        content = f"""{t("runtime.tool_call_parse.title", language, {"tool_name": tool_name})}

**{t("runtime.tool_call_parse.reason_title", language)}**: {error_reason}

**{t("runtime.tool_call_parse.raw_arguments", language)}**:
```
{display_args}
```

**{t("runtime.tool_call_parse.suggestions_title", language)}**:
{chr(10).join(suggestions)}

{t("runtime.tool_call_parse.next_step", language)}"""

        return MessageChunk(
            role=MessageRole.ASSISTANT.value,
            content=content,
            message_id=str(uuid.uuid4()),
            message_type=MessageType.AGENT_EXECUTION_ERROR.value,
            agent_name=self.agent_name,
            metadata=self._next_request_runtime_metadata(
                runtime_diagnostic_source="tool_call_argument_parse",
                tool_name=tool_name,
            ),
        )

    def _create_tool_call_message(
        self, tool_call: Dict[str, Any]
    ) -> List[MessageChunk]:
        """
        创建工具调用消息

        Args:
            tool_call: 工具调用信息

        Returns:
            List[MessageChunk]: 工具调用消息列表
        """
        # 格式化工具参数显示
        # 兼容两种分隔符
        args = tool_call["function"]["arguments"]
        if "```<｜tool▁call▁end｜>" in args:
            logger.debug(f"{self.agent_name}: 原始错误参数(▁): {args}")
            tool_call["function"]["arguments"] = args.split("```<｜tool▁call▁end｜>")[0]
        elif "```<｜tool call end｜>" in args:
            logger.debug(f"{self.agent_name}: 原始错误参数(space): {args}")
            tool_call["function"]["arguments"] = args.split("```<｜tool call end｜>")[0]

        function_params = tool_call["function"]["arguments"]
        if len(function_params) > 0:
            try:
                function_params = json.loads(function_params)
            except json.JSONDecodeError:
                try:
                    # 尝试使用 eval 解析，并注入 JSON 常量
                    function_params = eval(
                        function_params,
                        {"__builtins__": None},
                        {"true": True, "false": False, "null": None},
                    )
                except Exception:
                    logger.error(
                        f"{self.agent_name}: 第一次参数解析报错，再次进行参数解析失败"
                    )
                    logger.error(
                        f"{self.agent_name}: 原始参数: {tool_call['function']['arguments']}"
                    )

            if isinstance(function_params, str):
                try:
                    function_params = json.loads(function_params)
                except json.JSONDecodeError:
                    try:
                        # 再次尝试使用 eval 解析
                        function_params = eval(
                            function_params,
                            {"__builtins__": None},
                            {"true": True, "false": False, "null": None},
                        )
                    except Exception:
                        logger.error(
                            f"{self.agent_name}: 解析完参数化依旧后是str，再次进行参数解析失败"
                        )
                        logger.error(
                            f"{self.agent_name}: 原始参数: {tool_call['function']['arguments']}"
                        )
                        logger.error(
                            f"{self.agent_name}: 工具参数格式错误: {function_params}"
                        )
                        logger.error(
                            f"{self.agent_name}: 工具参数类型: {type(function_params)}"
                        )

            formatted_params = ""
            if isinstance(function_params, dict):
                tool_call["function"]["arguments"] = json.dumps(
                    function_params, ensure_ascii=False
                )
                for param, value in function_params.items():
                    formatted_params += (
                        f"{param} = {json.dumps(value, ensure_ascii=False)}, "
                    )
                formatted_params = formatted_params.rstrip(", ")
            else:
                # 只有当非空且非字典时才记录错误（SimpleAgent逻辑兼容）
                if function_params:
                    logger.warning(
                        f"{self.agent_name}: 参数解析结果不是字典: {type(function_params)}"
                    )
                formatted_params = str(function_params)
        else:
            formatted_params = ""

        tool_call["function"]["name"]

        # 将content 整理成函数调用的形式
        return [
            MessageChunk(
                role="assistant",
                tool_calls=[
                    {
                        "id": tool_call["id"],
                        "type": tool_call["type"],
                        "function": {
                            "name": tool_call["function"]["name"],
                            "arguments": tool_call["function"]["arguments"],
                        },
                    }
                ],
                message_type=MessageType.TOOL_CALL.value,
                message_id=str(uuid.uuid4()),
                # content=f"{tool_name}({formatted_params})",
                content=None,
                agent_name=self.agent_name,
            )
        ]

    async def _execute_tool(
        self,
        tool_call: Dict[str, Any],
        tool_manager: Optional[ToolManager],
        messages_input: List[Any],
        session_id: str,
        session_context: Optional[SessionContext] = None,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        执行工具

        Args:
            tool_call: 工具调用信息
            tool_manager: 工具管理器
            messages_input: 输入消息列表
            session_id: 会话ID

        Yields:
            List[MessageChunk]: 消息块列表
        """
        tool_name = tool_call["function"]["name"]
        if session_context is None and session_id:
            try:
                session_context = self._get_live_session_context(session_id)
            except Exception as e:
                logger.debug(
                    f"{self.agent_name}: 无法通过 session_id 获取 session_context: {e}"
                )
        language = self._language_from_session_context(session_context)

        try:
            # 解析并执行工具调用
            if len(tool_call["function"]["arguments"]) > 0:
                arguments = json.loads(tool_call["function"]["arguments"])
            else:
                arguments = {}

            if not isinstance(arguments, dict):
                async for chunk in self._handle_tool_error(
                    tool_call["id"],
                    tool_name,
                    Exception(t("runtime.tool.error.arguments_not_object", language)),
                    language,
                ):
                    yield chunk
                return

            if not tool_manager:
                raise ValueError("Tool manager is not provided")

            # 构造调用参数，确保 session_id 正确传递且不重复
            call_kwargs = arguments.copy()
            # 如果 arguments 中有保留身份字段，移除它们（因为会作为可信上下文传递）
            call_kwargs.pop("session_id", None)
            call_kwargs.pop("user_id", None)

            with _bind_tool_progress_context(session_id, tool_call["id"]):
                try:
                    tool_response = await tool_manager.run_tool_async(
                        tool_name,
                        session_id=session_id,
                        tool_call_id=tool_call["id"],
                        **call_kwargs,
                    )
                finally:
                    try:
                        await _emit_tool_progress_closed()
                    except Exception:
                        pass

            # 检查是否为流式响应
            if hasattr(tool_response, "__iter__") and not isinstance(
                tool_response, (str, bytes)
            ):
                # 处理流式响应
                logger.debug(f"{self.agent_name}: 收到流式工具响应")
                try:
                    for chunk in tool_response:
                        # 普通工具：添加必要的元数据
                        if isinstance(chunk, list):
                            # 转化成message chunk
                            message_chunks = []
                            for message in chunk:
                                if isinstance(message, dict):
                                    message_chunks.append(
                                        MessageChunk(
                                            role=MessageRole.TOOL.value,
                                            content=message["content"],
                                            tool_call_id=tool_call["id"],
                                            message_id=str(uuid.uuid4()),
                                            message_type=MessageType.TOOL_CALL_RESULT.value,
                                            agent_name=self.agent_name,
                                        )
                                    )
                            yield message_chunks
                        else:
                            # 单个消息
                            if isinstance(chunk, dict):
                                message_chunk_ = MessageChunk(
                                    role=MessageRole.TOOL.value,
                                    content=chunk["content"],
                                    tool_call_id=tool_call["id"],
                                    message_id=str(uuid.uuid4()),
                                    message_type=MessageType.TOOL_CALL_RESULT.value,
                                    agent_name=self.agent_name,
                                )
                                yield [message_chunk_]
                except Exception as e:
                    logger.error(
                        f"{self.agent_name}: 处理流式工具响应时发生错误: {str(e)}"
                    )
                    async for chunk in self._handle_tool_error(
                        tool_call["id"], tool_name, e, language
                    ):
                        yield chunk
            else:
                # 处理非流式响应
                processed_response = self.process_tool_response(
                    tool_response,  # pyright: ignore[reportArgumentType]
                    tool_call["id"],  # pyright: ignore[reportArgumentType]
                )
                yield processed_response

        except asyncio.CancelledError:
            logger.warning(
                f"{self.agent_name}: 工具 {tool_name} 收到取消信号, "
                f"tool_call_id={tool_call['id']}"
            )
            yield self._create_tool_cancelled_result(
                tool_call["id"], tool_name, language
            )
            raise
        except Exception as e:
            logger.error(
                f"{self.agent_name}: 执行工具 {tool_name} 时发生错误: {str(e)}"
            )
            logger.error(f"{self.agent_name}: 堆栈: {traceback.format_exc()}")
            async for chunk in self._handle_tool_error(
                tool_call["id"], tool_name, e, language
            ):
                yield chunk

    async def _handle_tool_error(
        self,
        tool_call_id: str,
        tool_name: str,
        error: Exception,
        language: Optional[str] = None,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        处理工具执行错误

        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            error: 错误信息

        Yields:
            List[MessageChunk]: 错误消息块列表
        """
        error_message = t(
            "runtime.tool.error.execution_failed",
            language,
            {"tool_name": tool_name, "message": str(error)},
        )
        logger.error(f"{self.agent_name}: {error_message}")

        error_chunk = MessageChunk(
            role="tool",
            content=json.dumps({"error": error_message}, ensure_ascii=False),
            tool_call_id=tool_call_id,
            message_id=str(uuid.uuid4()),
            message_type=MessageType.TOOL_CALL_RESULT.value,
            metadata={"tool_execution_status": "error"},
        )

        yield [error_chunk]

    def _create_tool_cancelled_result(
        self,
        tool_call_id: str,
        tool_name: str,
        language: Optional[str] = None,
    ) -> List[MessageChunk]:
        message = t(
            "runtime.tool.error.execution_cancelled",
            language,
            {"tool_name": tool_name},
        )
        return [
            MessageChunk(
                role=MessageRole.TOOL.value,
                content=json.dumps(
                    {
                        "error": True,
                        "error_type": "EXECUTION_CANCELLED",
                        "message": message,
                        "tool_name": tool_name,
                        "status": "cancelled",
                    },
                    ensure_ascii=False,
                ),
                tool_call_id=tool_call_id,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.TOOL_CALL_RESULT.value,
                agent_name=self.agent_name,
                metadata={"tool_execution_status": "cancelled"},
            )
        ]

    def process_tool_response(
        self, tool_response: str, tool_call_id: str
    ) -> List[MessageChunk]:
        """
        处理工具执行响应

        Args:
            tool_response: 工具执行响应
            tool_call_id: 工具调用ID

        Returns:
            List[MessageChunk]: 处理后的结果消息
        """
        tool_response_dict: Any = None
        try:
            tool_response_dict = json.loads(tool_response)

            if "content" in tool_response_dict:
                content = tool_response_dict["content"]
            else:
                content = tool_response
        except (json.JSONDecodeError, TypeError):
            content = tool_response

        # 如果 content 还是 dict/list，转成 json string
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False)
        else:
            content = str(content)

        execution_status = "success"
        if isinstance(tool_response_dict, dict) and (
            tool_response_dict.get("success") is False
            or tool_response_dict.get("error") not in (None, False, "")
            or tool_response_dict.get("status") == "error"
        ):
            execution_status = "error"

        return [
            MessageChunk(
                role=MessageRole.TOOL.value,
                content=content,
                tool_call_id=tool_call_id,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.TOOL_CALL_RESULT.value,
                agent_name=self.agent_name,
                metadata={"tool_execution_status": execution_status},
            )
        ]

    def merge_stream_response_to_non_stream_response(self, chunks):
        """将流式的 chunk 合并成非流式的 response。详见
        ``sagents.utils.stream_merger.merge_chat_completion_chunks``。
        """
        return _merge_chunks_util(chunks)

    async def _handle_tool_calls(
        self,
        tool_calls: Dict[str, Any],
        tool_manager: Optional[ToolManager],
        messages_input: List[Any],
        session_id: str,
        handle_complete_task: bool = False,
        emit_tool_call_message: bool = True,
        execute_concurrently: bool = True,
    ) -> AsyncGenerator[tuple[List[MessageChunk], bool], None]:
        """
        处理工具调用

        Args:
            tool_calls: 工具调用字典
            tool_manager: 工具管理器
            messages_input: 输入消息列表
            session_id: 会话ID
            handle_complete_task: 是否处理complete_task工具（TaskExecutorAgent需要）
            execute_concurrently: 是否并发执行工具；关闭时按 LLM 返回顺序逐个执行

        Yields:
            tuple[List[MessageChunk], bool]: (消息块列表, 是否完成任务)
        """
        logger.info(f"{self.agent_name}: LLM响应包含 {len(tool_calls)} 个工具调用")
        session_context: Optional[SessionContext] = None
        if session_id:
            try:
                session_context = self._get_live_session_context(session_id)
            except Exception:
                session_context = None
        language = self._language_from_session_context(session_context)

        executable_tool_calls: List[Dict[str, Any]] = []

        for tool_call_id, tool_call in tool_calls.items():
            # 增加让出主线程逻辑，防止工具循环处理导致卡死
            await asyncio.sleep(0)

            tool_name = tool_call["function"]["name"]
            raw_arguments = tool_call["function"]["arguments"]

            # 验证工具参数是否为有效的JSON
            # 将复杂的解析逻辑放到线程池中执行
            is_valid_json = False
            parsed_arguments = None

            try:
                # 使用线程池执行同步的解析逻辑
                parsed_arguments, is_valid_json = await asyncio.to_thread(
                    self._parse_and_validate_json, raw_arguments
                )
            except Exception as e:
                logger.error(f"{self.agent_name}: JSON解析异常: {e}")
                is_valid_json = False

            # 如果 JSON 解析失败，保留给后续 LLM 修正，但不暴露给客户端。
            if not is_valid_json:
                logger.warning(
                    f"{self.agent_name}: 工具参数JSON解析失败，转换为隐藏 runtime diagnostic"
                )
                error_message = self._create_tool_call_error_message(
                    tool_name=tool_name,
                    raw_arguments=raw_arguments,
                    language=language,
                )
                rejection_results = (
                    self._create_streamed_tool_rejection_results(
                        {tool_call_id: tool_call},
                        code="invalid_tool_arguments",
                    )
                    if not emit_tool_call_message
                    else []
                )
                yield ([*rejection_results, error_message], False)
                continue

            # 更新解析后的参数
            tool_call["function"]["arguments"] = json.dumps(
                parsed_arguments, ensure_ascii=False
            )

            # 检查是否为complete_task（仅TaskExecutorAgent需要处理）
            if handle_complete_task and tool_name == "complete_task":
                logger.info(f"{self.agent_name}: complete_task，停止执行")
                yield (
                    [
                        MessageChunk(
                            role=MessageRole.ASSISTANT.value,
                            content="All user requirements have been satisfied",
                            message_id=str(uuid.uuid4()),
                            message_type=MessageType.DO_SUBTASK_RESULT.value,
                        )
                    ],
                    True,
                )
                return

            # 如果上游已经把 tool_call 以流式消息发出来了，这里就不要重复发卡片了。
            if emit_tool_call_message:
                output_messages = self._create_tool_call_message(tool_call)
                yield (output_messages, False)

            if not execute_concurrently:
                async for message_chunk_list in self._execute_tool(
                    tool_call=tool_call,
                    tool_manager=tool_manager,
                    messages_input=messages_input,
                    session_id=session_id,
                ):
                    yield (message_chunk_list, False)
                continue

            executable_tool_calls.append(tool_call)

        result_queue: asyncio.Queue[
            tuple[str, int, Optional[List[MessageChunk]]]
        ] = asyncio.Queue()

        async def execute_and_publish_tool_result(
            index: int,
            tool_call: Dict[str, Any],
        ) -> None:
            tool_name = tool_call["function"]["name"]
            logger.info(f"{self.agent_name}: 执行工具 {tool_name}")

            try:
                async for message_chunk_list in self._execute_tool(
                    tool_call=tool_call,
                    tool_manager=tool_manager,
                    messages_input=messages_input,
                    session_id=session_id,
                    session_context=session_context,
                ):
                    result_queue.put_nowait(("result", index, message_chunk_list))
            finally:
                result_queue.put_nowait(("done", index, None))

        if not executable_tool_calls:
            return

        semaphore = asyncio.Semaphore(TOOL_CALL_CONCURRENCY_LIMIT)

        async def run_with_limit(index: int, tool_call: Dict[str, Any]) -> None:
            started = False
            try:
                async with semaphore:
                    started = True
                    await execute_and_publish_tool_result(index, tool_call)
            except asyncio.CancelledError:
                if not started:
                    result_queue.put_nowait(
                        (
                            "result",
                            index,
                            self._create_tool_cancelled_result(
                                tool_call["id"],
                                tool_call["function"]["name"],
                                language,
                            ),
                        )
                    )
                    result_queue.put_nowait(("done", index, None))
                raise

        tasks = [
            asyncio.create_task(
                run_with_limit(index, tool_call),
                name=f"tool-call-{tool_call['id']}",
            )
            for index, tool_call in enumerate(executable_tool_calls)
        ]
        completed = 0
        try:
            while completed < len(tasks):
                event, _index, message_chunk_list = await result_queue.get()
                if event == "done":
                    completed += 1
                    continue
                if message_chunk_list:
                    yield (message_chunk_list, False)
        except asyncio.CancelledError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            unconsumed_messages: List[MessageChunk] = []
            while not result_queue.empty():
                event, _index, message_chunk_list = result_queue.get_nowait()
                if event == "result" and message_chunk_list:
                    unconsumed_messages.extend(message_chunk_list)
            if session_context is not None and unconsumed_messages:
                session_context.add_messages(unconsumed_messages)
            raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _parse_and_validate_json(self, raw_arguments: str) -> tuple[Any, bool]:
        """
        在线程池中运行的同步JSON解析逻辑
        使用安全的 ast.literal_eval 替代 eval，避免代码注入风险
        """
        import ast

        try:
            parsed = json.loads(raw_arguments)
            return parsed, True
        except json.JSONDecodeError:
            # 尝试使用 ast.literal_eval 安全解析
            # 仅支持基本数据类型：字符串、数字、元组、列表、字典、集合、布尔值、None
            try:
                parsed = ast.literal_eval(raw_arguments)
                # 验证解析结果是否为字典（工具参数必须是字典）
                if not isinstance(parsed, dict):
                    return None, False
                # 验证解析结果是否可以序列化为JSON
                json.dumps(parsed)
                return parsed, True
            except (ValueError, SyntaxError, TypeError):
                return None, False

    def _should_abort_due_to_session(
        self, session_context: SessionContext, session_id: Optional[str] = None
    ) -> bool:
        """检查会话/父会话状态，命中即返回 True。详见
        ``sagents.utils.agent_session_helper.should_abort_due_to_session``。
        """
        return _should_abort_due_to_session_util(
            session_context,
            log_prefix=self.__class__.__name__,
        )
