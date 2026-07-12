from typing import Any, Dict, List, Optional, AsyncGenerator, Union, cast
import json
import uuid
import os

from .agent_base import AgentBase
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager

# 通用可自定义agent


class CommonAgent(AgentBase):
    def __init__(
        self,
        model: Any,
        model_config: Dict[str, Any],
        system_prefix: str = "",
        tools_name: Optional[List[str]] = None,
        max_model_len: int = 64000,
    ):
        super().__init__(model, model_config, system_prefix)
        self.tools_name = tools_name if tools_name is not None else []
        self.max_history_context_length = max_model_len

    async def run_stream(
        self, session_context: SessionContext
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        运行智能体，返回消息流

        Args:
            session_context: 会话上下文

        Returns:
            消息流
        """
        if not session_context.tool_manager:
            raise ValueError("ToolManager is not initialized in SessionContext")
        session_id = session_context.session_id
        if self._should_abort_due_to_session(session_context):
            return

        # Drain "运行期注入的引导用户消息"：持久注入会写入 message_manager；
        # transient 注入只追加到本轮 LLM 请求，不 yield 给 SSE。
        injected = self._consume_user_injections(session_context)
        if injected:
            visible_injected = self._visible_user_injections(injected)
            if visible_injected:
                yield visible_injected

        message_manager = session_context.message_manager
        all_messages = message_manager.extract_all_context_messages(
            recent_turns=10,
            max_length=self.max_history_context_length,  # pyright: ignore[reportCallIssue]
            last_turn_user_only=False,
        )
        transient_injected = self._transient_user_injections(injected)
        if transient_injected:
            all_messages = list(all_messages) + list(transient_injected)

        # all_messages  = message_manager.messages
        tool_manager = session_context.tool_manager

        tools_json = tool_manager.get_openai_tools(
            lang=session_context.get_language(), fallback_chain=["en"]
        )
        tools_json = [
            tools_json[tool_name]  # pyright: ignore[reportArgumentType,reportCallIssue]
            for tool_name in self.tools_name
            if tool_name in tools_json
        ]

        llm_request_message = await self.prepare_llm_request_messages(
            session_id=session_id,
            history_messages=all_messages,
            language=session_context.get_language(),
        )
        async for msg in self._call_llm_and_process_response(
            messages_input=llm_request_message,
            tools_json=tools_json,
            tool_manager=tool_manager,  # pyright: ignore[reportArgumentType]
            session_id=session_id,
        ):
            yield msg

    async def _call_llm_and_process_response(
        self,
        messages_input: List[MessageChunk],
        tools_json: List[Dict[str, Any]],
        tool_manager: Optional[ToolManager],
        session_id: str,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        logger.info(f"CommonAgent: 准备了 {len(messages_input)} 条消息用于LLM")

        # 准备模型配置覆盖，包含工具信息
        model_config_override = {}
        if len(tools_json) > 0:
            model_config_override["tools"] = tools_json

        response = self._call_llm_streaming(
            messages=cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input),
            session_id=session_id,
            step_name="task_execution",
            model_config_override=model_config_override,
        )

        tool_calls = {}
        reasoning_content_response_message_id = str(uuid.uuid4())
        content_response_message_id = str(uuid.uuid4())
        last_tool_call_id = None
        tool_calls_messages_id = str(uuid.uuid4())

        # 处理流式响应块
        async for chunk in response:
            # print(chunk)
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.tool_calls:
                self._handle_tool_calls_chunk(chunk, tool_calls, last_tool_call_id)  # pyright: ignore[reportArgumentType]
                # 更新last_tool_call_id
                for tool_call in chunk.choices[0].delta.tool_calls:
                    if tool_call.id is not None and len(tool_call.id) > 0:
                        last_tool_call_id = tool_call.id
                emit_on_complete = (
                    os.environ.get("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false").lower()
                    == "true"
                )
                if not emit_on_complete:
                    yield [
                        MessageChunk(
                            role=MessageRole.ASSISTANT.value,
                            tool_calls=chunk.choices[0].delta.tool_calls,
                            message_id=tool_calls_messages_id,
                            message_type=MessageType.TOOL_CALL.value,
                        )
                    ]

            elif chunk.choices[0].delta.content:
                if len(tool_calls) > 0:
                    logger.info(
                        f"CommonAgent: LLM响应包含 {len(tool_calls)} 个工具调用和内容，停止收集文本内容"
                    )
                    break

                if len(chunk.choices[0].delta.content) > 0:
                    output_messages = [
                        MessageChunk(
                            role=MessageRole.ASSISTANT.value,
                            content=chunk.choices[0].delta.content,
                            message_id=content_response_message_id,
                            message_type=MessageType.DO_SUBTASK_RESULT.value,
                        )
                    ]
                    yield output_messages
            else:
                # 先判断chunk.choices[0].delta 是否有reasoning_content 这个变量，并且不是none
                if (
                    hasattr(chunk.choices[0].delta, "reasoning_content")
                    and chunk.choices[0].delta.reasoning_content is not None
                ):
                    output_messages = [
                        MessageChunk(
                            role=MessageRole.ASSISTANT.value,
                            content=chunk.choices[0].delta.reasoning_content,
                            message_id=reasoning_content_response_message_id,
                            message_type=MessageType.TASK_ANALYSIS.value,
                        )
                    ]
                    yield output_messages
        # 处理工具调用
        if len(tool_calls) > 0:
            allowed_tool_names = {
                (tool.get("function") or {}).get("name") or ""
                for tool in tools_json
            }
            invalid_tool_names = {
                (tool_call.get("function") or {}).get("name") or ""
                for tool_call in tool_calls.values()
                if ((tool_call.get("function") or {}).get("name") or "")
                not in allowed_tool_names
            }
            if invalid_tool_names:
                logger.warning(
                    "CommonAgent: 模型返回未提供的工具 "
                    f"{sorted(invalid_tool_names)}，拒绝执行"
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
                yield [
                    *streamed_rejections,
                    self._create_unavailable_tool_runtime_message(
                        sorted(invalid_tool_names)
                    )
                ]
                return

            emit_on_complete = (
                os.environ.get("SAGE_EMIT_TOOL_CALL_ON_COMPLETE", "false").lower()
                == "true"
            )
            async for msg in self._handle_tool_calls(
                tool_calls=tool_calls,
                tool_manager=tool_manager,
                messages_input=messages_input,  # pyright: ignore[reportArgumentType]
                session_id=session_id,
                emit_tool_call_message=emit_on_complete,
            ):
                yield msg
        else:
            # 发送换行消息（也包含usage信息）
            output_messages = [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="",
                    message_id=content_response_message_id,
                    message_type=MessageType.DO_SUBTASK_RESULT.value,
                )
            ]
            yield output_messages

    async def _handle_tool_calls(
        self,
        tool_calls: Dict[str, Any],
        tool_manager: Optional[Any],
        messages_input: List[Dict[str, Any]],
        session_id: str,
        emit_tool_call_message: bool = True,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        """
        处理工具调用

        Args:
            tool_calls: 工具调用字典
            tool_manager: 工具管理器
            messages_input: 输入消息列表
            session_id: 会话ID

        Yields:
            tuple[List[MessageChunk], bool]: (消息块列表, 是否完成任务)
        """
        async for messages, is_complete in super()._handle_tool_calls(
            tool_calls=tool_calls,
            tool_manager=tool_manager,
            messages_input=messages_input,
            session_id=session_id,
            handle_complete_task=True,
            emit_tool_call_message=emit_tool_call_message,
            execute_concurrently=False,
        ):
            yield messages
            if is_complete:
                return

    def process_tool_response(
        self, tool_response: str, tool_call_id: str
    ) -> List[Dict[str, Any]]:
        """
        处理工具执行响应

        Args:
            tool_response: 工具执行响应
            tool_call_id: 工具调用ID

        Returns:
            List[Dict[str, Any]]: 处理后的结果消息
        """
        logger.debug(f"CommonAgent: 处理工具响应，工具调用ID: {tool_call_id}")

        try:
            tool_response_dict = json.loads(tool_response)

            if "content" in tool_response_dict:
                result = [
                    MessageChunk(
                        role=MessageRole.TOOL.value,
                        content=tool_response,
                        tool_call_id=tool_call_id,
                        message_id=str(uuid.uuid4()),
                        message_type=MessageType.TOOL_CALL_RESULT.value,
                    )
                ]
            elif "messages" in tool_response_dict:
                result = [
                    MessageChunk(
                        role=MessageRole.TOOL.value,
                        content=msg,
                        tool_call_id=tool_call_id,
                        message_id=str(uuid.uuid4()),
                        message_type=MessageType.TOOL_CALL_RESULT.value,
                    )
                    for msg in tool_response_dict["messages"]
                ]
            else:
                # 默认处理
                result = [
                    MessageChunk(
                        role=MessageRole.TOOL.value,
                        content=tool_response,
                        tool_call_id=tool_call_id,
                        message_id=str(uuid.uuid4()),
                        message_type=MessageType.TOOL_CALL_RESULT.value,
                    )
                ]

            logger.debug("CommonAgent: 工具响应处理成功")
            return result  # pyright: ignore[reportReturnType]

        except json.JSONDecodeError:
            logger.warning("CommonAgent: 处理工具响应时JSON解码错误，按普通文本处理")
            return [
                MessageChunk(  # pyright: ignore[reportReturnType]
                    role=MessageRole.TOOL.value,
                    content=tool_response,
                    tool_call_id=tool_call_id,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                )
            ]
