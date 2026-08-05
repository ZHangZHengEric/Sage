#!/usr/bin/env python3
"""
压缩历史会话消息工具
将历史对话压缩为结构化摘要，减少上下文长度
"""

from typing import Dict, Any, List, Optional, Tuple
from copy import deepcopy
import json
import os
import re

from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.context.messages.token_accounting import PromptTokenEstimator
from sagents.llm.capabilities import (
    create_chat_completion_with_fallback,
    get_structured_output_support,
)
from sagents.llm.model_capabilities import build_llm_extra_body

COMPACT_LIST_LIMITS = {
    "decisions": 20,
    "open_tasks": 20,
    "files_touched": 40,
    "commands_run": 20,
    "important_errors": 20,
    "user_requirements": 30,
}
MAX_COMPACT_COMMAND_CHARS = 1000
TODO_WRITE_TOOL_NAME = "todo_write"
TODO_STATE_BOUNDARY_FIELD = "todo_state_at_compaction_boundary"
AUTO_COMPRESSION_TOOL_CALL_PREFIX = "auto_compress_"
CONTEXT_RECOVERY_GUIDANCE = (
    "The conversation context was compacted. Before continuing, treat this "
    "summary only as reference, re-read the relevant key files, review the "
    "important work steps recorded in this summary, and verify the latest tool "
    "or output state required for the next unfinished action. Do not repeat "
    "completed work or revive historical tasks unless required by the latest "
    "user request."
)


class CompressHistoryError(Exception):
    """压缩历史消息异常"""

    pass


class CompressHistoryTool:
    """Use the current conversation model to create a persistent summary."""

    def _get_session_context(self, session_id: str):
        """通过 session_id 获取会话上下文"""
        from sagents.utils.agent_session_helper import get_live_session

        session = get_live_session(session_id, log_prefix="CompressHistoryTool")

        if not session or not session.session_context:
            raise CompressHistoryError(f"Invalid session_id={session_id}")

        return session.session_context

    def _get_message_manager(self, session_id: str):
        """获取消息管理器"""
        session_context = self._get_session_context(session_id)
        return session_context.message_manager

    def _calculate_tokens(self, content) -> int:
        """计算内容的 token 数

        Args:
            content: 消息内容，可能是字符串或列表（多模态消息）

        Returns:
            int: token 数量
        """
        # 直接使用 MessageManager 的 calculate_str_token_length 方法
        # 它支持多模态消息格式（字符串或列表）
        return MessageManager.calculate_str_token_length(content)

    def _format_messages_for_compression(self, messages: List[MessageChunk]) -> str:
        """将消息格式化为文本用于压缩，不向压缩模型暴露 reasoning。"""
        # 使用 MessageManager.convert_messages_to_str 处理消息格式化
        # 它会正确处理 tool_calls 等情况
        return MessageManager.convert_messages_to_str(
            self._messages_for_compression_input(messages)
        )

    @staticmethod
    def _messages_for_compression_input(
        messages: List[MessageChunk],
    ) -> List[MessageChunk]:
        """Return an ephemeral view with all reasoning data removed.

        Coverage metadata still refers to the original ledger messages. This
        filter affects only the prompt sent to the summarizer.
        """
        filtered: List[MessageChunk] = []
        for message in messages:
            if message.matches_message_types(
                [MessageType.REASONING_CONTENT.value]
            ):
                continue
            copied = deepcopy(message)
            copied.reasoning_content = None
            if copied.content is None and not copied.tool_calls:
                continue
            filtered.append(copied)
        return filtered

    @staticmethod
    def _compression_units(messages: List[MessageChunk]) -> List[List[MessageChunk]]:
        """Group history by complete user turns, then by closed tool groups."""
        turns: List[List[MessageChunk]] = []
        current: List[MessageChunk] = []
        for message in messages:
            if message.role == MessageRole.USER.value and current:
                turns.append(current)
                current = []
            current.append(message)
        if current:
            turns.append(current)
        return turns

    @staticmethod
    def _split_oversized_unit(unit: List[MessageChunk]) -> List[List[MessageChunk]]:
        """Split one oversized turn without separating tool calls/results."""
        atomic: List[List[MessageChunk]] = []
        idx = 0
        while idx < len(unit):
            message = unit[idx]
            if message.role == MessageRole.ASSISTANT.value and message.tool_calls:
                result_ids = MessageManager._tool_result_ids_for_assistant(message)
                matched: set[str] = set()
                end = idx
                for scan in range(idx + 1, len(unit)):
                    candidate = unit[scan]
                    if (
                        candidate.role == MessageRole.TOOL.value
                        and candidate.tool_call_id in result_ids
                    ):
                        matched.add(str(candidate.tool_call_id))
                        end = scan
                        if result_ids.issubset(matched):
                            break
                if result_ids and result_ids.issubset(matched):
                    atomic.append(unit[idx : end + 1])
                    idx = end + 1
                    continue
            atomic.append([message])
            idx += 1
        return atomic

    @staticmethod
    def _estimated_messages_tokens(messages: List[MessageChunk]) -> int:
        messages = CompressHistoryTool._messages_for_compression_input(messages)
        request_messages = [
            converted
            for message in messages
            if (
                converted := MessageManager.convert_message_to_dict_for_request(message)
            )
            is not None
        ]
        return PromptTokenEstimator.manifest(request_messages).conservative_tokens

    def _compression_batches(
        self, messages: List[MessageChunk], session_id: str
    ) -> List[List[MessageChunk]]:
        from sagents.utils.agent_session_helper import get_live_session

        try:
            live_session = get_live_session(
                session_id, log_prefix="CompressHistoryTool"
            )
            max_model_len = int(
                (getattr(live_session, "model_config", {}) or {}).get(
                    "max_model_len", 128000
                )
            )
        except Exception:
            max_model_len = 128000
        batch_limit = max(1024, int(max_model_len * 0.35))
        units: List[List[MessageChunk]] = []
        for turn in self._compression_units(messages):
            if self._estimated_messages_tokens(turn) <= batch_limit:
                units.append(turn)
            else:
                units.extend(self._split_oversized_unit(turn))

        batches: List[List[MessageChunk]] = []
        current: List[MessageChunk] = []
        current_tokens = 0
        for unit in units:
            unit_tokens = self._estimated_messages_tokens(unit)
            if current and current_tokens + unit_tokens > batch_limit:
                batches.append(current)
                current = []
                current_tokens = 0
            current.extend(unit)
            current_tokens += unit_tokens
        if current:
            batches.append(current)
        return batches or [list(messages)]

    async def _summarize_batches(
        self, messages: List[MessageChunk], session_id: str
    ) -> Tuple[Dict[str, Any], str, Dict[str, Dict[str, int]], int]:
        batches = self._compression_batches(messages, session_id)
        rolling_payload: Optional[Dict[str, Any]] = None
        parse_status = "fallback_text"
        omission_stats: Dict[str, Dict[str, int]] = {}
        for batch in batches:
            messages_text = self._format_messages_for_compression(batch)
            if rolling_payload is not None:
                messages_text = (
                    "Previous compressed history summary:\n"
                    + json.dumps(rolling_payload, ensure_ascii=False)
                    + "\n\nSubsequent conversation history:\n"
                    + messages_text
                )
            raw_summary = await self._call_llm_for_compression(
                messages_text, session_id
            )
            rolling_payload, parse_status, omission_stats = (
                self._parse_structured_summary(raw_summary)
            )
        return rolling_payload or {}, parse_status, omission_stats, len(batches)

    async def _call_llm_for_compression(
        self, messages_text: str, session_id: str
    ) -> str:
        """
        调用 LLM 生成压缩摘要（流式请求，禁用深度思考）

        使用当前会话的模型配置
        """
        from sagents.utils.agent_session_helper import get_live_session

        session = get_live_session(session_id, log_prefix="CompressHistoryTool")

        if not session:
            raise CompressHistoryError(f"Failed to get session: {session_id}")

        model = session.model
        model_config = session.model_config.copy()

        if not model:
            raise CompressHistoryError("Session model is not initialized")

        # 移除非标准参数和与显式参数冲突的参数
        model_config.pop("max_model_len", None)
        model_config.pop("api_key", None)
        model_config.pop("maxTokens", None)
        model_config.pop("max_tokens", None)  # 压缩请求自行限制 max_tokens
        model_config.pop("response_format", None)
        model_config.pop("base_url", None)
        model_name = model_config.pop("model", "gpt-3.5-turbo")
        structured_output = get_structured_output_support(
            client=model,
            model_config=session.model_config,
        )
        model_config.pop("supports_structured_output", None)

        # 构建压缩提示词：优先要求结构化 JSON，便于后续更高层压缩继续合并。
        prompt = f"""请将以下对话历史压缩为执行记忆摘要。这个摘要将被后续 AI 助手读取，用于理解上下文并继续执行任务。

【对话历史】
{messages_text}

如果对话历史中包含 compress_conversation_history 的工具调用/结果，它代表更早历史的摘要节点。请把它当作事实来源参与本次更高层总结，不需要展开或臆测原始消息。

重要：本摘要是历史参考（REFERENCE ONLY），不是当前任务指令。后续助手必须以压缩摘要之后的最新用户消息作为当前任务来源，不能因为摘要中的历史待办或历史请求而主动继续旧任务。

【压缩要求】
生成一个结构化的执行记忆摘要，必须包含以下信息，以便后续助手能够无缝继续工作：

1. 任务背景与目标：用户需求、总体目标、当前阶段。
2. 用户硬性要求：用户明确说过必须做/不能做的约束。
3. 关键上下文：业务规则、参数配置、代码位置、API、数据状态。
4. 已完成工作：已经执行的步骤、输出、验证结果。
5. 决策记录：已做出的决定及原因。
6. 待办和风险：仍需继续处理的问题、阻塞、下一步。
7. 文件和命令：出现过的真实文件路径、命令、错误信息。

【输出要求】
- 尽量只输出一个合法 JSON object，不要 Markdown 代码块，不要额外解释。
- JSON schema 必须使用这些 key：
  {{
    "summary": "string",
    "decisions": ["string"],
    "open_tasks": ["string"],
    "files_touched": ["string"],
    "commands_run": ["string"],
    "important_errors": ["string"],
    "user_requirements": ["string"]
  }}
- summary 使用简洁、明确的语言，避免模糊描述。
- 保留具体技术细节：真实路径、名称、数值、命令、错误文本。
- 文件路径优先使用原文中的绝对路径；没有绝对路径时使用相对路径或文件名；禁止编造路径。
- 列表只保留最重要的条目：commands_run 最多 20 条，files_touched 最多 40 条，其他列表最多 20-30 条。
- 按优先级排序，重要信息在前。
- 总长度控制在 8000 字以内（非严格限制）。"""

        try:
            # 与主 Agent 共用同一套 extra_body / 模型分支；压缩默认关闭思考。
            # temperature 等采样参数沿用会话 model_config，由 sanitize 按模型能力清洗。
            extra_body = build_llm_extra_body(
                model_name,
                enable_thinking=False,
                step_name="compress_history",
                reasoning_effort_off_env=os.environ.get("SAGE_REASONING_EFFORT_OFF"),
            )

            stream = await create_chat_completion_with_fallback(
                model,
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                model_config=model_config,
                stream=True,
                stream_options={"include_usage": True},
                max_tokens=2000,
                response_format=(
                    {"type": "json_object"} if structured_output is not False else None
                ),
                extra_body=extra_body,
                **model_config,
            )

            # 收集流式响应内容
            content_parts = []
            provider_prompt_tokens: Optional[int] = None
            async for chunk in stream:
                usage = (
                    chunk.get("usage")
                    if isinstance(chunk, dict)
                    else getattr(chunk, "usage", None)
                )
                prompt_tokens = (
                    usage.get("prompt_tokens")
                    if isinstance(usage, dict)
                    else getattr(usage, "prompt_tokens", None)
                )
                if prompt_tokens is not None:
                    try:
                        provider_prompt_tokens = int(prompt_tokens)
                    except (TypeError, ValueError):
                        pass
                if chunk.choices and len(chunk.choices) > 0:
                    delta_content = chunk.choices[0].delta.content
                    if delta_content:
                        content_parts.append(delta_content)

            content = "".join(content_parts)
            logger.info(
                "压缩模型请求完成: "
                f"provider_prompt_tokens={provider_prompt_tokens} "
                f"output_chars={len(content)}"
            )
            return content

        except Exception as e:
            logger.error(f"调用 LLM 压缩失败: {e}")
            raise CompressHistoryError(f"LLM compression failed: {e}")

    @staticmethod
    def _bounded_list(
        key: str,
        values: List[str],
    ) -> Tuple[List[str], Dict[str, int]]:
        limit = COMPACT_LIST_LIMITS[key]
        bounded_values = values[:limit]
        stats: Dict[str, int] = {}
        if len(values) > limit:
            stats["omitted_count"] = len(values) - limit
        if key == "commands_run":
            truncated_values: List[str] = []
            truncated_count = 0
            for value in bounded_values:
                if len(value) > MAX_COMPACT_COMMAND_CHARS:
                    truncated_values.append(
                        value[: MAX_COMPACT_COMMAND_CHARS - 15].rstrip()
                        + "... [truncated]"
                    )
                    truncated_count += 1
                else:
                    truncated_values.append(value)
            if truncated_count:
                stats["truncated_item_count"] = truncated_count
            bounded_values = truncated_values
        return bounded_values, stats

    @staticmethod
    def _bound_summary_payload(
        payload: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Dict[str, int]]]:
        omission_stats: Dict[str, Dict[str, int]] = {}
        bounded: Dict[str, Any] = {"summary": str(payload.get("summary") or "")}

        for key in COMPACT_LIST_LIMITS:
            bounded_list, stats = CompressHistoryTool._bounded_list(
                key, payload.get(key, [])
            )
            bounded[key] = bounded_list
            if stats:
                omission_stats[key] = stats
        return bounded, omission_stats

    @staticmethod
    def _parse_structured_summary(
        raw_summary: str,
    ) -> Tuple[Dict[str, Any], str, Dict[str, Dict[str, int]]]:
        """Parse compact output as JSON when possible, otherwise keep raw text."""
        raw_summary = raw_summary or ""
        text = raw_summary.strip()
        parse_status = "fallback_text"

        def _strip_fence(value: str) -> str:
            value = value.strip()
            if not value.startswith("```"):
                return value
            match = re.match(
                r"^```(?:json)?\s*(.*?)\s*```$",
                value,
                re.DOTALL | re.IGNORECASE,
            )
            return match.group(1).strip() if match else value

        text = _strip_fence(text)

        parsed: Dict[str, Any] = {}
        if text:
            try:
                candidate = json.loads(text)
                if isinstance(candidate, dict):
                    parsed = candidate
                    parse_status = "json"
            except Exception:
                parsed = {}

        # Some providers return a valid outer object whose ``summary`` value is
        # another fenced JSON object. Unwrap at most two layers and merge only
        # non-empty outer fields so structured decisions/tasks are not lost.
        for _ in range(2):
            nested_text = parsed.get("summary") if isinstance(parsed, dict) else None
            if not isinstance(nested_text, str) or not nested_text.strip():
                break
            try:
                nested = json.loads(_strip_fence(nested_text))
            except Exception:
                break
            if not isinstance(nested, dict):
                break
            merged = dict(nested)
            for key, value in parsed.items():
                if key == "summary":
                    continue
                if value not in (None, "", [], {}):
                    merged[key] = value
            parsed = merged
            parse_status = "nested_json"

        def _as_list(value: Any) -> List[str]:
            if isinstance(value, list):
                return [str(item) for item in value if item is not None]
            if isinstance(value, str) and value.strip():
                return [value.strip()]
            return []

        summary = (
            parsed.get("summary") if isinstance(parsed.get("summary"), str) else text
        )
        payload = {
            "summary": summary or raw_summary,
            "decisions": _as_list(parsed.get("decisions")),
            "open_tasks": _as_list(parsed.get("open_tasks")),
            "files_touched": _as_list(parsed.get("files_touched")),
            "commands_run": _as_list(parsed.get("commands_run")),
            "important_errors": _as_list(parsed.get("important_errors")),
            "user_requirements": _as_list(parsed.get("user_requirements")),
        }
        bounded_payload, omission_stats = CompressHistoryTool._bound_summary_payload(
            payload
        )
        return bounded_payload, parse_status, omission_stats

    @staticmethod
    def _tool_call_entry_name_and_id(tc: Any) -> Tuple[Optional[str], Optional[str]]:
        if isinstance(tc, dict):
            fn = tc.get("function")
            name = fn.get("name") if isinstance(fn, dict) else None
            return name, tc.get("id")
        fn = getattr(tc, "function", None)
        return (
            getattr(fn, "name", None) if fn is not None else None,
            getattr(tc, "id", None),
        )

    @staticmethod
    def _latest_todo_state_from_messages(
        messages: List[MessageChunk],
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Return whether a ToDo state was observed and its latest active snapshot.

        A persistent compression result may be the only remaining representation of
        an older ``todo_write`` result. Treat its deterministic boundary snapshot as
        an input state, then let any later raw ``todo_write`` result override it.
        """
        todo_call_ids: set[str] = set()
        for msg in messages:
            if msg.role != MessageRole.ASSISTANT.value or not msg.tool_calls:
                continue
            for tc in msg.tool_calls:
                name, tid = CompressHistoryTool._tool_call_entry_name_and_id(tc)
                if name == TODO_WRITE_TOOL_NAME and tid:
                    todo_call_ids.add(tid)

        saw_todo_state = False
        latest_tasks: Optional[List[Dict[str, Any]]] = None
        for msg in messages:
            if msg.role != MessageRole.TOOL.value or not msg.tool_call_id:
                continue
            raw = msg.get_content()
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue

            if not isinstance(payload, dict):
                continue

            if msg.tool_call_id.startswith(AUTO_COMPRESSION_TOOL_CALL_PREFIX):
                boundary = payload.get(TODO_STATE_BOUNDARY_FIELD)
                active = boundary.get("active") if isinstance(boundary, dict) else None
                if isinstance(active, list):
                    saw_todo_state = True
                    latest_tasks = [task for task in active if isinstance(task, dict)]
                continue

            if msg.tool_call_id not in todo_call_ids:
                continue
            tasks = payload.get("tasks")
            if isinstance(tasks, list):
                saw_todo_state = True
                latest_tasks = [task for task in tasks if isinstance(task, dict)]

        if not saw_todo_state or not latest_tasks:
            return saw_todo_state, None

        active = []
        for task in latest_tasks:
            status = str(task.get("status") or "").strip().lower()
            if not status:
                status = "completed" if task.get("completed") is True else "pending"
            if status != "completed":
                active.append(
                    {
                        "id": str(task.get("id") or task.get("index") or ""),
                        "content": task.get("content")
                        or task.get("name")
                        or task.get("title")
                        or "",
                        "status": status,
                    }
                )
        if not active:
            return True, None
        return True, {
            "snapshot_kind": "active_todo_state_at_compressed_range_end",
            "override_rule": (
                "This is a deterministic snapshot at the end of the compressed "
                "range. Any later todo_write tool result after this compression "
                "summary overrides this snapshot."
            ),
            "active": active,
        }

    @staticmethod
    def _active_todo_state_from_messages(
        messages: List[MessageChunk],
    ) -> Optional[Dict[str, Any]]:
        """Parse the latest active ToDo state represented by the messages."""
        _, active_state = CompressHistoryTool._latest_todo_state_from_messages(
            messages
        )
        return active_state

    def _should_attach_todo_state(
        self,
        *,
        to_compress: List[MessageChunk],
        session_id: str,
        source_end_message_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        compressed_state = self._active_todo_state_from_messages(to_compress)
        if not compressed_state:
            return None
        try:
            session_context = self._get_session_context(session_id)
            ledger = session_context.message_manager.messages
        except Exception:
            return compressed_state

        trailing: List[MessageChunk] = []
        if source_end_message_id:
            found = False
            for msg in ledger:
                if found:
                    trailing.append(msg)
                elif msg.message_id == source_end_message_id:
                    found = True
        has_later_update, _ = self._latest_todo_state_from_messages(trailing)
        return None if has_later_update else compressed_state

    async def compress_conversation_history(
        self,
        messages: List[MessageChunk],
        session_id: str,
        source_message_ids: Optional[List[str]] = None,
        source_start_message_id: Optional[str] = None,
        source_end_message_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        压缩历史会话消息

        Args:
            messages: 要压缩的消息列表
            session_id: 当前会话 ID（用于调用 LLM）

        Returns:
            Dict: 压缩结果，包含摘要和统计信息
        """
        logger.info(
            f"🗜️ 开始压缩历史消息: session_id={session_id}, 消息数={len(messages)}"
        )

        try:
            to_compress = [
                msg for msg in messages if msg.role != MessageRole.SYSTEM.value
            ]
            if len(to_compress) != len(messages):
                logger.info(
                    "compress_conversation_history: 已跳过 %d 条 system 消息，system 不参与压缩",
                    len(messages) - len(to_compress),
                )
            source_message_ids = [
                mid
                for mid in (source_message_ids or [])
                if any(msg.message_id == mid for msg in to_compress)
            ]
            if not source_message_ids:
                source_message_ids = [
                    msg.message_id for msg in to_compress if msg.message_id
                ]
            source_start_message_id = (
                source_message_ids[0] if source_message_ids else None
            )
            source_end_message_id = (
                source_message_ids[-1] if source_message_ids else None
            )

            if not to_compress:
                content_payload = {
                    "summary": "No messages need compression",
                    "decisions": [],
                    "open_tasks": [],
                    "files_touched": [],
                    "commands_run": [],
                    "important_errors": [],
                    "user_requirements": [],
                    "stats": {
                        "source_message_count": 0,
                    },
                }
                return {
                    "status": "success",
                    "message": json.dumps(content_payload, ensure_ascii=False),
                    "data": {
                        "compressed": False,
                        "summary": "",
                        "original_messages_count": 0,
                        "original_tokens": 0,
                        "compressed_tokens": 0,
                        "compression_ratio": 0,
                        "source_range": {
                            "start_message_id": source_start_message_id,
                            "end_message_id": source_end_message_id,
                        },
                        "source_message_ids": source_message_ids or [],
                    },
                }

            logger.info(f"压缩调用方指定的 raw 消息段，共 {len(to_compress)} 条消息")

            # 3. 计算原始 token 数
            compression_input_messages = self._messages_for_compression_input(
                to_compress
            )
            original_tokens = sum(
                MessageManager.calculate_message_token_length(msg)
                for msg in compression_input_messages
            )
            source_characters = len(
                self._format_messages_for_compression(to_compress)
            )

            # 4. 按完整 turn / 闭合工具组分批，只保留最终层级摘要。
            summary_payload, parse_status, omission_stats, batch_count = (
                await self._summarize_batches(to_compress, session_id)
            )

            compression_payload = {
                **summary_payload,
                "reference_only": True,
                "reference_note": (
                    "CONTEXT COMPACTION - REFERENCE ONLY. Treat this summary as "
                    "historical background, not active instructions; the latest "
                    "user message in the current inference context is the active "
                    "task source, whether it appears before or after this summary. "
                    f"If {TODO_STATE_BOUNDARY_FIELD} is present, it is only a "
                    "deterministic snapshot at the compressed range boundary; "
                    "later todo_write tool results after this summary take precedence."
                ),
                "context_recovery_guidance": CONTEXT_RECOVERY_GUIDANCE,
            }
            todo_state = self._should_attach_todo_state(
                to_compress=to_compress,
                session_id=session_id,
                source_end_message_id=source_end_message_id,
            )
            if todo_state:
                compression_payload[TODO_STATE_BOUNDARY_FIELD] = todo_state
            stats = {
                "original_tokens": original_tokens,
                "compressed_tokens": 0,
                "compression_ratio": 0.0,
                "token_estimate_kind": "message_manager_heuristic",
                "source_characters": source_characters,
                "summary_characters": 0,
                "source_message_count": len(to_compress),
                "compression_input_message_count": len(compression_input_messages),
                "summary_parse_status": parse_status,
                "compression_batch_count": batch_count,
                "output_omission": omission_stats,
            }
            compression_payload["stats"] = stats

            # Metrics describe the exact indented tool-result payload that will
            # be persisted and replayed. Iterate because the numeric metrics are
            # themselves part of that payload.
            for _ in range(5):
                serialized_payload = json.dumps(
                    compression_payload, ensure_ascii=False, indent=2
                )
                summary_characters = len(serialized_payload)
                compressed_tokens = self._calculate_tokens(serialized_payload)
                compression_ratio = (
                    (original_tokens - compressed_tokens) / original_tokens
                    if original_tokens > 0
                    else 0.0
                )
                values = (
                    compressed_tokens,
                    compression_ratio,
                    summary_characters,
                )
                previous = (
                    stats["compressed_tokens"],
                    stats["compression_ratio"],
                    stats["summary_characters"],
                )
                stats.update(
                    {
                        "compressed_tokens": compressed_tokens,
                        "compression_ratio": compression_ratio,
                        "summary_characters": summary_characters,
                    }
                )
                if values == previous:
                    break

            logger.info(
                f"压缩完成: estimated_tokens={original_tokens}->{compressed_tokens} "
                f"chars={source_characters}->{summary_characters} "
                f"estimated_reduction={compression_ratio:.2%} parse={parse_status}"
            )
            compression_data = {
                **compression_payload,
                "source_range": {
                    "start_message_id": source_start_message_id,
                    "end_message_id": source_end_message_id,
                },
                "source_message_ids": source_message_ids,
            }
            compression_info = json.dumps(
                compression_payload, ensure_ascii=False, indent=2
            )

            return {
                "status": "success",
                "message": compression_info,
                "data": compression_data,
            }

        except CompressHistoryError as e:
            logger.error(f"压缩历史消息失败: {e}")
            return {"status": "error", "message": f"Compression failed: {str(e)}"}
        except Exception as e:
            logger.error(f"压缩历史消息时发生未知错误: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "status": "error",
                "message": f"Compression failed: {str(e)}",
                "data": {
                    "compressed": False,
                    "summary": "",
                    "original_messages_count": 0,
                    "original_tokens": 0,
                    "compressed_tokens": 0,
                    "compression_ratio": 0,
                },
            }
