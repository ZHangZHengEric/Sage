import traceback
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, AsyncGenerator, Union, cast
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import SessionContext, get_session_context, SessionStatus
from sagents.tool.tool_manager import ToolManager
from sagents.utils.prompt_manager import PromptManager
from sagents.tool.tool_schema import convert_spec_to_openai_format
from sagents.utils.content_saver import save_agent_response_content
import json
import uuid
from copy import deepcopy


class SimpleAgent(AgentBase):
    """
    简单智能体

    负责无推理策略的直接任务执行，比ReAct策略更快速。
    适用于不需要推理或早期处理的任务。
    """

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        super().__init__(model, model_config, system_prefix)

        # 最大循环次数常量
        self.max_loop_count = 100
        self.agent_name = "SimpleAgent"
        self.agent_description = """SimpleAgent: 简单智能体，负责无推理策略的直接任务执行，比ReAct策略更快速。适用于不需要推理或早期处理的任务。"""
        logger.debug(f"SimpleAgent 初始化完成，最大循环次数为 {self.max_loop_count}")

    async def run_stream(self, session_context: SessionContext,
                         tool_manager: Optional[ToolManager] = None,
                         session_id: Optional[str] = None) -> AsyncGenerator[List[MessageChunk], None]:
        if self._should_abort_due_to_session(session_id, session_context):
            return

        # 重新获取agent_custom_system_prefix以支持动态语言切换
        current_system_prefix = PromptManager().get_agent_prompt_auto(
            "agent_custom_system_prefix", language=session_context.get_language()
        )

        # 从会话管理中，获取消息管理实例
        message_manager = session_context.message_manager
        # 从消息管理实例中，获取满足context 长度限制的消息
        history_messages = message_manager.extract_all_context_messages(recent_turns=20, last_turn_user_only=False)
        
        # 根据 active_budget 压缩消息
        budget_info = message_manager.context_budget_manager.budget_info
        if budget_info:
             history_messages = MessageManager.compress_messages(history_messages, budget_info.get('active_budget', 8000))
             logger.info(f'SimpleAgent: 压缩历史消息的条数:{len(history_messages)}，压缩后历史消息的content长度：{MessageManager.calculate_messages_token_length(cast(List[Union[MessageChunk, Dict[str, Any]]], history_messages))}')
        # 获取后续可能使用到的工具建议
        if tool_manager:
            suggested_tools = await self._get_suggested_tools(history_messages, tool_manager, session_id or "", session_context)
        else:
            suggested_tools = []
        # 准备工具列表
        tools_json = self._prepare_tools(tool_manager, suggested_tools, session_context)
        # 将system 加入到到messages中
        system_message = self.prepare_unified_system_message(
            session_id,
            custom_prefix=current_system_prefix,
            language=session_context.get_language(),
        )
        history_messages.insert(0, system_message)
        async for chunk in self._execute_loop(
            messages_input=history_messages,
            tools_json=tools_json,
            tool_manager=tool_manager,
            session_id=session_id or "",
            session_context=session_context
        ):
            yield chunk

    def _prepare_tools(self,
                       tool_manager: Optional[Any],
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
        logger.debug("SimpleAgent: 准备工具列表")

        if not tool_manager or not suggested_tools:
            logger.warning("SimpleAgent: 未提供工具管理器或建议工具")
            return []

        # 获取所有工具
        tools_json = tool_manager.get_openai_tools(lang=session_context.get_language(), fallback_chain=["en"])

        # 根据建议过滤工具
        # 强制包含 todo 工具，如果它们存在于可用工具中
        always_include = ['todo_write', 'todo_read']
        
        tools_suggest_json = [
            tool for tool in tools_json
            if tool['function']['name'] in suggested_tools or tool['function']['name'] in always_include
        ]
        
        if tools_suggest_json:
            tools_json = tools_suggest_json

        tool_names = [tool['function']['name'] for tool in tools_json]
        logger.debug(f"SimpleAgent: 准备了 {len(tools_json)} 个工具: {tool_names}")

        return tools_json

    async def _is_task_complete(self,
                                messages_input: List[MessageChunk],
                                session_id: str,
                                session_context: SessionContext) -> bool:
        # 如果最后一个messages role 是tool，说明是工具调用的结果，不是用户的请求，所以不是任务完成
        if messages_input[-1].role == 'tool':
            logger.info("messages_input[-1].role是 tool 调用结果，不是任务完成")
            return False

        # 只提取最后一个user以及之后的messages
        last_user_index = None
        for i, message in enumerate(messages_input):
            if message.role == 'user' and message.type == MessageType.NORMAL.value:
                last_user_index = i
        if last_user_index is not None:
            messages_for_complete = messages_input[last_user_index:]
        else:
            messages_for_complete = messages_input
        clean_messages = MessageManager.convert_messages_to_dict_for_request(messages_for_complete)

        task_complete_template = PromptManager().get_agent_prompt_auto('task_complete_template', language=session_context.get_language())
        prompt = task_complete_template.format(
            system_prompt=self.prepare_unified_system_message(
                session_id,
                custom_prefix=PromptManager().get_agent_prompt_auto(
                                                "agent_custom_system_prefix", language=session_context.get_language()
                                            ),
                language=session_context.get_language(),
                include_sections=["role_definition"]
            ),
            session_id=session_id,
            messages=json.dumps(clean_messages, ensure_ascii=False, indent=2)
        )
        messages_input = [{'role': 'user', 'content': prompt}]
        # 使用基类的流式调用方法，自动处理LLM request日志
        response = self._call_llm_streaming(
            messages=cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input),
            session_id=session_id,
            step_name="task_complete_judge"
        )
        # 收集流式响应内容
        all_content = ""
        async for chunk in response:
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                all_content += chunk.choices[0].delta.content
        try:
            result_clean = MessageChunk.extract_json_from_markdown(all_content)
            result = json.loads(result_clean)
            return result.get('task_interrupted', False)
        except json.JSONDecodeError:
            logger.warning("SimpleAgent: 解析任务完成判断响应时JSON解码错误")
            return False



    async def _execute_loop(self,
                            messages_input: List[MessageChunk],
                            tools_json: List[Dict[str, Any]],
                            tool_manager: Optional[ToolManager],
                            session_id: str,
                            session_context: SessionContext) -> AsyncGenerator[List[MessageChunk], None]:
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

        if self._should_abort_due_to_session(session_id, session_context):
            return
        all_new_response_chunks: List[MessageChunk] = []
        loop_count = 0
        # 从session context 检查一下是否有max_loop_count ，如果有，本次请求使用session context 中的max_loop_count
        max_loop_count = session_context.agent_config.get('maxLoopCount', self.max_loop_count)
        logger.info(f"SimpleAgent: 开始执行主循环，最大循环次数：{max_loop_count}")
        while True:
            if self._should_abort_due_to_session(session_id, session_context):
                break
            loop_count += 1
            logger.info(f"SimpleAgent: 循环计数: {loop_count}")

            if loop_count > max_loop_count:
                logger.warning(f"SimpleAgent: 循环次数超过 {max_loop_count}，终止循环")
                yield [MessageChunk(role=MessageRole.ASSISTANT.value, content=f"Agent执行次数超过最大循环次数：{max_loop_count}, 任务暂停，是否需要继续执行？", type=MessageType.NORMAL.value)]
                break

            # 合并消息
            messages_input = MessageManager.merge_new_messages_to_old_messages(
                cast(List[Union[MessageChunk, Dict[str, Any]]], all_new_response_chunks),
                cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input)
            )
            all_new_response_chunks = []
            current_system_prefix = PromptManager().get_agent_prompt_auto("agent_custom_system_prefix", language=session_context.get_language())

            # 更新system message，确保包含最新的子智能体列表等上下文信息
            if messages_input and messages_input[0].role == MessageRole.SYSTEM.value:
                system_message = self.prepare_unified_system_message(
                    session_id,
                    custom_prefix=current_system_prefix,
                    language=session_context.get_language(),
                )
                messages_input[0] = system_message

            # --- 上下文压缩检测逻辑 ---
            # 调用 MessageManager 执行压缩检测和压缩
            # 返回一个压缩（或者没有变化）后的 messages_for_llm，用于放到 _call_llm_and_process_response 中
            messages_for_llm = session_context.message_manager.compress_messages_if_needed(
                cast(List[MessageChunk], messages_input)
            )

            # 调用LLM
            should_break = False
            async for chunks, is_complete in self._call_llm_and_process_response(
                messages_input=messages_for_llm,
                tools_json=tools_json,
                tool_manager=tool_manager,
                session_id=session_id
            ):
                non_empty_chunks = [c for c in chunks if (c.message_type != MessageType.EMPTY.value)]
                if len(non_empty_chunks) > 0:
                    all_new_response_chunks.extend(deepcopy(non_empty_chunks))
                yield chunks
                if is_complete:
                    should_break = True
                    break

            if should_break:
                break

            # 检查是否应该停止
            if self._should_stop_execution(all_new_response_chunks):
                logger.info("SimpleAgent: 检测到停止条件，终止执行")
                break

            messages_input = MessageManager.merge_new_messages_to_old_messages(
                cast(List[Union[MessageChunk, Dict[str, Any]]], all_new_response_chunks),
                cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input)
            )
            all_new_response_chunks = []

            if MessageManager.calculate_messages_token_length(cast(List[Union[MessageChunk, Dict[str, Any]]], messages_input)) > self.max_model_input_len:
                logger.warning(f"SimpleAgent: 消息长度超过 {self.max_model_input_len}，截断消息")
                # 任务暂停，返回一个超长的错误消息块
                yield [MessageChunk(role=MessageRole.ASSISTANT.value, content=f"消息长度超过最大长度：{self.max_model_input_len},是否需要继续执行？", type=MessageType.ERROR.value)]
                break
            if self._should_abort_due_to_session(session_id, session_context):
                break
            # 检查任务是否完成
            if await self._is_task_complete(messages_input, session_id, session_context):
                logger.info("SimpleAgent: 任务完成，终止执行")
                break

    def _should_abort_due_to_session(self, session_id: Optional[str], session_context: SessionContext) -> bool:
        if session_id and get_session_context(session_id) is None:
            logger.info("SimpleAgent: 跳过执行，session上下文不存在或已中断")
            return True
        if session_context.status == SessionStatus.INTERRUPTED:
            logger.info("SimpleAgent: 跳过执行，session上下文状态为中断")
            return True
        return False

    async def _call_llm_and_process_response(self,
                                             messages_input: List[MessageChunk],
                                             tools_json: List[Dict[str, Any]],
                                             tool_manager: Optional[ToolManager],
                                             session_id: str
                                             ) -> AsyncGenerator[tuple[List[MessageChunk], bool], None]:

        clean_message_input = MessageManager.convert_messages_to_dict_for_request(messages_input)
        logger.info(f"SimpleAgent: 准备了 {len(clean_message_input)} 条消息用于LLM")

        # 准备模型配置覆盖，包含工具信息
        model_config_override = {}
        
        # 总是添加 load_skill 工具，如果有技能管理器
        # 这确保了它不会被过滤掉，并且直接传递给 LLM
        session_context = get_session_context(session_id)
        # if session_context and session_context.skill_manager and tool_manager:
        #     # 检查是否已经存在
        #     if not any(t['function']['name'] == 'load_skill' for t in tools_json):
        #         load_skill_tool = tool_manager.get_tool('load_skill')
        #         if load_skill_tool:
        #             skill_tool_schema = convert_spec_to_openai_format(load_skill_tool, lang=session_context.get_language())
        #             tools_json.append(skill_tool_schema)
        #             logger.debug("SimpleAgent: Added load_skill tool to tools_json via override logic")

        if len(tools_json) > 0:
            model_config_override['tools'] = tools_json

        response = self._call_llm_streaming(
            messages=cast(List[Union[MessageChunk, Dict[str, Any]]], clean_message_input),
            session_id=session_id,
            step_name="direct_execution",
            model_config_override=model_config_override
        )

        tool_calls: Dict[str, Any] = {}
        reasoning_content_response_message_id = str(uuid.uuid4())
        content_response_message_id = str(uuid.uuid4())
        last_tool_call_id = None
        full_content_accumulator = ""

        # 处理流式响应块
        async for chunk in response:
            # print(chunk)
            if chunk is None:
                logger.warning(f"Received None chunk from LLM response, skipping... chunk: {chunk}")
                continue
            if chunk.choices is None:
                logger.warning(f"Received chunk with None choices from LLM response, skipping... chunk: {chunk}")
                continue
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
                yield (output_messages, False)

            elif chunk.choices[0].delta.content:
                if len(tool_calls) > 0:
                    logger.info(f"SimpleAgent: LLM响应包含 {len(tool_calls)} 个工具调用和内容，停止收集文本内容")
                    break

                if len(chunk.choices[0].delta.content) > 0:
                    content_piece = chunk.choices[0].delta.content
                    full_content_accumulator += content_piece
                    output_messages = [MessageChunk(
                        role='assistant',
                        content=content_piece,
                        message_id=content_response_message_id,
                        message_type=MessageType.DO_SUBTASK_RESULT.value,
                        agent_name=self.agent_name
                    )]
                    yield (output_messages, False)
            else:
                # 先判断chunk.choices[0].delta 是否有reasoning_content 这个变量，并且不是none
                if hasattr(chunk.choices[0].delta, 'reasoning_content') and chunk.choices[0].delta.reasoning_content is not None:
                    output_messages = [MessageChunk(
                        role='assistant',
                        content=chunk.choices[0].delta.reasoning_content,
                        message_id=reasoning_content_response_message_id,
                        message_type=MessageType.TASK_ANALYSIS.value,
                        agent_name=self.agent_name
                    )]
                    yield (output_messages, False)
        
        # 处理完所有chunk后，尝试保存内容
        if full_content_accumulator:
             try:
                 save_agent_response_content(full_content_accumulator, session_id)
             except Exception as e:
                 logger.error(f"SimpleAgent: Failed to save response content: {e}")

        # 处理工具调用
        if len(tool_calls) > 0:
            # 识别是否包含结束任务的工具调用
            termination_tool_ids = set()
            for tool_call_id, tool_call in tool_calls.items():
                if tool_call['function']['name'] in ['complete_task', 'sys_finish_task']:
                    termination_tool_ids.add(tool_call_id)

            async for chunk in self._handle_tool_calls(
                tool_calls=tool_calls,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id or ""
            ):
                # chunk 是 (messages, is_complete)
                messages, is_complete = chunk
                
                # 如果当前消息块是结束任务工具的执行结果，则标记为完成
                if termination_tool_ids and not is_complete:
                    for msg in messages:
                        if msg.role == MessageRole.TOOL.value and msg.tool_call_id in termination_tool_ids:
                            logger.info(f"SimpleAgent: 检测到结束任务工具 {msg.tool_call_id} 执行完成，标记任务结束")
                            is_complete = True
                            break
                
                yield (messages, is_complete)

        else:
            # 发送换行消息（也包含usage信息）
            output_messages = [MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content='\n',
                message_id=content_response_message_id,
                message_type=MessageType.DO_SUBTASK_RESULT.value,
                agent_name=self.agent_name
            )]
            yield (output_messages, False)

    async def _handle_tool_calls(self,
                                 tool_calls: Dict[str, Any],
                                 tool_manager: Optional[ToolManager],
                                 messages_input: List[MessageChunk],
                                 session_id: str) -> AsyncGenerator[tuple[List[MessageChunk], bool], None]:
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
        logger.info(f"SimpleAgent: LLM响应包含 {len(tool_calls)} 个工具调用")
        logger.info(f"SimpleAgent: 工具调用: {tool_calls}")

        for tool_call_id, tool_call in tool_calls.items():
            tool_name = tool_call['function']['name']
            logger.info(f"SimpleAgent: 执行工具 {tool_name}")
            logger.info(f"SimpleAgent: 参数 {tool_call['function']['arguments']}")

            # 发送工具调用消息
            output_messages = self._create_tool_call_message(tool_call)
            yield (output_messages, False)

            # 执行工具
            async for message_chunk_list in self._execute_tool(
                tool_call=tool_call,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id
            ):
                yield (message_chunk_list, False)

    def _should_stop_execution(self, all_new_response_chunks: List[MessageChunk]) -> bool:
        """
        判断是否应该停止执行

        Args:
            all_new_response_chunks: 响应块列表

        Returns:
            bool: 是否应该停止执行
        """
        if len(all_new_response_chunks) < 10:
            logger.debug(f"SimpleAgent: 响应块: {all_new_response_chunks}")

        if len(all_new_response_chunks) == 0:
            logger.info("SimpleAgent: 没有更多响应块，停止执行")
            return True

        # 如果所有响应块都没有工具调用且没有内容，就停止执行
        if all(
            item.tool_calls is None and
            (item.content is None or item.content == '')
            for item in all_new_response_chunks
        ):
            logger.info("SimpleAgent: 没有更多响应块，停止执行")
            return True

        return False
