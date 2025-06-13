"""
DirectExecutorAgent 重构版本

直接执行智能体，负责无推理策略的直接任务执行。
改进了代码结构、错误处理、日志记录和可维护性。

作者: Eric ZZ
版本: 2.0 (重构版)
"""

import json
import uuid
import datetime
import traceback
import time
from copy import deepcopy
from typing import List, Dict, Any, Optional, Generator

from agents.agent.agent_base import AgentBase
from agents.tool.tool_manager import ToolManager
from agents.utils.logger import logger


class DirectExecutorAgent(AgentBase):
    """
    直接执行智能体
    
    负责无推理策略的直接任务执行，比ReAct策略更快速。
    适用于不需要推理或早期处理的任务。
    """

    # 系统提示模板常量
    SYSTEM_PREFIX_DEFAULT = """你是一个直接执行智能体，负责无推理策略的直接任务执行。你比ReAct策略更快速，适用于不需要推理或早期处理的任务。
一定要先执行用户的问题或者请求，即使用户问题不清楚，也要回答或者询问用户的问题，不要直接结束任务。"""
    
    # 工具建议提示模板常量
    TOOL_SUGGESTION_PROMPT_TEMPLATE = """你是一个智能助手，你要根据用户的需求，为用户提供帮助，回答用户的问题或者满足用户的需求。
你当前数据库_id或者知识库_id：{session_id}
你要根据历史的对话以及用户的请求，获取解决用户请求用到的所有可能的工具。

## 可用工具
{available_tools_str}

## 用户的对话历史以及新的请求
{messages}

输出格式：
```json
[
    "工具名称1",
    "工具名称2",
    ...
]
```
注意：
1. 工具名称必须是可用工具中的名称。
2. 返回所有可能用到的工具名称，对于不可能用到的工具，不要返回。
3. 可能的工具最多返回7个。
"""

    # 最大循环次数常量
    MAX_LOOP_COUNT = 10

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        """
        初始化直接执行智能体
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        super().__init__(model, model_config, system_prefix)
        self.agent_description = """DirectExecutorAgent: 执行子任务，使用工具或LLM直接生成。
此智能体不使用ReAct或其他推理策略。
它根据提供的上下文和工具直接执行子任务。这对于不需要推理或早期处理的任务会更快。"""
        logger.info("DirectExecutorAgent 初始化完成")

    def run_stream(self, 
                   messages: List[Dict[str, Any]], 
                   tool_manager: Optional[Any] = None,
                   session_id: str = None,
                   system_context: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式执行直接任务处理
        
        直接处理用户输入的任务，不进行复杂的分解和规划，适用于简单任务。
        
        Args:
            messages: 对话历史记录
            tool_manager: 用于执行工具的工具管理器
            session_id: 会话ID
            system_context: 系统上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的直接执行结果消息块
            
        Raises:
            Exception: 当直接执行过程出现错误时抛出异常
        """
        logger.info(f"DirectExecutorAgent: 开始流式直接执行，会话ID: {session_id}")
        
        if not messages:
            logger.warning("DirectExecutorAgent: 未提供消息，返回空列表")
            return
        
        # 使用基类方法收集和记录流式输出
        yield from self._collect_and_log_stream_output(
            self._execute_direct_stream_internal(messages, tool_manager, session_id, system_context)
        )

    def _execute_direct_stream_internal(self, 
                                      messages: List[Dict[str, Any]], 
                                      tool_manager: Optional[Any],
                                      session_id: str,
                                      system_context: Optional[Dict[str, Any]]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        内部直接执行流式方法
        
        Args:
            messages: 对话历史记录
            tool_manager: 工具管理器
            session_id: 会话ID
            system_context: 系统上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的直接执行结果消息块
        """
        try:
            # 准备直接执行上下文
            execution_context = self._prepare_execution_context(
                messages=messages,
                session_id=session_id,
                system_context=system_context
            )
            
            # 生成直接执行消息
            execution_messages = self._prepare_initial_messages(messages, execution_context)
            
            # 获取建议工具
            suggested_tools = self._get_suggested_tools(
                messages_input=execution_messages,
                tool_manager=tool_manager,
                session_id=session_id
            )
            
            # 准备工具列表
            tools_json = self._prepare_tools(tool_manager, suggested_tools)
            
            # 执行直接任务处理
            yield from self._execute_loop(
                messages_input=execution_messages,
                tools_json=tools_json,
                tool_manager=tool_manager,
                session_id=session_id
            )
            
        except Exception as e:
            logger.error(f"DirectExecutorAgent: 直接执行过程中发生异常: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            yield from self._handle_execution_error(e)

    def _prepare_execution_context(self, 
                                 messages: List[Dict[str, Any]],
                                 session_id: str,
                                 system_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        准备执行所需的上下文信息
        
        Args:
            messages: 对话消息列表
            session_id: 会话ID
            system_context: 系统上下文
            
        Returns:
            Dict[str, Any]: 包含执行所需信息的上下文字典
        """
        logger.debug("DirectExecutorAgent: 准备执行上下文")
        
        current_time = system_context.get('current_time', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')) if system_context else datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        file_workspace = system_context.get('file_workspace', '无') if system_context else '无'
        
        execution_context = {
            'current_time': current_time,
            'file_workspace': file_workspace,
            'session_id': session_id,
            'system_context': system_context
        }
        
        logger.info("DirectExecutorAgent: 执行上下文准备完成")
        return execution_context

    def _prepare_initial_messages(self, 
                                messages: List[Dict[str, Any]], 
                                execution_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        准备初始消息列表
        
        Args:
            messages: 原始消息列表
            execution_context: 执行上下文
            
        Returns:
            List[Dict[str, Any]]: 包含系统消息的消息列表
        """
        logger.debug("DirectExecutorAgent: 准备初始消息")
        
        # 构造系统消息
        system_message = self.prepare_unified_system_message(
            session_id=execution_context.get('session_id'),
            system_context=execution_context.get('system_context')
        )
        
        # 深拷贝原始消息并添加系统消息
        messages_input = deepcopy(messages)
        messages_input = [system_message] + messages_input
        
        logger.debug(f"DirectExecutorAgent: 准备了 {len(messages_input)} 条初始消息")
        return messages_input

    def _get_suggested_tools(self, 
                           messages_input: List[Dict[str, Any]],
                           tool_manager: Optional[Any],
                           session_id: str) -> List[str]:
        """
        基于用户输入和历史对话获取建议工具
        
        Args:
            messages_input: 消息列表
            tool_manager: 工具管理器
            session_id: 会话ID
            
        Returns:
            List[str]: 建议工具名称列表
        """
        logger.info(f"DirectExecutorAgent: 开始获取建议工具，会话ID: {session_id}")
        
        if not messages_input or not tool_manager:
            logger.warning("DirectExecutorAgent: 未提供消息或工具管理器，返回空列表")
            return []
        
        try:
            # 获取可用工具
            available_tools = tool_manager.list_tools_simplified()
            available_tools_str = json.dumps(available_tools, ensure_ascii=False, indent=2) if available_tools else '无可用工具'
            
            # 准备消息
            clean_messages = self._prepare_messages_for_tool_suggestion(messages_input)
            
            # 生成提示
            prompt = self.TOOL_SUGGESTION_PROMPT_TEMPLATE.format(
                session_id=session_id,
                available_tools_str=available_tools_str,
                messages=json.dumps(clean_messages, ensure_ascii=False, indent=2)
            )
            
            # 调用LLM获取建议
            suggested_tools = self._get_tool_suggestions(prompt)
            
            # 添加complete_task工具
            suggested_tools.append('complete_task')
            
            logger.info(f"DirectExecutorAgent: 获取到建议工具: {suggested_tools}")
            return suggested_tools
            
        except Exception as e:
            logger.error(f"DirectExecutorAgent: 获取建议工具时发生错误: {str(e)}")
            return []

    def _prepare_messages_for_tool_suggestion(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        为工具建议准备消息
        
        Args:
            messages: 原始消息列表
            
        Returns:
            List[Dict[str, Any]]: 清理后的消息列表
        """
        logger.debug("DirectExecutorAgent: 为工具建议准备消息")
        
        # 移除多余字段，只保留核心信息
        new_messages = []
        for msg in messages:
            clean_msg = {
                'role': msg.get('role', None),
                'content': msg.get('content', None),
                'tool_call_id': msg.get('tool_call_id', None),
                'tool_calls': msg.get('tool_calls', None)
            }
            
            # 去掉None值的键
            clean_msg = {k: v for k, v in clean_msg.items() if v is not None}
            new_messages.append(clean_msg)
        
        logger.debug(f"DirectExecutorAgent: 清理后消息数量: {len(new_messages)}")
        return new_messages

    def _get_tool_suggestions(self, prompt: str) -> List[str]:
        """
        调用LLM获取工具建议（流式调用）
        
        Args:
            prompt: 提示文本
            
        Returns:
            List[str]: 建议工具列表
        """
        logger.debug("DirectExecutorAgent: 调用LLM获取工具建议（流式）")
        
        messages_input = [{'role': 'user', 'content': prompt}]
        
        # 跟踪token使用
        start_time = time.time()
        
        # 使用流式调用
        response = self.model.chat.completions.create(
            messages=messages_input,
            stream=True,
            stream_options={"include_usage": True},
            **self.model_config
        )
        
        # 收集流式响应内容
        chunks = []
        all_content = ""
        
        for chunk in response:
            chunks.append(chunk)
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                all_content += chunk.choices[0].delta.content
        
        # 跟踪token使用
        self._track_streaming_token_usage(chunks, "tool_suggestion", start_time)
        
        try:
            result_clean = self._extract_json_from_markdown(all_content)
            suggested_tools = json.loads(result_clean)
            return suggested_tools
        except json.JSONDecodeError:
            logger.warning("DirectExecutorAgent: 解析工具建议响应时JSON解码错误")
            return []

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
        logger.debug("DirectExecutorAgent: 准备工具列表")
        
        if not tool_manager or not suggested_tools:
            logger.warning("DirectExecutorAgent: 未提供工具管理器或建议工具")
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
        logger.info(f"DirectExecutorAgent: 准备了 {len(tools_json)} 个工具: {tool_names}")
        
        return tools_json

    def _execute_loop(self, 
                     messages_input: List[Dict[str, Any]],
                     tools_json: List[Dict[str, Any]],
                     tool_manager: Optional[Any],
                     session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行主循环
        
        Args:
            messages_input: 输入消息列表
            tools_json: 工具配置列表
            tool_manager: 工具管理器
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 执行结果消息块
        """
        logger.info("DirectExecutorAgent: 开始执行主循环")
        
        all_new_response_chunks = []
        loop_count = 0
        
        while True:
            loop_count += 1
            logger.info(f"DirectExecutorAgent: 循环计数: {loop_count}")
            
            if loop_count > self.MAX_LOOP_COUNT:
                logger.warning(f"DirectExecutorAgent: 循环次数超过 {self.MAX_LOOP_COUNT}，终止循环")
                break
            
            # 合并消息
            messages_input = self._merge_messages(messages_input, all_new_response_chunks)
            all_new_response_chunks = []
            
            # 调用LLM
            should_break = yield from self._call_llm_and_process_response(
                messages_input=messages_input,
                tools_json=tools_json,
                tool_manager=tool_manager,
                session_id=session_id,
                all_new_response_chunks=all_new_response_chunks
            )
            
            if should_break:
                break
            
            # 检查是否应该停止
            if self._should_stop_execution(all_new_response_chunks):
                logger.info("DirectExecutorAgent: 检测到停止条件，终止执行")
                break

    def _call_llm_and_process_response(self, 
                                     messages_input: List[Dict[str, Any]],
                                     tools_json: List[Dict[str, Any]],
                                     tool_manager: Optional[Any],
                                     session_id: str,
                                     all_new_response_chunks: List[Dict[str, Any]]) -> Generator[bool, List[Dict[str, Any]], None]:
        """
        调用LLM并处理响应
        
        Args:
            messages_input: 输入消息列表
            tools_json: 工具配置列表
            tool_manager: 工具管理器
            session_id: 会话ID
            all_new_response_chunks: 用于收集响应块的列表
            
        Yields:
            List[Dict[str, Any]]: 响应消息块
            
        Returns:
            bool: 是否应该终止循环
        """
        logger.debug("DirectExecutorAgent: 调用LLM并处理响应")
        
        # 清理消息
        clean_message_input = self.clean_messages(messages_input)
        logger.info(f"DirectExecutorAgent: 准备了 {len(clean_message_input)} 条消息用于LLM")
        
        # 调用LLM并开始token跟踪
        start_time = time.time()
        response = self.model.chat.completions.create(
            tools=tools_json if len(tools_json) > 0 else None,
            messages=clean_message_input,
            stream=True,
            stream_options={"include_usage": True},
            **self.model_config
        )
        
        # 处理流式响应并收集chunks用于token跟踪
        chunks = []
        call_task_complete = yield from self._process_streaming_response_with_tracking(
            response=response,
            tool_manager=tool_manager,
            messages_input=messages_input,
            session_id=session_id,
            all_new_response_chunks=all_new_response_chunks,
            chunks=chunks
        )
        
        # 跟踪token使用
        self._track_streaming_token_usage(chunks, "direct_execution", start_time)
        
        return call_task_complete

    def _process_streaming_response_with_tracking(self, 
                                                response,
                                                tool_manager: Optional[Any],
                                                messages_input: List[Dict[str, Any]],
                                                session_id: str,
                                                all_new_response_chunks: List[Dict[str, Any]],
                                                chunks: List) -> Generator[bool, List[Dict[str, Any]], None]:
        """
        处理流式响应并跟踪token使用
        
        Args:
            response: LLM流式响应
            tool_manager: 工具管理器
            messages_input: 输入消息列表
            session_id: 会话ID
            all_new_response_chunks: 用于收集响应块的列表
            chunks: 用于token跟踪的chunk列表
            
        Yields:
            List[Dict[str, Any]]: 处理后的响应消息块
            
        Returns:
            bool: 是否调用了complete_task
        """
        logger.debug("DirectExecutorAgent: 处理流式响应")
        
        tool_calls = {}
        unused_tool_content_message_id = str(uuid.uuid4())
        last_tool_call_id = None
        
        # 处理流式响应块
        for chunk in response:
            chunks.append(chunk)  # 收集chunk用于token跟踪
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.tool_calls:
                self._handle_tool_calls_chunk(chunk, tool_calls, last_tool_call_id)
                # 更新last_tool_call_id
                for tool_call in chunk.choices[0].delta.tool_calls:
                    if tool_call.id is not None and len(tool_call.id) > 0:
                        last_tool_call_id = tool_call.id
            
            elif chunk.choices[0].delta.content:
                if len(tool_calls) > 0:
                    logger.info(f"DirectExecutorAgent: LLM响应包含 {len(tool_calls)} 个工具调用和内容，停止收集文本内容")
                    break
                
                if len(chunk.choices[0].delta.content) > 0:
                    output_messages = self._create_message_chunk(
                        content=chunk.choices[0].delta.content,
                        message_id=unused_tool_content_message_id,
                        show_content=chunk.choices[0].delta.content,
                        message_type="do_subtask_result"
                    )
                    all_new_response_chunks.extend(output_messages)
                    yield output_messages
        
        # 处理工具调用
        call_task_complete = False
        if len(tool_calls) > 0:
            call_task_complete = yield from self._handle_tool_calls(
                tool_calls=tool_calls,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id,
                all_new_response_chunks=all_new_response_chunks
            )
        else:
            # 发送换行消息（也包含usage信息）
            if len(all_new_response_chunks) > 0:
                output_messages = self._create_message_chunk(
                    content='',
                    message_id=unused_tool_content_message_id,
                    show_content='\n',
                    message_type="do_subtask_result"
                )
                all_new_response_chunks.extend(output_messages)
                yield output_messages
        
        return call_task_complete

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
                logger.info(f"DirectExecutorAgent: 检测到新工具调用: {last_tool_call_id}, 工具名称: {tool_call.function.name}")
                tool_calls[last_tool_call_id] = {
                    'id': last_tool_call_id,
                    'type': tool_call.type,
                    'function': {
                        'name': tool_call.function.name,
                        'arguments': tool_call.function.arguments
                    }
                }
            else:
                if tool_call.function.name:
                    logger.info(f"DirectExecutorAgent: 更新工具调用: {last_tool_call_id}, 工具名称: {tool_call.function.name}")
                    tool_calls[last_tool_call_id]['function']['name'] = tool_call.function.name
                if tool_call.function.arguments:
                    tool_calls[last_tool_call_id]['function']['arguments'] += tool_call.function.arguments

    def _handle_tool_calls(self, 
                         tool_calls: Dict[str, Any],
                         tool_manager: Optional[Any],
                         messages_input: List[Dict[str, Any]],
                         session_id: str,
                         all_new_response_chunks: List[Dict[str, Any]]) -> Generator[bool, List[Dict[str, Any]], None]:
        """
        处理工具调用
        
        Args:
            tool_calls: 工具调用字典
            tool_manager: 工具管理器
            messages_input: 输入消息列表
            session_id: 会话ID
            all_new_response_chunks: 响应块列表
            
        Yields:
            List[Dict[str, Any]]: 工具执行结果消息块
            
        Returns:
            bool: 是否调用了complete_task
        """
        logger.info(f"DirectExecutorAgent: LLM响应包含 {len(tool_calls)} 个工具调用")
        logger.info(f"DirectExecutorAgent: 工具调用: {tool_calls}")
        
        for tool_call_id, tool_call in tool_calls.items():
            tool_name = tool_call['function']['name']
            logger.info(f"DirectExecutorAgent: 执行工具 {tool_name}")
            logger.info(f"DirectExecutorAgent: 参数 {tool_call['function']['arguments']}")
            
            # 检查是否为complete_task
            if tool_name == 'complete_task':
                logger.info("DirectExecutorAgent: complete_task，停止执行")
                return True
            
            # 发送工具调用消息
            output_messages = self._create_tool_call_message(tool_call)
            all_new_response_chunks.extend(output_messages)
            yield output_messages
            
            # 执行工具
            yield from self._execute_tool(
                tool_call=tool_call,
                tool_manager=tool_manager,
                messages_input=messages_input,
                session_id=session_id,
                all_new_response_chunks=all_new_response_chunks
            )
        
        return False

    def _create_tool_call_message(self, tool_call: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        创建工具调用消息
        
        Args:
            tool_call: 工具调用信息
            
        Returns:
            List[Dict[str, Any]]: 工具调用消息列表
        """
        return [{
            'role': 'assistant',
            'tool_calls': [{
                'id': tool_call['id'],
                'type': tool_call['type'],
                'function': {
                    'name': tool_call['function']['name'],
                    'arguments': tool_call['function']['arguments']
                }
            }],
            "type": "tool_call",
            "message_id": str(uuid.uuid4()),
            "show_content": "调用工具：" + tool_call['function']['name'] + '\n\n'
        }]

    def _execute_tool(self, 
                     tool_call: Dict[str, Any],
                     tool_manager: Optional[Any],
                     messages_input: List[Dict[str, Any]],
                     session_id: str,
                     all_new_response_chunks: List[Dict[str, Any]]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行工具
        
        Args:
            tool_call: 工具调用信息
            tool_manager: 工具管理器
            messages_input: 输入消息列表
            session_id: 会话ID
            all_new_response_chunks: 响应块列表
            
        Yields:
            List[Dict[str, Any]]: 工具执行结果消息块
        """
        tool_name = tool_call['function']['name']
        
        try:
            # 解析并执行工具调用
            arguments = json.loads(tool_call['function']['arguments'])
            logger.info(f"DirectExecutorAgent: 执行工具 {tool_name}")
            tool_response = tool_manager.run_tool(
                tool_name,
                messages=messages_input,
                session_id=session_id,
                **arguments
            )
            
            # 处理工具响应
            logger.debug("DirectExecutorAgent: 收到工具响应，正在处理")
            logger.info(f"DirectExecutorAgent: 工具响应 {tool_response}")
            processed_response = self.process_tool_response(tool_response, tool_call['id'])
            all_new_response_chunks.extend(processed_response)
            yield processed_response
            
        except Exception as e:
            logger.error(f"DirectExecutorAgent: 执行工具 {tool_name} 时发生错误: {str(e)}")
            yield from self._handle_tool_error(tool_call['id'], tool_name, e)

    def _should_stop_execution(self, all_new_response_chunks: List[Dict[str, Any]]) -> bool:
        """
        判断是否应该停止执行
        
        Args:
            all_new_response_chunks: 响应块列表
            
        Returns:
            bool: 是否应该停止执行
        """
        if len(all_new_response_chunks) < 10:
            logger.debug(f"DirectExecutorAgent: 响应块: {json.dumps(all_new_response_chunks, ensure_ascii=False, indent=2)}")
        
        if len(all_new_response_chunks) == 0:
            logger.info("DirectExecutorAgent: 没有更多响应块，停止执行")
            return True
        
        # 如果所有响应块都没有工具调用且没有内容，就停止执行
        if all(
            item.get('tool_calls', None) is None and 
            (item.get('content', None) is None or item.get('content', None) == '')
            for item in all_new_response_chunks
        ):
            logger.info("DirectExecutorAgent: 没有更多响应块，停止执行")
            return True
        
        return False

    def _handle_execution_error(self, error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理执行过程中的错误
        
        Args:
            error: 发生的异常
            
        Yields:
            List[Dict[str, Any]]: 错误消息块
        """
        yield from self._handle_error_generic(
            error=error,
            error_context="任务执行",
            message_type='do_subtask_result'
        )

    def _handle_tool_error(self, 
                          tool_call_id: str, 
                          tool_name: str, 
                          error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理工具执行错误
        
        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            error: 发生的异常
            
        Yields:
            List[Dict[str, Any]]: 工具错误消息块
        """
        logger.error(f"DirectExecutorAgent: 工具 {tool_name} 执行错误: {str(error)}")
        
        error_message = f"工具 {tool_name} 执行失败: {str(error)}"
        
        yield [{
            'role': 'tool',
            'content': error_message,
            'tool_call_id': tool_call_id,
            "message_id": str(uuid.uuid4()),
            "type": "tool_call_result",
            "show_content": "工具调用失败\n\n"
        }]

    def process_tool_response(self, tool_response: str, tool_call_id: str) -> List[Dict[str, Any]]:
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
                result = [{
                    'role': 'tool',
                    'content': tool_response,
                    'tool_call_id': tool_call_id,
                    "message_id": str(uuid.uuid4()),
                    "type": "tool_call_result",
                    "show_content": '\n```json\n' + json.dumps(tool_response_dict['content'], ensure_ascii=False, indent=2) + '\n```\n'
                }]
            elif 'messages' in tool_response_dict:
                result = tool_response_dict['messages']
            else:
                # 默认处理
                result = [{
                    'role': 'tool',
                    'content': tool_response,
                    'tool_call_id': tool_call_id,
                    "message_id": str(uuid.uuid4()),
                    "type": "tool_call_result",
                    "show_content": '\n' + tool_response + '\n'
                }]
            
            logger.debug("DirectExecutorAgent: 工具响应处理成功")
            return result
            
        except json.JSONDecodeError:
            logger.warning("DirectExecutorAgent: 处理工具响应时JSON解码错误")
            return [{
                'role': 'tool',
                'content': '\n' + tool_response + '\n',
                'tool_call_id': tool_call_id,
                "message_id": str(uuid.uuid4()),
                "type": "tool_call_result",
                "show_content": "工具调用失败\n\n"
            }]

    def _get_last_sub_task(self, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        获取最后一个子任务消息
        
        Args:
            messages: 消息列表
            
        Returns:
            Optional[Dict[str, Any]]: 最后一个子任务消息，如果未找到则返回None
        """
        logger.debug(f"DirectExecutorAgent: 从 {len(messages)} 条消息中查找最后一个子任务")
        
        for i in range(len(messages) - 1, -1, -1):
            if (messages[i]['role'] == 'assistant' and 
                messages[i].get('type', None) == 'planning_result'):
                logger.debug(f"DirectExecutorAgent: 在索引 {i} 处找到最后一个子任务")
                return messages[i]
        
        logger.warning("DirectExecutorAgent: 未找到planning_result类型的消息")
        return None

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            session_id: str = None,
            system_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        执行直接任务处理（非流式版本）
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            session_id: 会话ID
            system_context: 系统上下文
            
        Returns:
            List[Dict[str, Any]]: 直接执行结果消息列表
        """
        logger.info("DirectExecutorAgent: 执行非流式直接任务处理")
        
        # 调用父类的默认实现，将流式结果合并
        return super().run(
            messages=messages,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        )