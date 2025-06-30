"""
ExecutorAgent 重构版本

执行智能体，负责使用工具或LLM直接执行子任务。
改进了代码结构、错误处理、日志记录和可维护性。

作者: Eric ZZ
版本: 2.0 (重构版)
"""

import json
import datetime
import traceback
import uuid
import time
from copy import deepcopy
from typing import List, Dict, Any, Optional, Generator

from agents.agent.agent_base import AgentBase
from agents.tool.tool_manager import ToolManager
from agents.tool.tool_base import AgentToolSpec
from agents.utils.logger import logger


class ExecutorAgent(AgentBase):
    """
    执行智能体
    
    负责执行子任务，可以使用工具调用或直接的LLM生成。
    支持流式输出，实时返回执行结果。
    """

    # 任务执行提示模板常量
    TASK_EXECUTION_PROMPT_TEMPLATE = """请执行以下需求或者任务：{next_subtask_description}

期望输出：{next_expected_output}

请直接开始执行任务，观察历史对话，不要做重复性的工作。"""

    # 系统提示模板常量
    SYSTEM_PREFIX_DEFAULT = """你是个任务执行助手，你需要根据最新的任务描述和要求，来执行任务。
    
注意以下的任务执行规则，不要使用工具集合之外的工具，否则会报错：
1. 如果不需要使用工具，直接返回中文内容。你的文字输出都要是markdown格式。
2. 只能在工作目录下读写文件。如果用户没有提供文件路径，你应该在这个目录下创建一个新文件。
3. 调用工具时，不要在其他的输出文字，尽可能调用不互相依赖的全部工具。
4. 输出的文字中不要暴露你的工作目录，id信息以及你的工具名称。

如果在工具集合包含file_write函数工具，要求如下：
5. 如果是要生成计划、方案、内容创作，代码等大篇幅文字，请使用file_write函数工具将内容分多次保存到文件中，文件内容是函数的参数，格式使用markdown。
6. 如果需要编写代码，请使用file_write函数工具，代码内容是函数的参数。
7. 如果是输出报告或者总结，请使用file_write函数工具，报告内容是函数的参数，格式使用markdown。
8. 如果使用file_write创建文件，一定要在工作目录下创建文件，要求文件路径是绝对路径。
"""
    
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        """
        初始化执行智能体
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        super().__init__(model, model_config, system_prefix)
        self.agent_description = "ExecutorAgent: 执行子任务，使用工具或LLM直接生成"
        logger.info("ExecutorAgent 初始化完成")

    def run_stream(self, 
                   message_manager: Any,
                   task_manager: Optional[Any] = None,
                   tool_manager: Optional[Any] = None,
                   session_id: Optional[str] = None,
                   system_context: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式执行任务
        
        Args:
            message_manager: 消息管理器（必需）
            task_manager: 任务管理器
            tool_manager: 工具管理器
            session_id: 会话ID
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        if not message_manager:
            raise ValueError("ExecutorAgent: message_manager 是必需参数")
        
        # 从MessageManager获取优化后的消息
        optimized_messages = message_manager.filter_messages_for_agent(self.__class__.__name__)
        logger.info(f"ExecutorAgent: 开始流式任务执行，获取到 {len(optimized_messages)} 条优化消息")
        
        # 使用基类方法收集和记录流式输出，并将结果添加到MessageManager
        for chunk_batch in self._collect_and_log_stream_output(
            self._execute_stream_internal(optimized_messages, tool_manager, session_id, system_context, task_manager)
        ):
            # Agent自己负责将生成的消息添加到MessageManager
            message_manager.add_messages(chunk_batch, agent_name="ExecutorAgent")
            yield chunk_batch

    def _execute_stream_internal(self, 
                               messages: List[Dict[str, Any]], 
                               tool_manager: Optional[Any],
                               session_id: str,
                               system_context: Optional[Dict[str, Any]],
                               task_manager: Optional[Any] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        内部流式执行方法
        
        Args:
            messages: 包含子任务的对话历史记录
            tool_manager: 工具管理器
            session_id: 会话ID
            system_context: 系统上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的执行结果消息块
        """
        try:
            # 准备执行上下文
            execution_context = self._prepare_execution_context(
                messages=messages,
                session_id=session_id,
                system_context=system_context
            )
            
            # 解析子任务信息
            subtask_info = self._parse_subtask_info(messages)
            
            # 生成执行提示并准备消息
            execution_messages = self._prepare_execution_messages(
                messages=messages,
                subtask_info=subtask_info,
                execution_context=execution_context
            )
            # logger.info(f"ExecutorAgent: 执行消息: {execution_messages}")
            # 发送任务执行提示
            yield from self._send_task_execution_prompt(subtask_info)
            
            # 执行任务
            yield from self._execute_task_with_tools(
                execution_messages=execution_messages,
                tool_manager=tool_manager,
                subtask_info=subtask_info,
                session_id=session_id
            )
            
        except Exception as e:
            logger.error(f"ExecutorAgent: 执行过程中发生异常: {str(e)}")
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
        # 提取相关消息
        task_description_messages = self._extract_task_description_messages(messages)
        completed_actions_messages = self._extract_completed_actions_messages(messages)
        
        # 获取上下文信息
        current_time = system_context.get('current_time', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')) if system_context else datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        file_workspace = system_context.get('file_workspace', '无') if system_context else '无'
        
        execution_context = {
            'task_description_messages': task_description_messages,
            'completed_actions_messages': completed_actions_messages,
            'current_time': current_time,
            'file_workspace': file_workspace,
            'session_id': session_id,
            'system_context': system_context
        }
        
        logger.info("ExecutorAgent: 执行上下文准备完成")
        return execution_context

    def _parse_subtask_info(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        解析子任务信息
        
        Args:
            messages: 消息列表
            
        Returns:
            Dict[str, Any]: 包含子任务描述、期望输出和所需工具的字典
            
        Raises:
            json.JSONDecodeError: 当JSON解析失败时抛出
        """
        try:
            # 查找最新的planning_result类型消息
            last_subtask_message = None
            for message in reversed(messages):
                if message.get('type') == 'planning_result':
                    last_subtask_message = message
                    break
            
            if last_subtask_message is None:
                raise ValueError("未找到planning_result类型的消息")
            
            # 解析子任务内容
            content = last_subtask_message['content']
            
            if content.startswith('Planning: '):
                content = content[len('Planning: '):]
            
            # 清理content内容
            cleaned_content = content.strip('```json\\n').strip('```')
            
            # 尝试解析JSON
            try:
                subtask_dict = json.loads(cleaned_content)
            except json.JSONDecodeError as json_err:
                logger.error(f"ExecutorAgent: JSON解析失败: {str(json_err)}")
                raise json_err
            
            subtask_info = {
                'description': subtask_dict['next_step']['description'],
                'expected_output': subtask_dict['next_step']['expected_output'],
                'required_tools': subtask_dict['next_step'].get('required_tools', [])
            }
            
            logger.info(f"ExecutorAgent: 解析子任务成功 - {subtask_info['description']}")
            
            return subtask_info
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"ExecutorAgent: 解析子任务失败: {str(e)}")
            raise json.JSONDecodeError("Failed to parse subtask message as JSON", doc=str(e), pos=0)

    def _prepare_execution_messages(self, 
                                  messages: List[Dict[str, Any]],
                                  subtask_info: Dict[str, Any],
                                  execution_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        准备执行消息列表
        
        Args:
            messages: 原始消息列表
            subtask_info: 子任务信息
            execution_context: 执行上下文
            
        Returns:
            List[Dict[str, Any]]: 准备好的执行消息列表
        """
        # 准备系统消息
        system_message = self.prepare_unified_system_message(
            session_id=execution_context.get('session_id'),
            system_context=execution_context.get('system_context')
        )
        
        # 使用新的方法提取最近消息
        recent_messages = self._extract_recent_messages(messages)
        
        # 深拷贝消息
        messages_input = deepcopy(recent_messages)
        messages_input = [system_message] + messages_input
        
        # 添加任务执行提示
        task_prompt = self.TASK_EXECUTION_PROMPT_TEMPLATE.format(
            next_subtask_description=subtask_info['description'],
            next_expected_output=subtask_info['expected_output']
        )
        
        request_message = {
            'role': 'assistant',
            'content': task_prompt,
            'type': 'do_subtask',
            'message_id': str(uuid.uuid4()),
            'show_content': ""
        }
        
        messages_input.append(request_message)
        
        return messages_input

    def _send_task_execution_prompt(self, subtask_info: Dict[str, Any]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        发送任务执行提示消息
        
        Args:
            subtask_info: 子任务信息
            
        Yields:
            List[Dict[str, Any]]: 任务执行提示消息块
        """
        task_prompt = self.TASK_EXECUTION_PROMPT_TEMPLATE.format(
            next_subtask_description=subtask_info['description'],
            next_expected_output=subtask_info['expected_output']
        )
        
        request_message = {
            'role': 'assistant',
            'content': task_prompt,
            'type': 'do_subtask',
            'message_id': str(uuid.uuid4()),
            'show_content': ""
        }
        
        yield [request_message]

    def _execute_task_with_tools(self, 
                               execution_messages: List[Dict[str, Any]],
                               tool_manager: Optional[Any],
                               subtask_info: Dict[str, Any],
                               session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        使用工具执行任务
        
        Args:
            execution_messages: 执行消息列表
            tool_manager: 工具管理器
            subtask_info: 子任务信息
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 执行结果消息块
        """
        logger.info("ExecutorAgent: 开始使用工具执行任务")
        
        # 清理消息格式
        clean_messages = self.clean_messages(execution_messages)
        
        # 准备工具
        tools_json = self._prepare_tools(tool_manager, subtask_info)
        
        # 调用LLM
        response = self._call_llm_with_tools(clean_messages, tools_json, session_id)
        
        # 处理流式响应
        yield from self._process_streaming_response(
            response=response,
            tool_manager=tool_manager,
            execution_messages=execution_messages,
            session_id=session_id
        )

    def _prepare_tools(self, 
                      tool_manager: Optional[Any], 
                      subtask_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        准备工具列表
        
        Args:
            tool_manager: 工具管理器
            subtask_info: 子任务信息
            
        Returns:
            List[Dict[str, Any]]: 工具配置列表
        """
        if not tool_manager:
            logger.warning("ExecutorAgent: 未提供工具管理器")
            return []
        
        # 获取所有工具
        tools_json = tool_manager.get_openai_tools()
        
        # 根据建议的工具进行过滤
        suggested_tools = subtask_info.get('required_tools', [])
        if suggested_tools:
            tools_suggest_json = [
                tool for tool in tools_json 
                if tool['function']['name'] in suggested_tools
            ]
            if tools_suggest_json:
                tools_json = tools_suggest_json

        tool_names = [tool['function']['name'] for tool in tools_json]
        logger.info(f"ExecutorAgent: 准备了 {len(tools_json)} 个工具: {tool_names}")
        
        return tools_json

    def _call_llm_with_tools(self, 
                           messages: List[Dict[str, Any]], 
                           tools_json: List[Dict[str, Any]],
                           session_id: Optional[str] = None):
        """
        调用LLM并支持工具调用
        
        Args:
            messages: 消息列表
            tools_json: 工具配置列表
            session_id: 会话ID（用于LLM请求记录）
            
        Returns:
            Generator: LLM流式响应
        """
        # 准备模型配置，包含工具
        model_config_with_tools = {**self.model_config}
        if tools_json:
            model_config_with_tools["tools"] = tools_json
        
        # 使用基类的流式调用方法来确保LLM请求被记录
        return self._call_llm_streaming(
            messages=messages,
            session_id=session_id,
            step_name="tool_execution",
            model_config_override=model_config_with_tools
        )

    def _process_streaming_response(self, 
                                  response,
                                  tool_manager: Optional[Any],
                                  execution_messages: List[Dict[str, Any]],
                                  session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理流式响应
        
        Args:
            response: LLM流式响应
            tool_manager: 工具管理器
            execution_messages: 执行消息列表
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 处理后的响应消息块
        """
        logger.info("ExecutorAgent: 开始处理流式响应")
        
        tool_calls = {}
        unused_tool_content_message_id = str(uuid.uuid4())
        last_tool_call_id = None
        text_content_length = 0
        
        # 处理流式响应
        for chunk in response:
            if len(chunk.choices) == 0:
                continue
                
            if chunk.choices[0].delta.tool_calls:
                # 先更新last_tool_call_id，再传递给_handle_tool_calls_chunk
                for tool_call in chunk.choices[0].delta.tool_calls:
                    if tool_call.id and len(tool_call.id) > 0:
                        last_tool_call_id = tool_call.id
                
                try:
                    self._handle_tool_calls_chunk(
                        chunk=chunk,
                        tool_calls=tool_calls,
                        last_tool_call_id=last_tool_call_id
                    )
                except Exception as e:
                    logger.error(f"ExecutorAgent: 调用_handle_tool_calls_chunk时发生异常: {str(e)}")
                    import traceback
                    logger.error(f"ExecutorAgent: 异常堆栈: {traceback.format_exc()}")
                        
            elif chunk.choices[0].delta.content:
                if tool_calls:
                    # 有工具调用时停止收集文本内容
                    logger.info(f"ExecutorAgent: 检测到工具调用，停止收集文本内容")
                    break
                
                content = chunk.choices[0].delta.content
                text_content_length += len(content)
                
                # 使用基类的消息创建函数
                yield self._create_message_chunk(
                    content=content,
                    message_id=unused_tool_content_message_id,
                    show_content=content,
                    message_type='do_subtask_result'
                )
        
        # 处理工具调用或发送结束消息
        if tool_calls:
            logger.info(f"ExecutorAgent: 开始执行 {len(tool_calls)} 个工具调用")
            yield from self._execute_tool_calls(
                tool_calls=tool_calls,
                tool_manager=tool_manager,
                execution_messages=execution_messages,
                session_id=session_id
            )
        else:
            # 发送结束消息（使用基类函数）
            logger.info(f"ExecutorAgent: 无工具调用，发送结束消息")
            yield self._create_message_chunk(
                content='',
                message_id=unused_tool_content_message_id,
                show_content='\n',
                message_type='do_subtask_result'
            )

    def _handle_tool_calls_chunk(self, 
                               chunk,
                               tool_calls: Dict[str, Any],
                               last_tool_call_id: str) -> None:
        """
        处理工具调用数据块
        
        Args:
            chunk: LLM响应块
            tool_calls: 工具调用字典（会被修改）
            last_tool_call_id: 最后的工具调用ID
        """
        for tool_call in chunk.choices[0].delta.tool_calls:
            if tool_call.id and len(tool_call.id) > 0:
                last_tool_call_id = tool_call.id                            
                
            if last_tool_call_id not in tool_calls:
                logger.info(f"ExecutorAgent: 检测到新工具调用: {getattr(tool_call.function, 'name', 'None')}")
                tool_calls[last_tool_call_id] = {
                    'id': last_tool_call_id,
                                'type': tool_call.type,
                                'function': {
                                    'name': getattr(tool_call.function, 'name', ''),
                                    'arguments': getattr(tool_call.function, 'arguments', '')
                                }
                            }
            else:
                if hasattr(tool_call.function, 'name') and tool_call.function.name:
                    tool_calls[last_tool_call_id]['function']['name'] = tool_call.function.name
                if hasattr(tool_call.function, 'arguments') and tool_call.function.arguments:
                    tool_calls[last_tool_call_id]['function']['arguments'] += tool_call.function.arguments

    def _execute_tool_calls(self, 
                          tool_calls: Dict[str, Any],
                          tool_manager: Optional[Any],
                          execution_messages: List[Dict[str, Any]],
                          session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行工具调用（逐个工具调用模式）
        
        Args:
            tool_calls: 工具调用字典
            tool_manager: 工具管理器
            execution_messages: 执行消息列表（会被修改以包含工具调用和响应）
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 工具执行结果消息块
        """
        logger.info(f"ExecutorAgent: 逐个执行 {len(tool_calls)} 个工具调用")
        
        # 逐个执行每个工具调用
        for tool_call_id, tool_call in tool_calls.items():
            tool_name = tool_call['function']['name']
            
            try:
                logger.info(f"ExecutorAgent: 执行工具 {tool_name}")
                
                # 1. 创建单个工具调用消息
                single_tool_call_message = {
                    'role': 'assistant',
                    'tool_calls': [tool_call],  # 只包含当前工具调用
                    'message_id': str(uuid.uuid4()),
                    'type': 'tool_call',
                }
                
                # 2. 添加工具调用消息到执行消息列表
                execution_messages.append(single_tool_call_message)
                
                # 3. 为前端显示生成工具调用消息（包含show_content）
                display_tool_call_message = deepcopy(single_tool_call_message)
                formatted_params = self._format_tool_parameters(tool_call['function']['arguments'])
                display_tool_call_message['show_content'] = f"🔧 **调用工具：{tool_name}**\n\n{formatted_params}\n"
                
                # 4. yield显示消息给前端
                yield [display_tool_call_message]
                
                # 5. 获取工具
                tool = tool_manager.get_tool(tool_name) if tool_manager else None
                if not tool:
                    logger.error(f"ExecutorAgent: 工具 {tool_name} 不存在")
                    yield from self._handle_tool_error(tool_call_id, tool_name, 
                                                     Exception(f"工具 {tool_name} 不存在"))
                    
                    # 添加错误响应到execution_messages
                    error_response_message = {
                        'role': 'tool',
                        'content': f"工具执行错误: 工具 {tool_name} 不存在",
                        'tool_call_id': tool_call_id,
                        'message_id': str(uuid.uuid4()),
                        'type': 'tool_error'
                    }
                    execution_messages.append(error_response_message)
                    continue
                
                # 6. 处理Agent工具
                if isinstance(tool, AgentToolSpec):
                    handoff_message = {
                        'role': 'assistant',
                        'content': f"该任务交接给了{tool.name}，进行执行",
                        'show_content': f"该任务交接给了{tool.name}，进行执行",
                        'message_id': str(uuid.uuid4()),
                        'type': 'handoff_agent',
                    }
                    yield [handoff_message]
                    
                    # Agent工具不需要添加tool响应消息到execution_messages
                    # 因为Agent的输出会通过其他方式处理
                    
                else:
                    # 7. 执行普通工具
                    arguments = json.loads(tool_call['function']['arguments'])
                    tool_response = tool_manager.run_tool(
                        tool_name,
                        messages=execution_messages,
                        session_id=session_id,
                        **arguments
                    )
                    
                    # 8. 处理工具响应
                    if hasattr(tool_response, '__iter__') and not isinstance(tool_response, (str, bytes)):
                        # 流式响应
                        
                        # 收集所有响应内容，最后一起添加到execution_messages
                        all_response_content = []
                        
                        try:
                            for chunk in tool_response:
                                if isinstance(chunk, list):
                                    # 为每个消息添加tool_call_id
                                    for message in chunk:
                                        if isinstance(message, dict):
                                            message['tool_call_id'] = tool_call_id
                                            if 'message_id' not in message:
                                                message['message_id'] = str(uuid.uuid4())
                                            if 'type' not in message:
                                                message['type'] = 'tool_call_result'
                                    yield chunk
                                    # 收集内容用于添加到execution_messages
                                    all_response_content.extend(chunk)
                                else:
                                    # 单个消息
                                    if isinstance(chunk, dict):
                                        chunk['tool_call_id'] = tool_call_id
                                        if 'message_id' not in chunk:
                                            chunk['message_id'] = str(uuid.uuid4())
                                        if 'type' not in chunk:
                                            chunk['type'] = 'tool_call_result'
                                    yield [chunk]
                                    # 收集内容用于添加到execution_messages
                                    all_response_content.append(chunk)
                        except Exception as e:
                            logger.error(f"ExecutorAgent: 处理流式工具响应时发生错误: {str(e)}")
                            yield from self._handle_tool_error(tool_call_id, tool_name, e)
                            
                            # 添加错误响应到execution_messages
                            error_response_message = {
                                'role': 'tool',
                                'content': f"工具执行错误: {str(e)}",
                                'tool_call_id': tool_call_id,
                                'message_id': str(uuid.uuid4()),
                                'type': 'tool_error'
                            }
                            execution_messages.append(error_response_message)
                            continue
                        
                        # 9. 创建工具响应消息并添加到execution_messages
                        if all_response_content:
                            # 合并所有响应内容
                            combined_content = ""
                            for content in all_response_content:
                                if isinstance(content, dict) and 'content' in content:
                                    combined_content += content['content'] + "\n"
                                elif isinstance(content, str):
                                    combined_content += content + "\n"
                            
                            tool_response_message = {
                                'role': 'tool',
                                'content': combined_content.strip(),
                                'tool_call_id': tool_call_id,
                                'message_id': str(uuid.uuid4()),
                                'type': 'tool_response'
                            }
                            execution_messages.append(tool_response_message)
                    else:
                        # 非流式响应
                        logger.info(f"ExecutorAgent: 工具响应 {tool_response}")
                        
                        processed_response = self.process_tool_response(tool_response, tool_call_id)
                        yield processed_response
                        
                        # 添加工具响应消息到execution_messages
                        tool_response_message = {
                            'role': 'tool',
                            'content': str(tool_response),
                            'tool_call_id': tool_call_id,
                            'message_id': str(uuid.uuid4()),
                            'type': 'tool_response',
                            'show_content': str(tool_response)
                        }
                        execution_messages.append(tool_response_message)
                
            except Exception as e:
                logger.error(f"ExecutorAgent: 执行工具 {tool_name} 时发生错误: {str(e)}")
                yield from self._handle_tool_error(tool_call_id, tool_name, e)
                
                # 即使出错也要添加错误响应到execution_messages
                error_response_message = {
                    'role': 'tool',
                    'content': f"工具执行错误: {str(e)}",
                    'tool_call_id': tool_call_id,
                    'message_id': str(uuid.uuid4()),
                    'type': 'tool_error'
                }
                execution_messages.append(error_response_message)
        
        logger.info(f"ExecutorAgent: 完成所有工具调用，执行消息总数: {len(execution_messages)}")

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
        logger.error(f"ExecutorAgent: 工具 {tool_name} 执行错误: {str(error)}")
        
        error_message = f"工具 {tool_name} 执行失败: {str(error)}"
        
        yield [{
            'role': 'tool',
            'content': error_message,
            'tool_call_id': tool_call_id,
            'message_id': str(uuid.uuid4()),
            'type': 'tool_call_result',
            'show_content': f"工具调用失败\n\n"
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
        try:
            tool_response_dict = json.loads(tool_response)
            
            if "content" in tool_response_dict:
                result = [{
                    'role': 'tool',
                    'content': tool_response,
                    'tool_call_id': tool_call_id,
                    'message_id': str(uuid.uuid4()),
                    'type': 'tool_call_result',
                    'show_content': '\n```json\n' + json.dumps(tool_response_dict['content'], ensure_ascii=False, indent=2) + '\n```\n'
                }]
            elif 'messages' in tool_response_dict:
                result = tool_response_dict['messages']
            else:
                # 默认处理
                result = [{
                    'role': 'tool',
                    'content': tool_response,
                    'tool_call_id': tool_call_id,
                    'message_id': str(uuid.uuid4()),
                    'type': 'tool_call_result',
                    'show_content': '\n' + tool_response + '\n'
                }]
            
            return result
            
        except json.JSONDecodeError:
            logger.warning("ExecutorAgent: 处理工具响应时JSON解码错误")
            return [{
                'role': 'tool',
                'content': '\n' + tool_response + '\n',
                'tool_call_id': tool_call_id,
                'message_id': str(uuid.uuid4()),
                'type': 'tool_call_result',
                'show_content': "工具调用失败\n\n"
            }]

    def _get_last_sub_task(self, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        获取最后一个子任务消息
        
        Args:
            messages: 消息列表
            
        Returns:
            Optional[Dict[str, Any]]: 最后一个子任务消息，如果未找到则返回None
        """
        logger.debug(f"ExecutorAgent: 从 {len(messages)} 条消息中查找最后一个子任务")
        
        for i in range(len(messages) - 1, -1, -1):
            if (messages[i]['role'] == 'assistant' and 
                messages[i].get('type') == 'planning_result'):
                logger.debug(f"ExecutorAgent: 在索引 {i} 处找到最后一个子任务")
                return messages[i]
        
        logger.warning("ExecutorAgent: 未找到planning_result类型的消息")
        return None

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[ToolManager] = None,
            session_id: str = None,
            system_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        执行子任务（非流式版本）
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            session_id: 会话ID
            system_context: 系统上下文
            
        Returns:
            List[Dict[str, Any]]: 执行结果消息列表
        """
        logger.info("ExecutorAgent: 执行非流式子任务")
        
        # 调用父类的默认实现，将流式结果合并
        return super().run(
            messages=messages,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        )

    def _format_tool_parameters(self, arguments_str: str) -> str:
        """
        格式化工具参数为美观的 markdown 显示
        
        Args:
            arguments_str: 工具参数的 JSON 字符串
            
        Returns:
            str: 格式化后的 markdown 字符串
        """
        try:
            # 解析参数
            params = json.loads(arguments_str)
            
            if not params:
                return "📝 **参数**: 无"
            
            formatted_lines = ["📝 **参数**:"]
            
            for key, value in params.items():
                # 处理不同类型的参数值
                if isinstance(value, str):
                    # 处理长字符串参数
                    if len(value) > 100:
                        truncated_value = value[:97] + "..."
                        formatted_value = f'"{truncated_value}"'
                    else:
                        formatted_value = f'"{value}"'
                elif isinstance(value, (dict, list)):
                    # 处理复杂对象
                    value_str = json.dumps(value, ensure_ascii=False, indent=2)
                    if len(value_str) > 150:
                        formatted_value = "复杂对象 (已省略详细内容)"
                    else:
                        formatted_value = f"`{value_str}`"
                elif isinstance(value, bool):
                    formatted_value = "✅ 是" if value else "❌ 否"
                elif isinstance(value, (int, float)):
                    formatted_value = f"`{value}`"
                else:
                    formatted_value = f"`{str(value)}`"
                
                formatted_lines.append(f"- **{key}**: {formatted_value}")
            
            return "\n".join(formatted_lines)
            
        except json.JSONDecodeError:
            # 如果无法解析 JSON，直接显示原始字符串
            if len(arguments_str) > 100:
                truncated = arguments_str[:97] + "..."
                return f"📝 **参数**: `{truncated}`"
            else:
                return f"📝 **参数**: `{arguments_str}`"
        except Exception as e:
            logger.warning(f"ExecutorAgent: 格式化工具参数时发生错误: {str(e)}")
            return "📝 **参数**: 解析失败"

    def _extract_recent_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        提取最近一次stage_summary之后的所有消息，并保留user消息
        
        Args:
            messages: 消息列表
            
        Returns:
            List[Dict[str, Any]]: 最近消息列表
        """
        logger.info(f"ExecutorAgent: 从 {len(messages)} 条消息中提取最近消息")
        
        recent_messages = []
        found_last_stage_summary = False
        
        # 从最新的消息开始向前查找
        for index, msg in enumerate(reversed(messages)):
            # 检查是否是stage_summary类型的消息
            if msg.get('type') == 'stage_summary':
                
                # 找到最近一次stage_summary消息，提取该消息之后的所有消息
                # index是从0开始的，所以len(messages) - index - 1是stage_summary消息的位置
                # 我们需要从stage_summary消息的下一条消息开始提取
                start_index = len(messages) - index
                recent_messages = messages[start_index:]
                found_last_stage_summary = True
                logger.info(f"ExecutorAgent: 找到最近一次stage_summary消息，提取之后 {len(recent_messages)} 条消息")
                break
        
        # 如果没有找到stage_summary类型的消息，则提取所有消息
        if not found_last_stage_summary:
            recent_messages = messages
            logger.info(f"ExecutorAgent: 未找到stage_summary类型消息，提取全部 {len(recent_messages)} 条消息")
        
        # 确保包含user消息
        user_messages = [msg for msg in messages if msg.get('role') == 'user']
        if user_messages:
            # 将user消息添加到recent_messages的开头，避免重复
            for user_msg in user_messages:
                if user_msg not in recent_messages:
                    recent_messages.insert(0, user_msg)
            logger.info(f"ExecutorAgent: 添加了 {len(user_messages)} 条user消息")
        
        # 过滤掉task_decomposition类型的消息
        filtered_messages = []
        for msg in recent_messages:
            msg_type = msg.get('type', 'normal')
            if msg_type != 'task_decomposition':
                filtered_messages.append(msg)
            else:
                logger.debug(f"ExecutorAgent: 过滤掉task_decomposition消息")
        
        logger.info(f"ExecutorAgent: 最终提取 {len(filtered_messages)} 条最近消息")
        return filtered_messages