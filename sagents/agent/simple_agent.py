import traceback
from sagents.context.messages import message_manager
from sagents.context.messages.message_manager import MessageManager
from .agent_base import AgentBase
from typing import Any, Dict, List, Optional, Generator
from sagents.utils.logger import logger
from sagents.context.messages.message import MessageChunk, MessageRole,MessageType
from sagents.context.session_context import SessionContext,get_session_context
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_base import AgentToolSpec
from sagents.utils.prompt_manager import PromptManager
import json
import uuid
from copy import deepcopy

class SimpleAgent(AgentBase):
    """
    简单智能体
    
    负责无推理策略的直接任务执行，比ReAct策略更快速。
    适用于不需要推理或早期处理的任务。
    """
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", max_model_len: int = 64000):
        super().__init__(model, model_config, system_prefix, max_model_len)

        self.agent_custom_system_prefix = PromptManager().get_agent_prompt_auto('agent_custom_system_prefix')
        # 最大循环次数常量
        self.max_loop_count = 30
        self.agent_name = "SimpleAgent"
        self.agent_description = """SimpleAgent: 简单智能体，负责无推理策略的直接任务执行，比ReAct策略更快速。适用于不需要推理或早期处理的任务。"""
        logger.info(f"SimpleAgent 初始化完成，最大循环次数为 {self.max_loop_count}")

    async def run_stream(self, session_context: SessionContext, 
                    tool_manager: Optional[Any] = None, 
                    session_id: str = None) -> Generator[List[MessageChunk], None, None]:
        logger.info(f"SimpleAgent: 开始流式直接执行，会话ID: {session_id}")
        
        # 重新获取agent_custom_system_prefix以支持动态语言切换
        self.agent_custom_system_prefix = PromptManager().get_agent_prompt_auto('agent_custom_system_prefix', language=session_context.get_language())

        # 从会话管理中，获取消息管理实例
        message_manager = session_context.message_manager
        # 从消息管理实例中，获取满足context 长度限制的消息
        logger.info(f"SimpleAgent: 全部消息长度：{MessageManager.calculate_messages_token_length(message_manager.messages)}")
        history_messages = message_manager.extract_all_context_messages(recent_turns=4,max_length=self.max_history_context_length,last_turn_user_only=False)
        logger.info(f'SimpleAgent: 获取历史消息的条数:{len(history_messages)}')
        logger.info(f'历史消息的content长度：{MessageManager.calculate_messages_token_length(history_messages)}')
        system_context = session_context.system_context
        # 调用内部方法，执行流式直接执行
        async for chunk in self._execute_direct_stream_internal(history_messages, 
                                                        tool_manager, 
                                                        session_id, 
                                                        system_context,
                                                        session_context):
            yield chunk

    async def _execute_direct_stream_internal(self, 
                                messages: List[MessageChunk], 
                                tool_manager: ToolManager,
                                session_id: str,
                                system_context: Optional[Dict[str, Any]],
                                session_context: SessionContext) -> Generator[List[MessageChunk], None, None]:
        logger.info(f"SimpleAgent: 输入的消息长度：{len(messages)}")
        # 获取后续可能使用到的工具建议
        suggested_tools = self._get_suggested_tools(messages, tool_manager, session_id, session_context)
        
        # 准备工具列表
        tools_json = self._prepare_tools(tool_manager, suggested_tools)

        # 将system 加入到到messages中
        system_message = self.prepare_unified_system_message(session_id,custom_prefix=self.agent_custom_system_prefix)
        messages.insert(0, system_message)


        async for chunk in self._execute_loop(
                messages_input=messages,
                tools_json=tools_json,
                tool_manager=tool_manager,
                session_id=session_id,
                session_context=session_context
            ):
            yield chunk

    def _prepare_tools(self, 
                      tool_manager: Optional[Any], 
                      suggested_tools: List[str]) -> List[Dict[str, Any]]:
        """
        准备工具列表
        
        Args:
            tool_manager: 工具管理器
            suggested_tools: 建议工具列表
            
        Returns:
            List[Dict[str, Any]]: 工具配置列表
        """
        logger.debug("SimpleAgent: 准备工具列表")
        
        if not tool_manager or not suggested_tools:
            logger.warning("SimpleAgent: 未提供工具管理器或建议工具")
            return []
        
        # 获取所有工具
        tools_json = tool_manager.get_openai_tools()
        
        # 根据建议过滤工具
        tools_suggest_json = [
            tool for tool in tools_json 
            if tool['function']['name'] in suggested_tools
        ]
        
        if tools_suggest_json:
            tools_json = tools_suggest_json
        
        tool_names = [tool['function']['name'] for tool in tools_json]
        logger.info(f"SimpleAgent: 准备了 {len(tools_json)} 个工具: {tool_names}")
        
        return tools_json

    def _is_task_complete(self,
                            messages_input: List[MessageChunk],
                            session_id: str,
                            session_context: SessionContext) -> bool:
        # 如果最后一个messages role 是tool，说明是工具调用的结果，不是用户的请求，所以不是任务完成
        if messages_input[-1].role == 'tool':
            logger.info(f"messages_input[-1].role是 tool 调用结果，不是任务完成")
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
                session_id=session_id,
                messages=json.dumps(clean_messages, ensure_ascii=False, indent=2)
        )
        messages_input = [{'role': 'user', 'content': prompt}]
        # 使用基类的流式调用方法，自动处理LLM request日志
        response = self._call_llm_streaming(
            messages=messages_input,
            session_id=session_id,  
            step_name="task_complete_judge"
        )
        # 收集流式响应内容
        all_content = ""
        for chunk in response:
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                all_content += chunk.choices[0].delta.content
        try:
            result_clean = MessageChunk.extract_json_from_markdown(all_content)
            result = json.loads(result_clean)
            return result['task_interrupted']
        except json.JSONDecodeError:
            logger.warning("SimpleAgent: 解析任务完成判断响应时JSON解码错误")
            return False

    def _get_suggested_tools(self, 
                           messages_input: List[MessageChunk],
                           tool_manager: ToolManager,
                           session_id: str,
                           session_context: SessionContext) -> List[str]:
        """
        基于用户输入和历史对话获取建议工具
        
        Args:
            messages_input: 消息列表
            tool_manager: 工具管理器
            session_id: 会话ID
            
        Returns:
            List[str]: 建议工具名称列表
        """
        logger.info(f"SimpleAgent: 开始获取建议工具，会话ID: {session_id}")
        
        if not messages_input or not tool_manager:
            logger.warning("SimpleAgent: 未提供消息或工具管理器，返回空列表")
            return []
        try:
            # 获取可用工具，只提取工具名称
            available_tools = tool_manager.list_tools_simplified()
            
            tool_names = [tool['name'] for tool in available_tools] if available_tools else []
            if len(tool_names) <= 10:
                logger.info(f"SimpleAgent: 可用工具数量小于等于9个，直接返回所有工具: {tool_names}")
                if 'complete_task' in tool_names:
                    tool_names.remove('complete_task')
                return tool_names
            available_tools_str = ", ".join(tool_names) if tool_names else '无可用工具'
            
            # 准备消息
            clean_messages = MessageManager.convert_messages_to_dict_for_request(messages_input)
            
            # 生成提示
            tool_suggestion_template = PromptManager().get_agent_prompt_auto('tool_suggestion_template', language=session_context.get_language())
            prompt = tool_suggestion_template.format(
                session_id=session_id,
                available_tools_str=available_tools_str,
                agent_config=self.prepare_unified_system_message(session_id,custom_prefix=self.agent_custom_system_prefix).content,
                messages=json.dumps(clean_messages, ensure_ascii=False, indent=2)
            )
            
            # 调用LLM获取建议
            suggested_tools = self._get_tool_suggestions(prompt, session_id)
            
            # 添加complete_task工具
            # suggested_tools.append('complete_task')
            # 如果有complete_task 要去掉
            if 'complete_task' in suggested_tools:
                suggested_tools.remove('complete_task')
            
            logger.info(f"SimpleAgent: 获取到建议工具: {suggested_tools}")
            return suggested_tools
            
        except Exception as e:
            logger.error(traceback.format_exc())
            logger.error(f"SimpleAgent: 获取建议工具时发生错误: {str(e)}")
            return []

    def _get_tool_suggestions(self, prompt: str, session_id: str) -> List[str]:
        """
        调用LLM获取工具建议（流式调用）
        
        Args:
            prompt: 提示文本
            
        Returns:
            List[str]: 建议工具列表
        """
        logger.debug("SimpleAgent: 调用LLM获取工具建议（流式）")
        
        messages_input = [{'role': 'user', 'content': prompt}]
        # 使用基类的流式调用方法，自动处理LLM request日志
        response = self._call_llm_streaming(
            messages=messages_input,
            session_id=session_id,  
            step_name="tool_suggestion"
        )
        # 收集流式响应内容
        all_content = ""
        for chunk in response:
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                all_content += chunk.choices[0].delta.content
        try:
            result_clean = MessageChunk.extract_json_from_markdown(all_content)
            suggested_tools = json.loads(result_clean)
            return suggested_tools
        except json.JSONDecodeError:
            logger.warning("SimpleAgent: 解析工具建议响应时JSON解码错误")
            return []

    async def _execute_loop(self, 
                     messages_input: List[MessageChunk],
                     tools_json: List[Dict[str, Any]],
                     tool_manager: Optional[Any],
                     session_id: str,
                     session_context: SessionContext) -> Generator[List[MessageChunk], None, None]:
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
        logger.info("SimpleAgent: 开始执行主循环")
        
        all_new_response_chunks = []
        loop_count = 0
        # 从session context 检查一下是否有max_loop_count ，如果有，本次请求使用session context 中的max_loop_count
        max_loop_count = session_context.agent_config.get('maxLoopCount', self.max_loop_count)

        while True:
            loop_count += 1
            logger.info(f"SimpleAgent: 循环计数: {loop_count}")
            
            if loop_count > max_loop_count:
                logger.warning(f"SimpleAgent: 循环次数超过 {max_loop_count}，终止循环")
                break
            
            # 合并消息
            messages_input = MessageManager.merge_new_messages_to_old_messages(all_new_response_chunks,messages_input)
            all_new_response_chunks = []
            
            # 调用LLM
            should_break = False
            async for chunks, is_complete in self._call_llm_and_process_response(
                messages_input=messages_input,
                tools_json=tools_json,
                tool_manager=tool_manager,
                session_id=session_id
            ):
                all_new_response_chunks.extend(deepcopy(chunks))
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
            
            messages_input = MessageManager.merge_new_messages_to_old_messages(all_new_response_chunks,messages_input)
            all_new_response_chunks = []

            if MessageManager.calculate_messages_token_length(messages_input) > self.max_model_input_len:
                logger.warning(f"SimpleAgent: 消息长度超过 {self.max_model_input_len}，截断消息")
                # 任务暂停，返回一个超长的错误消息块
                yield [MessageChunk(role=MessageRole.ASSISTANT.value, content=f"消息长度超过最大长度：{self.max_model_input_len},是否需要继续执行？",type=MessageType.ERROR.value)]
                break
            
            # 检查任务是否完成
            if self._is_task_complete(messages_input, session_id, session_context):
                logger.info("SimpleAgent: 任务完成，终止执行")
                break
            
    async def _call_llm_and_process_response(self,
        messages_input: List[MessageChunk],
        tools_json: List[Dict[str, Any]],
        tool_manager: Optional[Any],
        session_id: str
    ) -> Generator[tuple[List[MessageChunk], bool], None, None]:

        clean_message_input = MessageManager.convert_messages_to_dict_for_request(messages_input)
        logger.info(f"SimpleAgent: 准备了 {len(clean_message_input)} 条消息用于LLM")
        
        # 准备模型配置覆盖，包含工具信息
        model_config_override = {}
        if len(tools_json) > 0:
            model_config_override['tools'] = tools_json

        response = self._call_llm_streaming(
            messages=clean_message_input,
            session_id=session_id,
            step_name="direct_execution",
            model_config_override=model_config_override
        )

        tool_calls = {}
        reasoning_content_response_message_id = str(uuid.uuid4())
        content_response_message_id = str(uuid.uuid4())
        last_tool_call_id = None
        
        # 处理流式响应块
        for chunk in response:
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
                    show_content="",
                    message_type=MessageType.DO_SUBTASK_RESULT.value
                )]
                yield (output_messages, False)

            elif chunk.choices[0].delta.content:
                if len(tool_calls) > 0:
                    logger.info(f"SimpleAgent: LLM响应包含 {len(tool_calls)} 个工具调用和内容，停止收集文本内容")
                    break
                
                if len(chunk.choices[0].delta.content) > 0:
                    output_messages = [MessageChunk(
                        role='assistant',
                        content=chunk.choices[0].delta.content,
                        message_id=content_response_message_id,
                        show_content=chunk.choices[0].delta.content,
                        message_type=MessageType.DO_SUBTASK_RESULT.value
                    )]
                    yield (output_messages, False)
            else:
                # 先判断chunk.choices[0].delta 是否有reasoning_content 这个变量，并且不是none
                if hasattr(chunk.choices[0].delta, 'reasoning_content') and chunk.choices[0].delta.reasoning_content is not None:
                    output_messages = [MessageChunk(
                        role='assistant',
                        content="",
                        message_id=reasoning_content_response_message_id,
                        show_content=chunk.choices[0].delta.reasoning_content,
                        message_type=MessageType.TASK_ANALYSIS.value
                    )]
                    yield (output_messages, False)
        # 处理工具调用
        if len(tool_calls) > 0:
            async for chunk in self._handle_tool_calls(
                tool_calls=tool_calls,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id
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
            yield (output_messages, False)

    def _handle_tool_calls_chunk(self, 
                               chunk, 
                               tool_calls: Dict[str, Any], 
                               last_tool_call_id: str) -> None:
        """
        处理工具调用数据块
        
        Args:
            chunk: LLM响应块
            tool_calls: 工具调用字典
            last_tool_call_id: 最后的工具调用ID
        """
        for tool_call in chunk.choices[0].delta.tool_calls:
            if tool_call.id is not None and len(tool_call.id) > 0:
                last_tool_call_id = tool_call.id
                
            if last_tool_call_id not in tool_calls:
                logger.info(f"SimpleAgent: 检测到新工具调用: {last_tool_call_id}, 工具名称: {tool_call.function.name}")
                tool_calls[last_tool_call_id] = {
                    'id': last_tool_call_id,
                    'type': tool_call.type,
                    'function': {
                        'name': tool_call.function.name or "",
                        'arguments': tool_call.function.arguments if tool_call.function.arguments else ""
                    }
                }
            else:
                if tool_call.function.name:
                    logger.info(f"SimpleAgent: 更新工具调用: {last_tool_call_id}, 工具名称: {tool_call.function.name}")
                    tool_calls[last_tool_call_id]['function']['name'] = tool_call.function.name
                if tool_call.function.arguments:
                    tool_calls[last_tool_call_id]['function']['arguments'] += tool_call.function.arguments

    async def _handle_tool_calls(self, 
                         tool_calls: Dict[str, Any],
                         tool_manager: Optional[Any],
                         messages_input: List[Dict[str, Any]],
                         session_id: str) -> Generator[tuple[List[MessageChunk], bool], None, None]:
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
            
            # 检查是否为complete_task
            if tool_name == 'complete_task':
                logger.info("SimpleAgent: complete_task，停止执行")
                yield ([], True)
                return
            
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
    def _create_tool_call_message(self, tool_call: Dict[str, Any]) -> List[MessageChunk]:
        """
        创建工具调用消息
        
        Args:
            tool_call: 工具调用信息
            
        Returns:
            List[Dict[str, Any]]: 工具调用消息列表
        """
        # 格式化工具参数显示
        # 格式化工具参数显示
        if '```<｜tool▁call▁end｜>' in tool_call['function']['arguments']:
            logger.debug(f"SimpleAgent: 原始错误参数: {tool_call['function']['arguments']}")
            # 去掉```<｜tool▁call▁end｜> 以及之后所有的字符
            tool_call['function']['arguments'] = tool_call['function']['arguments'].split('```<｜tool▁call▁end｜>')[0]
        # 格式化工具参数显示
        function_params = tool_call['function']['arguments']
        if len(tool_call['function']['arguments'])>0:
            try:
                function_params = json.loads(tool_call['function']['arguments'])
            except json.JSONDecodeError:
                try:
                    function_params = eval(tool_call['function']['arguments'])
                except:
                    logger.error(f"SimpleAgent: 第一次参数解析报错，再次进行参数解析失败")
                    logger.error(f"SimpleAgent: 原始参数: {tool_call['function']['arguments']}")
            
            if isinstance(function_params, str):
                try:
                    function_params = json.loads(function_params)
                except json.JSONDecodeError:
                    try:
                        function_params = eval(function_params)
                    except:
                        logger.error(f"SimpleAgent: 解析完参数化依旧后是str，再次进行参数解析失败")
                        logger.error(f"SimpleAgent: 原始参数: {tool_call['function']['arguments']}")
                        logger.error(f"SimpleAgent: 工具参数格式错误: {function_params}")
                        logger.error(f"SimpleAgent: 工具参数类型: {type(function_params)}")
            formatted_params = ''
            if isinstance(function_params, dict):
                tool_call['function']['arguments'] = json.dumps(function_params,ensure_ascii=False)
                for param, value in function_params.items():
                    # 对于字符串的参数，在format时需要截断，避免过长，并且要用引号包裹,不要使用f-string的写法
                    # 要对value进行转移，打印的时候，不会发生换行
                    # if isinstance(value, str) and len(value) > 100:
                    #     value = f'"{value[:30]}"'
                    formatted_params += f"{param} = {json.dumps(value,ensure_ascii=False)}, "
                formatted_params = formatted_params.rstrip(', ')
        else:
            formatted_params = ""

        tool_name = tool_call['function']['name']
        
        # 将show_content 整理成函数调用的形式
        # func_name(param1 = ,param2)
        return [MessageChunk(
            role='assistant',
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
            show_content=f"{tool_name}({formatted_params})"
        )]

    async def _execute_tool(self, 
                     tool_call: Dict[str, Any],
                     tool_manager: Optional[Any],
                     messages_input: List[Dict[str, Any]],
                     session_id: str) -> Generator[List[MessageChunk], None, None]:
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
            if len(tool_call['function']['arguments'])>0:
                arguments = json.loads(tool_call['function']['arguments'])
            else:
                arguments = {}
            tool_response = await tool_manager.run_tool_async(
                tool_name,
                session_context=get_session_context(session_id),
                session_id=session_id,
                **arguments
            )
            
            # 检查是否为流式响应（AgentToolSpec）
            if hasattr(tool_response, '__iter__') and not isinstance(tool_response, (str, bytes)):
                # 检查是否为专业agent工具
                tool_spec = tool_manager.get_tool(tool_name) if tool_manager else None
                is_agent_tool = isinstance(tool_spec, AgentToolSpec)
                
                # 处理流式响应
                logger.debug(f"SimpleAgent: 收到流式工具响应，工具类型: {'专业Agent' if is_agent_tool else '普通工具'}")
                try:
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
                                    if isinstance(message,dict):
                                        message_chunks.append(MessageChunk(
                                            role=MessageRole.TOOL.value,
                                            content=message['content'],
                                            tool_call_id=tool_call['id'],
                                            message_id=str(uuid.uuid4()),
                                            message_type=MessageType.TOOL_CALL_RESULT.value,
                                            show_content=message['content']
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
                                        show_content=chunk['content']
                                    )
                                    yield [message_chunk_]
                except Exception as e:
                    logger.error(f"SimpleAgent: 处理流式工具响应时发生错误: {str(e)}")
                    async for chunk in self._handle_tool_error(tool_call['id'], tool_name, e):
                        yield chunk
            else:
                # 处理非流式响应
                logger.debug("SimpleAgent: 收到非流式工具响应，正在处理")
                logger.info(f"SimpleAgent: 工具响应 {tool_response}")
                processed_response = await self.process_tool_response(tool_response, tool_call['id'])
                yield processed_response
            
        except Exception as e:
            logger.error(f"SimpleAgent: 执行工具 {tool_name} 时发生错误: {str(e)}")
            async for chunk in self._handle_tool_error(tool_call['id'], tool_name, e):
                yield chunk

    async def _handle_tool_error(self, tool_call_id: str, tool_name: str, error: Exception) -> Generator[List[MessageChunk], None, None]:
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
        logger.error(f"SimpleAgent: {error_message}")
        
        error_chunk = MessageChunk(
            role='tool',
            content=error_message,
            tool_call_id=tool_call_id,
            message_id=str(uuid.uuid4()),
            message_type=MessageType.TOOL_CALL_RESULT.value,
            show_content=error_message
        )
        
        yield [error_chunk]
    
    async def process_tool_response(self, tool_response: str, tool_call_id: str) -> List[Dict[str, Any]]:
        """
        处理工具执行响应
        
        Args:
            tool_response: 工具执行响应
            tool_call_id: 工具调用ID
            
        Returns:
            List[Dict[str, Any]]: 处理后的结果消息
        """
        logger.debug(f"DirectExecutorAgent: 处理工具响应，工具调用ID: {tool_call_id}")
        
        try:
            tool_response_dict = json.loads(tool_response)
            
            if "content" in tool_response_dict:
                result = [MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=tool_response,
                    tool_call_id=tool_call_id,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                    show_content='\n```json\n' + json.dumps(tool_response_dict['content'], ensure_ascii=False, indent=2) + '\n```\n'
                )]
            elif 'messages' in tool_response_dict:
                result = [MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=msg,
                    tool_call_id=tool_call_id,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                    show_content=msg
                ) for msg in tool_response_dict['messages']]
            else:
                # 默认处理
                result = [MessageChunk(
                    role=MessageRole.TOOL.value,
                    content=tool_response,
                    tool_call_id=tool_call_id,
                    message_id=str(uuid.uuid4()),
                    message_type=MessageType.TOOL_CALL_RESULT.value,
                    show_content='\n' + tool_response + '\n'
                )]
            
            logger.debug("DirectExecutorAgent: 工具响应处理成功")
            return result
            
        except json.JSONDecodeError:
            logger.warning("DirectExecutorAgent: 处理工具响应时JSON解码错误")
            return [MessageChunk(
                role='tool',
                content='\n' + tool_response + '\n',
                tool_call_id=tool_call_id,
                message_id=str(uuid.uuid4()),
                message_type=MessageType.TOOL_CALL_RESULT.value,
                show_content="工具调用失败\n\n"
            )]


    def _should_stop_execution(self, all_new_response_chunks: List[Dict[str, Any]]) -> bool:
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
