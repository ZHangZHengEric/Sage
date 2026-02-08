from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, AsyncGenerator, cast, Union
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.utils.prompt_manager import PromptManager
import uuid


class TaskExecutorAgent(AgentBase):
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)
        self.TASK_EXECUTION_PROMPT_TEMPLATE = PromptManager().get_agent_prompt_auto('task_execution_template')
        self.agent_custom_system_prefix = PromptManager().get_agent_prompt_auto('task_executor_system_prefix')
        self.agent_name = "TaskExecutorAgent"
        self.agent_description = """
TaskExecutorAgent: 任务执行智能体，负责根据任务描述和要求，来执行任务。
"""
        logger.debug("TaskExecutorAgent 初始化完成")

    async def run_stream(self, session_context: SessionContext, tool_manager: Optional[ToolManager] = None, session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        # 重新获取模板和系统前缀，使用正确的语言
        self.TASK_EXECUTION_PROMPT_TEMPLATE = PromptManager().get_agent_prompt_auto('task_execution_template', language=session_context.get_language())
        self.agent_custom_system_prefix = PromptManager().get_agent_prompt_auto('task_executor_system_prefix', language=session_context.get_language())

        message_manager = session_context.message_manager
        if 'task_rewrite' in session_context.audit_status:
            rewrite_user = [MessageChunk(
                role=MessageRole.USER.value,
                content=session_context.audit_status['task_rewrite'],
                message_type=MessageType.NORMAL.value
            )]
            messages_after_last_user = message_manager.get_all_execution_messages_after_last_user(recent_turns=10)
            history_messages = rewrite_user + messages_after_last_user
        else:
            history_messages = message_manager.extract_all_context_messages(recent_turns=10, last_turn_user_only=True)
            messages_after_last_user = message_manager.get_all_execution_messages_after_last_user(recent_turns=12)
            history_messages.extend(messages_after_last_user)

        last_planning_message_dict = session_context.audit_status['all_plannings'][-1]['next_step']

        prompt = self.TASK_EXECUTION_PROMPT_TEMPLATE.format(
            next_subtask_description=last_planning_message_dict['description'],
            next_expected_output=last_planning_message_dict['expected_output']
        )
        prompt_message_chunk = MessageChunk(
            role=MessageRole.ASSISTANT.value,
            type=MessageType.EXECUTION.value,
            content=prompt,
            message_id=str(uuid.uuid4()),
            show_content=""
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language())
        ]
        llm_request_message.extend(history_messages)
        llm_request_message.append(prompt_message_chunk)
        yield [prompt_message_chunk]

        tools_json = self._prepare_tools(tool_manager, last_planning_message_dict, session_context)

        async for chunk in self._call_llm_and_process_response(
            messages_input=llm_request_message,
            tools_json=tools_json,
            tool_manager=tool_manager,
            session_id=session_id or ""
        ):
            yield chunk

    async def _call_llm_and_process_response(self,
                                             messages_input: List[MessageChunk],
                                             tools_json: List[Dict[str, Any]],
                                             tool_manager: Optional[ToolManager],
                                             session_id: str
                                             ) -> AsyncGenerator[List[MessageChunk], None]:

        clean_message_input = MessageManager.convert_messages_to_dict_for_request(messages_input)
        logger.info(f"SimpleAgent: 准备了 {len(clean_message_input)} 条消息用于LLM")

        # 准备模型配置覆盖，包含工具信息
        model_config_override = {}
        if len(tools_json) > 0:
            model_config_override['tools'] = tools_json

        response = self._call_llm_streaming(
            messages=cast(List[Union[MessageChunk, Dict[str, Any]]], clean_message_input),
            session_id=session_id,
            step_name="task_execution",
            model_config_override=model_config_override
        )

        tool_calls: Dict[str, Any] = {}
        reasoning_content_response_message_id = str(uuid.uuid4())
        content_response_message_id = str(uuid.uuid4())
        last_tool_call_id: Optional[str] = None

        # 处理流式响应块
        async for chunk in response:
            # print(chunk)
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.tool_calls:
                self._handle_tool_calls_chunk(chunk, tool_calls, last_tool_call_id or "")
                # 更新last_tool_call_id
                for tool_call in chunk.choices[0].delta.tool_calls:
                    if tool_call.id is not None and len(tool_call.id) > 0:
                        last_tool_call_id = tool_call.id
                # yield 一个空的消息块以避免生成器卡住
                output_messages = [MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="",
                    message_id=content_response_message_id,
                    show_content="",
                    message_type=MessageType.EMPTY.value
                )]
                yield output_messages

            elif chunk.choices[0].delta.content:
                if len(tool_calls) > 0:
                    logger.info(f"SimpleAgent: LLM响应包含 {len(tool_calls)} 个工具调用和内容，停止收集文本内容")
                    break

                if len(chunk.choices[0].delta.content) > 0:
                    output_messages = [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=chunk.choices[0].delta.content,
                        message_id=content_response_message_id,
                        show_content=chunk.choices[0].delta.content,
                        message_type=MessageType.DO_SUBTASK_RESULT.value
                    )]
                    yield output_messages
            else:
                # 先判断chunk.choices[0].delta 是否有reasoning_content 这个变量，并且不是none
                if hasattr(chunk.choices[0].delta, 'reasoning_content') and chunk.choices[0].delta.reasoning_content is not None:
                    output_messages = [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content="",
                        message_id=reasoning_content_response_message_id,
                        show_content=chunk.choices[0].delta.reasoning_content,
                        message_type=MessageType.TASK_ANALYSIS.value
                    )]
                    yield output_messages
        # 处理工具调用
        if len(tool_calls) > 0:
            async for chunk in self._handle_tool_calls(
                tool_calls=tool_calls,
                tool_manager=tool_manager,
                messages_input=cast(List[Dict[str, Any]], messages_input),
                session_id=session_id,
            ):
                yield chunk
        else:
            # 发送换行消息（也包含usage信息）
            output_messages = [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content='',
                message_id=content_response_message_id,
                show_content='\n',
                message_type=MessageType.DO_SUBTASK_RESULT.value
            )]
            yield output_messages

    def _prepare_tools(self,
                       tool_manager: Optional[ToolManager],
                       subtask_info: Dict[str, Any],
                       session_context: SessionContext) -> List[Dict[str, Any]]:
        """
        准备工具列表

        Args:
            tool_manager: 工具管理器
            subtask_info: 子任务信息
            session_context: 会话上下文

        Returns:
            List[Dict[str, Any]]: 工具配置列表
        """
        if not tool_manager:
            logger.warning("ExecutorAgent: 未提供工具管理器")
            return []

        # 获取所有工具
        tools_json = tool_manager.get_openai_tools(lang=session_context.get_language(), fallback_chain=["en"])

        # 根据建议的工具进行过滤，同时移除掉complete_task 这个工具
        suggested_tools = subtask_info.get('required_tools', [])
        if suggested_tools:
            tools_suggest_json = [
                tool for tool in tools_json
                if tool['function']['name'] in suggested_tools and tool['function']['name'] != 'complete_task'
            ]
            if tools_suggest_json:
                tools_json = tools_suggest_json

        tool_names = [tool['function']['name'] for tool in tools_json]
        logger.info(f"ExecutorAgent: 准备了 {len(tools_json)} 个工具: {tool_names}")

        return tools_json

    async def _handle_tool_calls(self,
                                 tool_calls: Dict[str, Any],
                                 tool_manager: Optional[ToolManager],
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
        logger.info(f"TaskExecutorAgent: LLM响应包含 {len(tool_calls)} 个工具调用")
        logger.info(f"TaskExecutorAgent: 工具调用: {tool_calls}")

        for tool_call_id, tool_call in tool_calls.items():
            tool_name = tool_call['function']['name']
            logger.info(f"TaskExecutorAgent: 执行工具 {tool_name}")
            logger.info(f"TaskExecutorAgent: 参数 {tool_call['function']['arguments']}")

            # 检查是否为complete_task
            if tool_name == 'complete_task':
                logger.info("TaskExecutorAgent: complete_task，停止执行")
                yield [MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content='已经完成了满足用户的所有要求',
                    message_id=str(uuid.uuid4()),
                    show_content='已经完成了满足用户的所有要求',
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
