import traceback
from typing import Any, Dict, List, Optional, AsyncGenerator
import json
import uuid

from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext, get_session_context
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_schema import AgentToolSpec

# 通用可自定义agent


class CommonAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", tools_name: List[str] = [], max_model_len: int = 64000):
        super().__init__(model, model_config, system_prefix)
        self.tools_name = tools_name
        self.max_history_context_length = max_model_len

    async def run_stream(self, session_context: SessionContext, tool_manager: ToolManager = None, session_id: str = None) -> AsyncGenerator[List[MessageChunk], None]:
        """
        运行智能体，返回消息流

        Args:
            session_context: 会话上下文
            tool_manager: 工具管理器
            session_id: 会话ID

        Returns:
            消息流
        """
        message_manager = session_context.message_manager
        all_messages = message_manager.extract_all_context_messages(recent_turns=10, max_length=self.max_history_context_length, last_turn_user_only=False)
        # 根据 active_budget 压缩消息
        budget_info = message_manager.context_budget_manager.budget_info
        if budget_info:
            all_messages = MessageManager.compress_messages(all_messages, budget_info.get('active_budget', 8000))
        # all_messages  = message_manager.messages
        if tool_manager is None:
            tool_manager = session_context.tool_manager
        
        tools_json = tool_manager.get_openai_tools(lang=session_context.get_language(), fallback_chain=["en"])
        tools_json = [tools_json[tool_name] for tool_name in self.tools_name if tool_name in tools_json]

        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language())
        ]
        llm_request_message.extend(all_messages)
        async for msg in self._call_llm_and_process_response(
            messages_input=llm_request_message,
            tools_json=tools_json,
            tool_manager=tool_manager,
            session_id=session_id
        ):
            yield msg

    async def _call_llm_and_process_response(self,
                                       messages_input: List[MessageChunk],
                                       tools_json: List[Dict[str, Any]],
                                       tool_manager: Optional[ToolManager],
                                       session_id: str
                                       ) -> AsyncGenerator[List[MessageChunk], None]:

        clean_message_input = MessageManager.convert_messages_to_dict_for_request(messages_input)
        logger.info(f"CommonAgent: 准备了 {len(clean_message_input)} 条消息用于LLM")

        # 准备模型配置覆盖，包含工具信息
        model_config_override = {}
        if len(tools_json) > 0:
            model_config_override['tools'] = tools_json

        response = self._call_llm_streaming(
            messages=clean_message_input,
            session_id=session_id,
            step_name="task_execution",
            model_config_override=model_config_override
        )

        tool_calls = {}
        reasoning_content_response_message_id = str(uuid.uuid4())
        content_response_message_id = str(uuid.uuid4())
        last_tool_call_id = None

        # 处理流式响应块
        async for chunk in response:
            # print(chunk)
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.tool_calls:
                self._handle_tool_calls_chunk(chunk, tool_calls, last_tool_call_id)
                # 更新last_tool_call_id
                for tool_call in chunk.choices[0].delta.tool_calls:
                    if tool_call.id is not None and len(tool_call.id) > 0:
                        last_tool_call_id = tool_call.id
                # yield 一个空的消息块以避免生成器卡住
                output_messages = [MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="",
                    message_id=content_response_message_id,
                    message_type=MessageType.EMPTY.value
                )]
                yield output_messages

            elif chunk.choices[0].delta.content:
                if len(tool_calls) > 0:
                    logger.info(f"CommonAgent: LLM响应包含 {len(tool_calls)} 个工具调用和内容，停止收集文本内容")
                    break

                if len(chunk.choices[0].delta.content) > 0:
                    output_messages = [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=chunk.choices[0].delta.content,
                        message_id=content_response_message_id,
                        message_type=MessageType.DO_SUBTASK_RESULT.value
                    )]
                    yield output_messages
            else:
                # 先判断chunk.choices[0].delta 是否有reasoning_content 这个变量，并且不是none
                if hasattr(chunk.choices[0].delta, 'reasoning_content') and chunk.choices[0].delta.reasoning_content is not None:
                    output_messages = [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=chunk.choices[0].delta.reasoning_content,
                        message_id=reasoning_content_response_message_id,
                        message_type=MessageType.TASK_ANALYSIS.value
                    )]
                    yield output_messages
        # 处理工具调用
        if len(tool_calls) > 0:
            async for msg in self._handle_tool_calls(
                tool_calls=tool_calls,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id
            ):
                yield msg
        else:
            # 发送换行消息（也包含usage信息）
            output_messages = [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content='',
                message_id=content_response_message_id,
                message_type=MessageType.DO_SUBTASK_RESULT.value
            )]
            yield output_messages

    async def _handle_tool_calls(self,
                           tool_calls: Dict[str, Any],
                           tool_manager: Optional[Any],
                           messages_input: List[Dict[str, Any]],
                           session_id: str) -> AsyncGenerator[List[MessageChunk], None]:
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
        logger.info(f"CommonAgent: LLM响应包含 {len(tool_calls)} 个工具调用")
        logger.info(f"CommonAgent: 工具调用: {tool_calls}")

        for tool_call_id, tool_call in tool_calls.items():
            tool_name = tool_call['function']['name']
            logger.info(f"CommonAgent: 执行工具 {tool_name}")
            logger.info(f"CommonAgent: 参数 {tool_call['function']['arguments']}")

            # 检查是否为complete_task
            if tool_name == 'complete_task':
                logger.info("CommonAgent: complete_task，停止执行")
                yield [MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content='已经完成了满足用户的所有要求',
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.DO_SUBTASK_RESULT.value
                )]
                return

            # 发送工具调用消息
            output_messages = self._create_tool_call_message(tool_call)
            yield output_messages

            # 执行工具
            async for message_chunk_list in self._execute_tool(
                tool_call=tool_call,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id
            ):
                yield message_chunk_list

    def _create_tool_call_message(self, tool_call: Dict[str, Any]) -> List[MessageChunk]:
        """
        创建工具调用消息

        Args:
            tool_call: 工具调用信息

        Returns:
            List[Dict[str, Any]]: 工具调用消息列表
        """
        # 格式化工具参数显示
        if '```<｜tool▁call▁end｜>' in tool_call['function']['arguments']:
            logger.debug(f"CommonAgent: 原始错误参数: {tool_call['function']['arguments']}")
            # 去掉```<｜tool▁call▁end｜> 以及之后所有的字符
            tool_call['function']['arguments'] = tool_call['function']['arguments'].split('```<｜tool▁call▁end｜>')[0]

        function_params = tool_call['function']['arguments']
        try:
            function_params = json.loads(tool_call['function']['arguments'])
        except json.JSONDecodeError:
            try:
                function_params = eval(tool_call['function']['arguments'])
            except Exception:
                logger.error("CommonAgent: 第一次参数解析报错，再次进行参数解析失败")
                logger.error(f"CommonAgent: 原始参数: {tool_call['function']['arguments']}")

        formatted_params = ''
        if isinstance(function_params, str):
            try:
                function_params = json.loads(function_params)
            except json.JSONDecodeError:
                try:
                    function_params = eval(function_params)
                except Exception:
                    logger.error("CommonAgent: 解析完参数化依旧后是str，再次进行参数解析失败")
                    logger.error(f"CommonAgent: 原始参数: {tool_call['function']['arguments']}")
                    logger.error(f"CommonAgent: 工具参数格式错误: {function_params}")
                    logger.error(f"CommonAgent: 工具参数类型: {type(function_params)}")

        if isinstance(function_params, dict):
            tool_call['function']['arguments'] = json.dumps(function_params, ensure_ascii=False)
            for param, value in function_params.items():
                # 对于字符串的参数，在format时需要截断，避免过长，并且要用引号包裹,不要使用f-string的写法
                # if isinstance(value, str) and len(value) > 100:
                #     value = f'"{value[:30]}"'
                formatted_params += f"{param} = {value}, "
            formatted_params = formatted_params.rstrip(', ')
        else:

            logger.error(f"CommonAgent: 原始参数: {tool_call['function']['arguments']}")
            logger.error(f"CommonAgent: 工具参数格式错误: {function_params}")
            logger.error(f"CommonAgent: 工具参数类型: {type(function_params)}")
            formatted_params = str(function_params)

        tool_name = tool_call['function']['name']

        # 将content 整理成函数调用的形式
        # func_name(param1 = ,param2)
        return [MessageChunk(
            role=MessageRole.ASSISTANT.value,
            tool_calls=[{
                'id': tool_call['id'],
                'type': tool_call['type'],
                'function': {
                    'name': tool_call['function']['name'],
                    'arguments': tool_call['function']['arguments']
                }
            }],
            message_type=MessageType.TOOL_CALL.value,
            message_id=str(uuid.uuid4()),
            content=f"{tool_name}({formatted_params})"
        )]

    async def _execute_tool(self,
                      tool_call: Dict[str, Any],
                      tool_manager: Optional[Any],
                      messages_input: List[Dict[str, Any]],
                      session_id: str) -> AsyncGenerator[List[MessageChunk], None]:
        """
        执行工具

        Args:
            tool_call: 工具调用信息
            tool_manager: 工具管理器
            messages_input: 输入消息列表
            session_id: 会话ID

        Yields:
            tuple[List[MessageChunk], bool]: (消息块列表, 是否完成任务)
        """
        tool_name = tool_call['function']['name']

        try:
            # 解析并执行工具调用
            arguments = json.loads(tool_call['function']['arguments'])
            if not isinstance(arguments, dict):
                async for msg in self._handle_tool_error(tool_call['id'], tool_name, "工具参数格式错误"):
                    yield msg
                return
            logger.info(f"CommonAgent: 执行工具 {tool_name}")
            tool_response = await tool_manager.run_tool_async(
                tool_name,
                session_context=get_session_context(session_id),
                session_id=session_id,
                **arguments
            )

            # 检查是否为流式响应（AgentToolSpec）
            is_async_iter = hasattr(tool_response, '__aiter__')
            is_sync_iter = hasattr(tool_response, '__iter__')
            
            if (is_async_iter or is_sync_iter) and not isinstance(tool_response, (str, bytes)):
                # 检查是否为专业agent工具
                tool_spec = tool_manager.get_tool(tool_name) if tool_manager else None
                is_agent_tool = isinstance(tool_spec, AgentToolSpec)

                # 处理流式响应
                logger.debug(f"CommonAgent: 收到流式工具响应，工具类型: {'专业Agent' if is_agent_tool else '普通工具'}")
                try:
                    if is_async_iter:
                        async for chunk in tool_response:
                            if is_agent_tool:
                                # 专业agent工具：直接返回原始结果，不做任何处理
                                if isinstance(chunk, list):
                                    yield chunk
                                else:
                                    yield [chunk]
                            else:
                                # 普通工具：添加必要的元数据
                                if isinstance(chunk, list):
                                    # 转化成message chunk
                                    message_chunks = []
                                    for message in chunk:
                                        if isinstance(message, dict):
                                            message_chunks.append(MessageChunk(
                                                role=MessageRole.TOOL.value,
                                                content=message['content'],
                                                tool_call_id=tool_call['id'],
                                                message_id=str(uuid.uuid4()),
                                                message_type=MessageType.TOOL_CALL_RESULT.value,
                                            ))
                                    yield message_chunks
                                else:
                                    # 单个消息
                                    if isinstance(chunk, dict):
                                        message_chunk_ = MessageChunk(
                                            role=MessageRole.TOOL.value,
                                            content=chunk['content'],
                                            tool_call_id=tool_call['id'],
                                            message_id=str(uuid.uuid4()),
                                            message_type=MessageType.TOOL_CALL_RESULT.value,
                                        )
                                        yield [message_chunk_]
                    else:
                        for chunk in tool_response:
                            if is_agent_tool:
                                # 专业agent工具：直接返回原始结果，不做任何处理
                                if isinstance(chunk, list):
                                    yield chunk
                                else:
                                    yield [chunk]
                            else:
                                # 普通工具：添加必要的元数据
                                if isinstance(chunk, list):
                                    # 转化成message chunk
                                    message_chunks = []
                                    for message in chunk:
                                        if isinstance(message, dict):
                                            message_chunks.append(MessageChunk(
                                                role=MessageRole.TOOL.value,
                                                content=message['content'],
                                                tool_call_id=tool_call['id'],
                                                message_id=str(uuid.uuid4()),
                                                message_type=MessageType.TOOL_CALL_RESULT.value,
                                            # show_content=message['content']
                                        ))
                                    yield message_chunks
                                else:
                                    # 单个消息
                                    if isinstance(chunk, dict):
                                        message_chunk_ = MessageChunk(
                                            role=MessageRole.TOOL.value,
                                            content=chunk['content'],
                                            tool_call_id=tool_call['id'],
                                            message_id=str(uuid.uuid4()),
                                            message_type=MessageType.TOOL_CALL_RESULT.value,
                                        )
                                        yield [message_chunk_]
                except Exception as e:
                    logger.error(f"CommonAgent: 处理流式工具响应时发生错误: {str(e)}")
                    async for msg in self._handle_tool_error(tool_call['id'], tool_name, e):
                        yield msg
            else:
                # 处理非流式响应
                logger.debug("CommonAgent: 收到非流式工具响应，正在处理")
                logger.info(f"CommonAgent: 工具响应 {tool_response}")
                processed_response = self.process_tool_response(tool_response, tool_call['id'])
                yield processed_response

        except Exception as e:
            logger.error(f"CommonAgent: 执行工具 {tool_name} 时发生错误: {str(e)}")
            logger.error(f"CommonAgent: 执行工具 {tool_name} 时发生错误: {traceback.format_exc()}")
            async for msg in self._handle_tool_error(tool_call['id'], tool_name, e):
                yield msg

    async def _handle_tool_error(self, tool_call_id: str, tool_name: str, error: Exception) -> AsyncGenerator[List[MessageChunk], None]:
        """
        处理工具执行错误

        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            error: 错误信息

        Yields:
            tuple[List[MessageChunk], bool]: (错误消息块列表, 是否完成任务)
        """
        error_message = f"工具 {tool_name} 执行失败: {str(error)}"
        logger.error(f"CommonAgent: {error_message}")

        error_chunk = MessageChunk(
            role='tool',
            content=error_message,
            tool_call_id=tool_call_id,
            message_id=str(uuid.uuid4()),
            message_type=MessageType.TOOL_CALL_RESULT.value,
        )

        yield [error_chunk]

    def process_tool_response(self, tool_response: str, tool_call_id: str) -> List[Dict[str, Any]]:
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
                result = [MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=tool_response,
                    tool_call_id=tool_call_id,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.TOOL_CALL_RESULT.value
                )]
            elif 'messages' in tool_response_dict:
                result = [MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=msg,
                    tool_call_id=tool_call_id,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.TOOL_CALL_RESULT.value
                ) for msg in tool_response_dict['messages']]
            else:
                # 默认处理
                result = [MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=tool_response,
                    tool_call_id=tool_call_id,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.TOOL_CALL_RESULT.value
                )]

            logger.debug("CommonAgent: 工具响应处理成功")
            return result

        except json.JSONDecodeError:
            logger.warning("CommonAgent: 处理工具响应时JSON解码错误，按普通文本处理")
            return [MessageChunk(
                role=MessageRole.TOOL.value,
                content=tool_response,
                tool_call_id=tool_call_id,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.TOOL_CALL_RESULT.value
            )]
