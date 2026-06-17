#!/usr/bin/env python3
"""
压缩历史会话消息工具
将历史对话压缩为结构化摘要，减少上下文长度
"""

from typing import Dict, Any, List, Optional, Tuple
import json
import re

from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.context.messages.message_manager import MessageManager


class CompressHistoryError(Exception):
    """压缩历史消息异常"""

    pass


class CompressHistoryTool:
    """
    压缩历史会话消息工具

    功能：
    1. 分析当前会话的消息历史
    2. 将旧消息压缩为结构化摘要
    3. 保留最近3轮对话的完整内容
    4. 返回压缩结果供后续使用
    """

    def __init__(self):
        # 压缩级别配置
        self.compression_levels = {
            "light": {"tool_truncate": 1000, "assistant_summary": 800},
            "medium": {"tool_truncate": 500, "assistant_summary": 400},
            "heavy": {"tool_truncate": 200, "assistant_summary": 200},
        }

    def _get_session_context(self, session_id: str):
        """通过 session_id 获取会话上下文"""
        from sagents.utils.agent_session_helper import get_live_session

        session = get_live_session(session_id, log_prefix="CompressHistoryTool")

        if not session or not session.session_context:
            raise CompressHistoryError(f"无效的 session_id={session_id}")

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
        """将消息格式化为文本用于压缩"""
        # 使用 MessageManager.convert_messages_to_str 处理消息格式化
        # 它会正确处理 tool_calls 等情况
        return MessageManager.convert_messages_to_str(messages)

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
            raise CompressHistoryError(f"无法获取会话: {session_id}")

        model = session.model
        model_config = session.model_config.copy()

        if not model:
            raise CompressHistoryError("会话模型未初始化")

        # 移除非标准参数和与显式参数冲突的参数
        model_config.pop("max_model_len", None)
        model_config.pop("api_key", None)
        model_config.pop("maxTokens", None)
        model_config.pop("max_tokens", None)  # 移除可能存在的 max_tokens
        model_config.pop("temperature", None)  # 移除可能存在的 temperature
        model_config.pop("base_url", None)
        model_name = model_config.pop("model", "gpt-3.5-turbo")

        # 构建压缩提示词：优先要求结构化 JSON，便于后续更高层压缩继续合并。
        prompt = f"""请将以下对话历史压缩为执行记忆摘要。这个摘要将被后续 AI 助手读取，用于理解上下文并继续执行任务。

【对话历史】
{messages_text}

如果对话历史中包含 compress_conversation_history 的工具调用/结果，它代表更早历史的摘要节点。请把它当作事实来源参与本次更高层总结，不需要展开或臆测原始消息。

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
- 按优先级排序，重要信息在前。
- 总长度控制在 8000 字以内（非严格限制）。"""

        try:
            # 构建 extra_body，禁用深度思考
            extra_body = {"top_k": 20, "_step_name": "compress_history"}

            # 判断是否为 OpenAI 推理模型
            is_openai_reasoning_model = (
                model_name.startswith("o3-")
                or model_name.startswith("o1-")
                or "gpt-5.2" in model_name.lower()
                or "gpt-5.1" in model_name.lower()
            )

            if is_openai_reasoning_model:
                # OpenAI 推理模型使用 reasoning_effort=low 最小化推理
                extra_body["reasoning_effort"] = "low"
            else:
                # 其他模型使用 enable_thinking=False 禁用思考
                extra_body["chat_template_kwargs"] = {"enable_thinking": False}
                extra_body["enable_thinking"] = False
                extra_body["thinking"] = {"type": "disabled"}

            # 流式请求 LLM
            stream = await model.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                stream_options={"include_usage": True},
                max_tokens=2000,
                temperature=0.3,
                extra_body=extra_body,
                **model_config,
            )

            # 收集流式响应内容
            content_parts = []
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta_content = chunk.choices[0].delta.content
                    if delta_content:
                        content_parts.append(delta_content)

            return "".join(content_parts)

        except Exception as e:
            logger.error(f"调用 LLM 压缩失败: {e}")
            raise CompressHistoryError(f"LLM 压缩失败: {e}")

    @staticmethod
    def _parse_structured_summary(raw_summary: str) -> Tuple[Dict[str, Any], str]:
        """Parse compact output as JSON when possible, otherwise keep raw text."""
        raw_summary = raw_summary or ""
        text = raw_summary.strip()
        parse_status = "fallback_text"
        if text.startswith("```"):
            match = re.match(
                r"^```(?:json)?\s*(.*?)\s*```$",
                text,
                re.DOTALL | re.IGNORECASE,
            )
            if match:
                text = match.group(1).strip()

        parsed: Dict[str, Any] = {}
        if text:
            try:
                candidate = json.loads(text)
                if isinstance(candidate, dict):
                    parsed = candidate
                    parse_status = "json"
            except Exception:
                parsed = {}

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
        return payload, parse_status

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
            to_compress = messages

            if not to_compress:
                return {
                    "status": "success",
                    "message": json.dumps(
                        {
                            "summary": "没有消息需要压缩",
                            "decisions": [],
                            "open_tasks": [],
                            "files_touched": [],
                            "commands_run": [],
                            "important_errors": [],
                            "user_requirements": [],
                            "source_range": {
                                "start_message_id": source_start_message_id,
                                "end_message_id": source_end_message_id,
                            },
                            "source_message_ids": source_message_ids or [],
                            "original_content_paths": [],
                        },
                        ensure_ascii=False,
                    ),
                    "data": {
                        "compressed": False,
                        "summary": "",
                        "original_messages_count": 0,
                        "original_tokens": 0,
                        "compressed_tokens": 0,
                        "compression_ratio": 0,
                    },
                }

            logger.info(f"压缩调用方指定的 raw 消息段，共 {len(to_compress)} 条消息")

            # 3. 计算原始 token 数
            original_tokens = sum(
                self._calculate_tokens(msg.get_content() or "") for msg in to_compress
            )

            # 4. 格式化消息并调用 LLM 压缩
            messages_text = self._format_messages_for_compression(to_compress)
            raw_summary = await self._call_llm_for_compression(messages_text, session_id)
            summary_payload, parse_status = self._parse_structured_summary(raw_summary)

            # 5. 计算压缩后的 token 数
            compressed_tokens = self._calculate_tokens(
                json.dumps(summary_payload, ensure_ascii=False)
            )
            compression_ratio = (
                (original_tokens - compressed_tokens) / original_tokens
                if original_tokens > 0
                else 0
            )

            logger.info(
                f"压缩完成: {original_tokens} tokens -> {compressed_tokens} tokens, "
                f"压缩率: {compression_ratio:.2%}"
            )

            source_message_ids = source_message_ids or [
                msg.message_id for msg in to_compress if msg.message_id
            ]
            source_start_message_id = (
                source_start_message_id
                or (source_message_ids[0] if source_message_ids else None)
            )
            source_end_message_id = (
                source_end_message_id
                or (source_message_ids[-1] if source_message_ids else None)
            )
            compression_payload = {
                **summary_payload,
                "source_range": {
                    "start_message_id": source_start_message_id,
                    "end_message_id": source_end_message_id,
                },
                "source_message_ids": source_message_ids,
                "original_content_paths": [],
                "stats": {
                    "original_tokens": original_tokens,
                    "compressed_tokens": compressed_tokens,
                    "compression_ratio": compression_ratio,
                    "source_message_count": len(to_compress),
                    "summary_parse_status": parse_status,
                },
            }
            compression_info = json.dumps(
                compression_payload, ensure_ascii=False, indent=2
            )

            return {
                "status": "success",
                "message": compression_info,
                "data": compression_payload,
            }

        except CompressHistoryError as e:
            logger.error(f"压缩历史消息失败: {e}")
            return {"status": "error", "message": f"❌ 压缩失败: {str(e)}"}
        except Exception as e:
            logger.error(f"压缩历史消息时发生未知错误: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "status": "error",
                "message": f"压缩失败: {str(e)}",
                "data": {
                    "compressed": False,
                    "summary": "",
                    "original_messages_count": 0,
                    "original_tokens": 0,
                    "compressed_tokens": 0,
                    "compression_ratio": 0,
                },
            }
