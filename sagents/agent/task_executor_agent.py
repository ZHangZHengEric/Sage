from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, AsyncGenerator, cast, Union
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.utils.prompt_manager import PromptManager

from sagents.utils.content_saver import save_agent_response_content
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
       
        history_messages = message_manager.extract_all_context_messages(recent_turns=10, last_turn_user_only=False)

        # 根据 active_budget 压缩消息
        budget_info = message_manager.context_budget_manager.budget_info
        if budget_info:
             history_messages = MessageManager.compress_messages(history_messages, min(budget_info.get('active_budget', 8000), 8000))

        last_planning_message_dict = session_context.audit_status['all_plannings'][-1]['next_step']

        prompt = self.TASK_EXECUTION_PROMPT_TEMPLATE.format(
            next_subtask_description=last_planning_message_dict['description']
        )
        prompt_message_chunk = MessageChunk(
            role=MessageRole.ASSISTANT.value,
            type=MessageType.EXECUTION.value,
            content=prompt,
            message_id=str(uuid.uuid4())
        )
        llm_request_message = [
            self.prepare_unified_system_message(session_id=session_id, language=session_context.get_language())
        ]
        llm_request_message.extend(history_messages)
        llm_request_message.append(prompt_message_chunk)
        # yield [prompt_message_chunk]

        # 1. 获取建议工具
        if tool_manager:
            suggested_tools = await self._get_suggested_tools(history_messages, tool_manager, session_id or "", session_context)
        else:
            suggested_tools = []
        
        # 2. 准备工具
        tools_json = self._prepare_tools(tool_manager, suggested_tools, session_context)

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
        full_content_accumulator = ""

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
                    message_type=MessageType.EMPTY.value
                )]
                yield output_messages

            elif chunk.choices[0].delta.content:
                if len(tool_calls) > 0:
                    logger.info(f"SimpleAgent: LLM响应包含 {len(tool_calls)} 个工具调用和内容，停止收集文本内容")
                    break

                if len(chunk.choices[0].delta.content) > 0:
                    content_piece = chunk.choices[0].delta.content
                    full_content_accumulator += content_piece
                    output_messages = [MessageChunk(
                        role=MessageRole.ASSISTANT.value,
                        content=content_piece,
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
        
        # 处理完所有chunk后，尝试保存内容
        if full_content_accumulator:
             try:
                 save_agent_response_content(full_content_accumulator, session_id)
             except Exception as e:
                 logger.error(f"TaskExecutorAgent: Failed to save response content: {e}")

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
                content='\n',
                message_id=content_response_message_id,
                message_type=MessageType.DO_SUBTASK_RESULT.value
            )]
            yield output_messages

    def _prepare_tools(self,
                       tool_manager: Optional[ToolManager],
                       suggested_tools: List[str],
                       session_context: SessionContext) -> List[Dict[str, Any]]:
        """
        准备工具列表

        Args:
            tool_manager: 工具管理器
            suggested_tools: 建议工具列表
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
        # suggested_tools 已经是 List[str] 了，直接使用
        
        # 验证 suggested_tools 中的工具是否真实存在于 tool_manager 中
        # 如果存在无效工具名，可能是模型幻觉，此时最好回退到使用所有工具，以免遗漏
        available_tool_names = {tool['function']['name'] for tool in tools_json}
        
        # 过滤掉 load_skill 后再检查，因为 load_skill 稍后会特殊处理
        tools_to_check = [t for t in suggested_tools if t != 'load_skill']
        
        if tools_to_check:
            invalid_tools = [t for t in tools_to_check if t not in available_tool_names]
            if invalid_tools:
                logger.warning(f"TaskExecutorAgent: 发现无效的建议工具 {invalid_tools}，将忽略建议列表并使用所有工具")
                suggested_tools = [] # 清空建议列表，触发后续使用全量工具逻辑
        
        # 如果存在建议工具且有技能管理器，确保 load_skill 包含在内
        if suggested_tools and session_context.skill_manager and session_context.skill_manager.list_skills():
            if 'load_skill' not in suggested_tools:
                suggested_tools.append('load_skill')
        
        if suggested_tools:
            tools_suggest_json = [
                tool for tool in tools_json
                if tool['function']['name'] in suggested_tools and tool['function']['name'] != 'complete_task'
            ]
            
            # 再次确认过滤后的列表非空（虽然前面已经做了校验，但双重保险）
            if tools_suggest_json:
                tools_json = tools_suggest_json
            else:
                logger.warning("TaskExecutorAgent: 过滤后工具列表为空，回退到使用所有工具")

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
