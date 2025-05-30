"""
ExecutorAgent 重构版本

执行智能体，负责使用工具或LLM直接执行子任务。
改进了代码结构、错误处理、日志记录和可维护性。

作者: Multi-Agent Framework Team
日期: 2024
版本: 2.0 (重构版)
"""

import json
import datetime
import traceback
import uuid
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
    TASK_EXECUTION_PROMPT_TEMPLATE = """Do the following subtask:{next_subtask_description}.
the expected output is:{next_expected_output}

注意以下的任务执行规则：
1. 如果不需要使用工具，直接返回中文内容。你的文字输出都要是markdown格式。
2. 如果是要生成计划、方案、内容创作，代码等大篇幅文字，请使用file_write函数工具将内容分多次保存到文件中，文件内容是函数的参数，格式使用markdown。
3. 如果需要编写代码，请使用file_write函数工具，代码内容是函数的参数。
4. 如果是输出报告或者总结，请使用file_write函数工具，报告内容是函数的参数，格式使用markdown。
5. 只能在工作目录下读写文件。如果用户没有提供文件路径，你应该在这个目录下创建一个新文件。
6. 调用工具时，不要在其他的输出文字,你一次只能执行一个任务。
7. 输出的文字中不要暴露你的工作目录，id信息以及你的工具名称。
8. 如果使用file_write创建文件，一定要在工作目录下创建文件，要求文件路径是绝对路径。
"""

    # 系统提示模板常量
    SYSTEM_PREFIX_DEFAULT = """你是个任务执行助手，你需要根据任务描述，执行任务。"""
    
    # 系统消息模板常量
    SYSTEM_MESSAGE_TEMPLATE = """
你的当前工作目录是：{file_workspace}
当前时间是：{current_time}
你当前数据库_id或者知识库_id：{session_id}
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
                   messages: List[Dict[str, Any]], 
                   tool_manager: Optional[ToolManager] = None,
                   context: Optional[Dict[str, Any]] = None,
                   session_id: str = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式执行子任务
        
        使用工具调用或直接LLM生成来执行子任务并实时返回执行结果。
        
        Args:
            messages: 包含子任务的对话历史记录
            tool_manager: 用于执行基于工具的子任务的工具管理器
            context: 附加执行上下文
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 流式输出的执行结果消息块
            
        Raises:
            Exception: 当执行过程出现错误时抛出异常
        """
        logger.info(f"ExecutorAgent: 开始流式执行，会话ID: {session_id}")
        
        if not messages:
            logger.warning("ExecutorAgent: 未提供消息，返回空列表")
            return
        
        try:
            # 准备执行上下文
            execution_context = self._prepare_execution_context(
                messages=messages,
                context=context,
                session_id=session_id
            )
            
            # 解析子任务信息
            subtask_info = self._parse_subtask_info(messages)
            
            # 生成执行提示并准备消息
            execution_messages = self._prepare_execution_messages(
                messages=messages,
                subtask_info=subtask_info,
                execution_context=execution_context
            )
            
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
                                 context: Optional[Dict[str, Any]],
                                 session_id: str) -> Dict[str, Any]:
        """
        准备执行所需的上下文信息
        
        Args:
            messages: 对话消息列表
            context: 附加上下文
            session_id: 会话ID
            
        Returns:
            Dict[str, Any]: 包含执行所需信息的上下文字典
        """
        logger.debug("ExecutorAgent: 准备执行上下文")
        
        # 提取相关消息
        task_description_messages = self._extract_task_description_messages(messages)
        completed_actions_messages = self._extract_completed_actions_messages(messages)
        
        # 获取上下文信息
        current_time = context.get('current_time', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')) if context else datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        file_workspace = context.get('file_workspace', '无') if context else '无'
        
        execution_context = {
            'task_description_messages': task_description_messages,
            'completed_actions_messages': completed_actions_messages,
            'current_time': current_time,
            'file_workspace': file_workspace,
            'session_id': session_id
        }
        
        logger.info("ExecutorAgent: 执行上下文准备完成")
        return execution_context

    def _parse_subtask_info(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        解析子任务信息
        
        Args:
            messages: 消息列表
            
        Returns:
            Dict[str, Any]: 解析后的子任务信息
            
        Raises:
            json.JSONDecodeError: 当无法解析子任务消息时抛出
        """
        logger.debug("ExecutorAgent: 解析子任务信息")
        
        try:
            last_subtask_message = self._get_last_sub_task(messages)
            if not last_subtask_message:
                raise ValueError("未找到planning_result类型的消息")
            
            # 解析子任务内容
            content = last_subtask_message['content']
            if content.startswith('Planning: '):
                content = content[len('Planning: '):]
            
            subtask_dict = json.loads(content.strip('```json\\n').strip('```'))
            
            subtask_info = {
                'description': subtask_dict['next_step']['description'],
                'expected_output': subtask_dict['next_step']['expected_output'],
                'required_tools': subtask_dict['next_step'].get('required_tools', [])
            }
            
            logger.info(f"ExecutorAgent: 解析子任务成功 - {subtask_info['description']}")
            logger.debug(f"ExecutorAgent: 需要的工具: {subtask_info['required_tools']}")
            
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
        logger.debug("ExecutorAgent: 准备执行消息")
        
        # 准备系统消息
        system_message = self._prepare_system_message(execution_context)
        
        # 深拷贝消息
        messages_input = deepcopy(messages)
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
        
        logger.debug(f"ExecutorAgent: 准备了 {len(messages_input)} 条执行消息")
        return messages_input

    def _prepare_system_message(self, execution_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        准备系统消息
        
        Args:
            execution_context: 执行上下文
            
        Returns:
            Dict[str, Any]: 系统消息字典
        """
        logger.debug("ExecutorAgent: 准备系统消息")
        
        # 设置默认系统前缀
        if len(self.system_prefix) == 0:
            self.system_prefix = self.SYSTEM_PREFIX_DEFAULT
        
        # 构建系统消息
        system_content = self.system_prefix + self.SYSTEM_MESSAGE_TEMPLATE.format(
            session_id=execution_context['session_id'],
            current_time=execution_context['current_time'],
            file_workspace=execution_context['file_workspace']
        )
        
        system_message = {
            'role': 'system',
            'content': system_content
        }
        
        logger.info(f"ExecutorAgent: 系统消息准备完成")
        return system_message

    def _send_task_execution_prompt(self, subtask_info: Dict[str, Any]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        发送任务执行提示消息
        
        Args:
            subtask_info: 子任务信息
            
        Yields:
            List[Dict[str, Any]]: 任务执行提示消息块
        """
        logger.debug("ExecutorAgent: 发送任务执行提示")
        
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
                               tool_manager: Optional[ToolManager],
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
        logger.debug(f"ExecutorAgent: 准备了 {len(clean_messages)} 条清理后的消息")
        
        # 准备工具
        tools_json = self._prepare_tools(tool_manager, subtask_info)
        
        # 调用LLM
        response = self._call_llm_with_tools(clean_messages, tools_json)
        
        # 处理流式响应
        yield from self._process_streaming_response(
            response=response,
            tool_manager=tool_manager,
            execution_messages=execution_messages,
            session_id=session_id
        )

    def _prepare_tools(self, 
                      tool_manager: Optional[ToolManager], 
                      subtask_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        准备工具列表
        
        Args:
            tool_manager: 工具管理器
            subtask_info: 子任务信息
            
        Returns:
            List[Dict[str, Any]]: 工具配置列表
        """
        logger.debug("ExecutorAgent: 准备工具列表")
        
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
                           tools_json: List[Dict[str, Any]]):
        """
        调用LLM并支持工具调用
        
        Args:
            messages: 消息列表
            tools_json: 工具配置列表
            
        Returns:
            Generator: LLM流式响应
        """
        logger.debug("ExecutorAgent: 调用LLM进行工具辅助执行")
        
        return self.model.chat.completions.create(
            tools=tools_json if tools_json else None,
            messages=messages,
            stream=True,
            **self.model_config
        )

    def _process_streaming_response(self, 
                                  response,
                                  tool_manager: Optional[ToolManager],
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
        logger.debug("ExecutorAgent: 处理流式响应")
        
        tool_calls = {}
        unused_tool_content_message_id = str(uuid.uuid4())
        last_tool_call_id = None
        
        # 处理流式响应
        for chunk in response:
            if chunk.choices[0].delta.tool_calls:
                yield from self._handle_tool_calls_chunk(
                    chunk=chunk,
                    tool_calls=tool_calls,
                    last_tool_call_id=last_tool_call_id
                )
                # 更新last_tool_call_id
                for tool_call in chunk.choices[0].delta.tool_calls:
                    if tool_call.id and len(tool_call.id) > 0:
                        last_tool_call_id = tool_call.id
                        
            elif chunk.choices[0].delta.content:
                if tool_calls:
                    # 有工具调用时停止收集文本内容
                    logger.debug(f"ExecutorAgent: 检测到 {len(tool_calls)} 个工具调用，停止收集文本内容")
                    break
                
                yield [{
                    'role': 'assistant',
                    'content': chunk.choices[0].delta.content,
                    'type': 'do_subtask_result',
                    'message_id': unused_tool_content_message_id,
                    'show_content': chunk.choices[0].delta.content
                }]
        
        # 处理工具调用或发送结束消息
        if tool_calls:
            yield from self._execute_tool_calls(
                tool_calls=tool_calls,
                tool_manager=tool_manager,
                execution_messages=execution_messages,
                session_id=session_id
            )
        else:
            # 发送结束消息
            yield [{
                'role': 'assistant',
                'content': '',
                'type': 'do_subtask_result',
                'message_id': unused_tool_content_message_id,
                'show_content': '\\n'
            }]

    def _handle_tool_calls_chunk(self, 
                               chunk,
                               tool_calls: Dict[str, Any],
                               last_tool_call_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理工具调用数据块
        
        Args:
            chunk: LLM响应块
            tool_calls: 工具调用字典
            last_tool_call_id: 最后的工具调用ID
            
        Yields:
            List[Dict[str, Any]]: 处理结果（通常为空）
        """
        for tool_call in chunk.choices[0].delta.tool_calls:
            if tool_call.id and len(tool_call.id) > 0:
                last_tool_call_id = tool_call.id
                
            if last_tool_call_id not in tool_calls:
                logger.debug(f"ExecutorAgent: 检测到新工具调用: {last_tool_call_id}, 工具名称: {tool_call.function.name}")
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
                    tool_calls[last_tool_call_id]['function']['name'] = tool_call.function.name
                if tool_call.function.arguments:
                    tool_calls[last_tool_call_id]['function']['arguments'] += tool_call.function.arguments
        
        # 通常不需要yield任何内容
        return
        yield []

    def _execute_tool_calls(self, 
                          tool_calls: Dict[str, Any],
                          tool_manager: Optional[ToolManager],
                          execution_messages: List[Dict[str, Any]],
                          session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行工具调用
        
        Args:
            tool_calls: 工具调用字典
            tool_manager: 工具管理器
            execution_messages: 执行消息列表
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 工具执行结果消息块
        """
        logger.info(f"ExecutorAgent: 执行 {len(tool_calls)} 个工具调用")
        
        for tool_call_id, tool_call in tool_calls.items():
            tool_name = tool_call['function']['name']
            logger.info(f"ExecutorAgent: 执行工具 {tool_name}")
            
            try:
                # 检查工具是否存在
                tool = tool_manager.get_tool(tool_name) if tool_manager else None
                if not tool:
                    logger.error(f"ExecutorAgent: 工具 {tool_name} 未找到")
                    continue
                
                # 处理Agent工具
                if isinstance(tool, AgentToolSpec):
                    yield [{
                        'role': 'assistant',
                        'content': f"该任务交接给了{tool.name}，进行执行",
                        'show_content': f"该任务交接给了{tool.name}，进行执行",
                        'message_id': str(uuid.uuid4()),
                        'type': 'tool_call',
                    }]
                else:
                    # 发送工具调用消息
                    yield [{
                        'role': 'assistant',
                        'tool_calls': [{
                            'id': tool_call['id'],
                            'type': tool_call['type'],
                            'function': {
                                'name': tool_call['function']['name'],
                                'arguments': tool_call['function']['arguments']
                            }
                        }],
                        'type': 'tool_call',
                        'message_id': str(uuid.uuid4()),
                        'show_content': f"调用工具：{tool_name}\\n\\n"
                    }]
                
                # 解析并执行工具
                arguments = json.loads(tool_call['function']['arguments'])
                tool_response = tool_manager.run_tool(
                    tool_name,
                    messages=execution_messages,
                    session_id=session_id,
                    **arguments
                )
                
                # 处理工具响应
                logger.debug("ExecutorAgent: 收到工具响应，正在处理")
                logger.info(f"ExecutorAgent: 工具响应 {tool_response}")
                
                processed_response = self.process_tool_response(tool_response, tool_call_id)
                yield processed_response
                
            except Exception as e:
                logger.error(f"ExecutorAgent: 执行工具 {tool_name} 时发生错误: {str(e)}")
                yield from self._handle_tool_error(tool_call_id, tool_name, e)

    def _handle_execution_error(self, error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理执行过程中的错误
        
        Args:
            error: 发生的异常
            
        Yields:
            List[Dict[str, Any]]: 错误消息块
        """
        logger.error(f"ExecutorAgent: 处理执行错误: {str(error)}")
        
        error_message = f"\\n任务执行失败: {str(error)}"
        message_id = str(uuid.uuid4())
        
        yield [{
            'role': 'tool',
            'content': error_message,
            'type': 'do_subtask_result',
            'message_id': message_id,
            'show_content': error_message
        }]

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
            'show_content': f"工具调用失败\\n\\n"
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
        logger.debug(f"ExecutorAgent: 处理工具响应，工具调用ID: {tool_call_id}")
        
        try:
            tool_response_dict = json.loads(tool_response)
            
            if "content" in tool_response_dict:
                result = [{
                    'role': 'tool',
                    'content': tool_response,
                    'tool_call_id': tool_call_id,
                    'message_id': str(uuid.uuid4()),
                    'type': 'tool_call_result',
                    'show_content': '\\n```json\\n' + json.dumps(tool_response_dict['content'], ensure_ascii=False, indent=2) + '\\n```\\n'
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
                    'show_content': '\\n' + tool_response + '\\n'
                }]
            
            logger.debug("ExecutorAgent: 工具响应处理成功")
            return result
            
        except json.JSONDecodeError:
            logger.warning("ExecutorAgent: 处理工具响应时JSON解码错误")
            return [{
                'role': 'tool',
                'content': '\\n' + tool_response + '\\n',
                'tool_call_id': tool_call_id,
                'message_id': str(uuid.uuid4()),
                'type': 'tool_call_result',
                'show_content': "工具调用失败\\n\\n"
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
            context: Optional[Dict[str, Any]] = None,
            session_id: str = None) -> List[Dict[str, Any]]:
        """
        执行任务（非流式版本）
        
        Args:
            messages: 对话历史记录
            tool_manager: 工具管理器
            context: 附加上下文信息
            session_id: 会话ID
            
        Returns:
            List[Dict[str, Any]]: 任务执行结果消息列表
        """
        logger.info("ExecutorAgent: 执行非流式任务执行")
        
        # 调用父类的默认实现，将流式结果合并
        return super().run(
            messages=messages,
            tool_manager=tool_manager,
            context=context,
            session_id=session_id
        )