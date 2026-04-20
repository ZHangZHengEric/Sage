#!/usr/bin/env python3
"""
压缩历史会话消息工具
将历史对话压缩为结构化摘要，减少上下文长度
"""

from typing import Dict, Any, List

from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
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
            "heavy": {"tool_truncate": 200, "assistant_summary": 200}
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

    async def _call_llm_for_compression(self, messages_text: str, session_id: str) -> str:
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
        model_config.pop('max_model_len', None)
        model_config.pop('api_key', None)
        model_config.pop('maxTokens', None)
        model_config.pop('max_tokens', None)  # 移除可能存在的 max_tokens
        model_config.pop('temperature', None)  # 移除可能存在的 temperature
        model_config.pop('base_url', None)
        model_name = model_config.pop('model', 'gpt-3.5-turbo')

        # 构建压缩提示词 - 优化为更适合作为记忆供后续执行使用
        prompt = f"""请将以下对话历史压缩为执行记忆摘要。这个摘要将被后续 AI 助手读取，用于理解上下文并继续执行任务。

【对话历史】
{messages_text}

【压缩要求】
生成一个结构化的执行记忆摘要，必须包含以下信息，以便后续助手能够无缝继续工作：

📋 **任务背景与目标**
  - 用户最初的需求是什么
  - 任务的总体目标

🔑 **关键上下文信息**
  - 重要的业务规则、约束条件
  - 已确认的需求细节、参数配置
  - 相关的文件路径、代码位置、API 接口

✅ **已完成的工作**
  - 已执行的步骤和产生的输出
  - 已做出的决策及其原因
  - 已验证通过的结果

⚠️ **待解决问题**
  - 当前阻塞或需要关注的事项
  - 待确认的问题或选项
  - 下一步建议的行动

💾 **重要数据状态**
  - 关键变量的当前值
  - 已创建的资源的 ID/名称
  - 中间结果或临时文件位置

📁 **生成文件清单**
  - 列出对话历史中提到的文件（优先使用绝对路径，没有则使用相对路径或文件名）
  - 每个文件的用途说明
  - 文件之间的依赖关系（如有）

【输出要求】
- 使用简洁、明确的语言，避免模糊描述
- 保留具体的技术细节（路径、名称、数值等）
- 文件路径原则：优先使用绝对路径，没有绝对路径时使用相对路径或文件名，禁止编造路径（如 /workspace/ 等）
- 按优先级排序，重要信息在前
- 总长度控制在 8000 字以内（非严格限制）"""

        try:
            # 构建 extra_body，禁用深度思考
            extra_body = {
                "top_k": 20,
                "_step_name": "compress_history"
            }

            # 判断是否为 OpenAI 推理模型
            is_openai_reasoning_model = (
                model_name.startswith("o3-") or
                model_name.startswith("o1-") or
                "gpt-5.2" in model_name.lower() or
                "gpt-5.1" in model_name.lower()
            )

            if is_openai_reasoning_model:
                # OpenAI 推理模型使用 reasoning_effort=low 最小化推理
                extra_body["reasoning_effort"] = "low"
            else:
                # 其他模型使用 enable_thinking=False 禁用思考
                extra_body["chat_template_kwargs"] = {"enable_thinking": False}
                extra_body["enable_thinking"] = False
                extra_body["thinking"] = {'type': "disabled"}

            # 流式请求 LLM
            stream = await model.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                stream=True,
                stream_options={"include_usage": True},
                max_tokens=2000,
                temperature=0.3,
                extra_body=extra_body,
                **model_config
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

    def _determine_compression_range(self, messages: List[MessageChunk]) -> Dict[str, Any]:
        """
        确定压缩范围

        策略（都不包含 System 消息）：
        1. 只有一个 User：压缩该 User 之后的所有非 User 消息
        2. 多个 User：压缩最后一个 User 之前的所有消息
        """
        # 找到 System 消息的结束位置
        system_end = 0
        for i, msg in enumerate(messages):
            if msg.role == MessageRole.SYSTEM.value:
                system_end = i + 1

        # 找到所有 User 消息的索引（不包括 System 部分）
        user_indices = [
            i for i, msg in enumerate(messages)
            if i >= system_end and
            msg.is_user_input_message()
        ]

        if len(user_indices) == 0:
            # 没有 User 消息，不压缩
            return {
                "system_end": system_end,
                "to_compress_start": system_end,
                "to_compress_end": system_end,
                "total_messages": len(messages),
                "reserved_rounds": 0
            }

        if len(user_indices) == 1:
            # 只有一个 User：压缩该 User 之后的所有非 User 消息
            first_user_idx = user_indices[0]
            return {
                "system_end": system_end,
                "to_compress_start": first_user_idx + 1,  # 从 User 之后开始
                "to_compress_end": len(messages),  # 到结尾
                "total_messages": len(messages),
                "reserved_rounds": 1
            }
        else:
            # 多个 User：压缩最后一个 User 之前的所有消息
            last_user_idx = user_indices[-1]
            return {
                "system_end": system_end,
                "to_compress_start": system_end,  # 从 System 之后开始
                "to_compress_end": last_user_idx,  # 到最后一个 User 之前
                "total_messages": len(messages),
                "reserved_rounds": len(user_indices)
            }

    async def compress_conversation_history(
        self,
        messages: List[MessageChunk],
        session_id: str
    ) -> Dict[str, Any]:
        """
        压缩历史会话消息

        Args:
            messages: 要压缩的消息列表
            session_id: 当前会话 ID（用于调用 LLM）

        Returns:
            Dict: 压缩结果，包含摘要和统计信息
        """
        logger.info(f"🗜️ 开始压缩历史消息: session_id={session_id}, 消息数={len(messages)}")

        try:
            all_messages = messages

            if not all_messages:
                return {
                    "status": "success",
                    "message": "没有消息需要压缩",
                    "data": {
                        "compressed": False,
                        "summary": "",
                        "original_messages_count": 0,
                        "original_tokens": 0,
                        "compressed_tokens": 0,
                        "compression_ratio": 0
                    }
                }

            # 2. 确定压缩范围
            range_info = self._determine_compression_range(all_messages)
            to_compress = all_messages[range_info["to_compress_start"]:range_info["to_compress_end"]]

            if not to_compress:
                return {
                    "status": "success",
                    "message": "消息数量较少，无需压缩",
                    "data": {
                        "compressed": False,
                        "summary": "",
                        "original_messages_count": len(all_messages),
                        "original_tokens": 0,
                        "compressed_tokens": 0,
                        "compression_ratio": 0
                    }
                }

            logger.info(f"压缩范围: 消息 {range_info['to_compress_start']} 到 {range_info['to_compress_end']}, "
                       f"共 {len(to_compress)} 条消息")

            # 3. 计算原始 token 数
            original_tokens = sum(
                self._calculate_tokens(msg.get_content() or "")
                for msg in to_compress
            )

            # 4. 格式化消息并调用 LLM 压缩
            messages_text = self._format_messages_for_compression(to_compress)
            summary = await self._call_llm_for_compression(messages_text, session_id)

            # 5. 计算压缩后的 token 数
            compressed_tokens = self._calculate_tokens(summary)
            compression_ratio = (original_tokens - compressed_tokens) / original_tokens if original_tokens > 0 else 0

            logger.info(f"压缩完成: {original_tokens} tokens -> {compressed_tokens} tokens, "
                       f"压缩率: {compression_ratio:.2%}")

            # 6. 构建压缩结果 - 简化为 message 格式
            compression_info = (
                f"✅ 成功压缩 {len(to_compress)} 条历史消息\n"
                f"📊 压缩统计: {original_tokens} tokens → {compressed_tokens} tokens "
                f"(压缩率: {compression_ratio:.1%})\n\n"
                f"📝 历史摘要:\n{summary}"
            )

            return {
                "status": "success",
                "message": compression_info
            }

        except CompressHistoryError as e:
            logger.error(f"压缩历史消息失败: {e}")
            return {
                "status": "error",
                "message": f"❌ 压缩失败: {str(e)}"
            }
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
                    "compression_ratio": 0
                }
            }
