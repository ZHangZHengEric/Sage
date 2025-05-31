"""
TaskDecomposeAgent 重构版本

任务分解智能体，负责将复杂任务分解为可执行的子任务。
改进了代码结构、错误处理、日志记录和可维护性。

作者: Multi-Agent Framework Team
日期: 2024
版本: 2.0 (重构版)
"""

import json
import uuid
import re
import datetime
import traceback
import time
from typing import List, Dict, Any, Optional, Generator

from agents.agent.agent_base import AgentBase
from agents.utils.logger import logger


class TaskDecomposeAgent(AgentBase):
    """
    任务分解智能体
    
    负责将复杂的用户需求分解为清晰可执行的子任务。
    支持流式输出，实时返回分解过程。
    """

    # 任务分解提示模板常量
    DECOMPOSITION_PROMPT_TEMPLATE = """# 任务分解指南

## 用户需求
{task_description}

## 分解要求
1. 将复杂需求分解为清晰可执行的子任务
2. 确保每个子任务都是原子性的
3. 考虑任务之间的依赖关系，输出的列表必须是有序的，按照优先级从高到低排序，优先级相同的任务按照依赖关系排序
4. 输出格式必须严格遵守以下要求
5. 如果有任务Thinking的过程，子任务要与Thinking的处理逻辑一致
6. 子任务数量不要超过10个，较简单的子任务可以合并为一个子任务

## 输出格式
```
<task_item>
子任务1描述
</task_item>
<task_item>
子任务2描述
</task_item>
```
"""

    # 系统提示模板常量
    SYSTEM_PREFIX_DEFAULT = """你是一个任务分解者，你需要根据用户需求，将复杂任务分解为清晰可执行的子任务。"""
    
    # 系统消息模板常量
    SYSTEM_MESSAGE_TEMPLATE = """
你的当前工作目录是：{file_workspace}
当前时间是：{current_time}
你当前数据库_id或者知识库_id：{session_id}
"""

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        """
        初始化任务分解智能体
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        super().__init__(model, model_config, system_prefix)
        self.agent_description = "任务分解智能体，专门负责将复杂任务分解为可执行的子任务"
        logger.info("TaskDecomposeAgent 初始化完成")
    
    def run_stream(self, 
                   messages: List[Dict[str, Any]], 
                   tool_manager: Optional[Any] = None,
                   context: Optional[Dict[str, Any]] = None,
                   session_id: str = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式执行任务分解
        
        将复杂任务分解为清晰可执行的子任务并实时返回分解结果。
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            context: 附加上下文信息
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 流式输出的任务分解消息块
            
        Raises:
            Exception: 当分解过程出现错误时抛出异常
        """
        logger.info("TaskDecomposeAgent: 开始流式任务分解")
        
        # 使用基类方法收集和记录流式输出
        yield from self._collect_and_log_stream_output(
            self._execute_decompose_stream_internal(messages, tool_manager, context, session_id)
        )

    def _execute_decompose_stream_internal(self, 
                                         messages: List[Dict[str, Any]], 
                                         tool_manager: Optional[Any],
                                         context: Optional[Dict[str, Any]],
                                         session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        内部任务分解流式执行方法
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            context: 附加上下文信息
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 流式输出的任务分解消息块
        """
        try:
            # 准备分解上下文
            decomposition_context = self._prepare_decomposition_context(
                messages=messages,
                context=context,
                session_id=session_id
            )
            
            # 生成分解提示
            prompt = self._generate_decomposition_prompt(decomposition_context)
            
            # 执行流式任务分解
            yield from self._execute_streaming_decomposition(decomposition_context)
            
        except Exception as e:
            logger.error(f"TaskDecomposeAgent: 任务分解过程中发生异常: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            yield from self._handle_decomposition_error(e)

    def _prepare_decomposition_context(self, 
                                     messages: List[Dict[str, Any]],
                                     context: Optional[Dict[str, Any]],
                                     session_id: str) -> Dict[str, Any]:
        """
        准备任务分解所需的上下文信息
        
        Args:
            messages: 对话消息列表
            context: 附加上下文
            session_id: 会话ID
            
        Returns:
            Dict[str, Any]: 包含任务分解所需信息的上下文字典
        """
        logger.debug("TaskDecomposeAgent: 准备任务分解上下文")
        
        # 提取任务描述
        task_description_messages = self._extract_task_description_messages(messages)
        task_description_str = self.convert_messages_to_str(task_description_messages)
        
        logger.debug(f"TaskDecomposeAgent: 提取任务描述，消息数量: {len(task_description_messages)}")
        
        decomposition_context = {
            'task_description': task_description_str,
            'session_id': session_id,
            'context': context
        }
        
        logger.info("TaskDecomposeAgent: 任务分解上下文准备完成")
        return decomposition_context

    def _generate_decomposition_prompt(self, context: Dict[str, Any]) -> str:
        """
        生成任务分解提示
        
        Args:
            context: 任务分解上下文信息
            
        Returns:
            str: 格式化后的任务分解提示
        """
        logger.debug("TaskDecomposeAgent: 生成任务分解提示")
        
        prompt = self.DECOMPOSITION_PROMPT_TEMPLATE.format(
            task_description=context['task_description']
        )
        
        logger.debug("TaskDecomposeAgent: 任务分解提示生成完成")
        return prompt

    def _execute_streaming_decomposition(self, 
                                        decomposition_context: Dict[str, Any]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行流式任务分解
        
        Args:
            decomposition_context: 分解上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        logger.info("TaskDecomposeAgent: 开始执行流式任务分解")
        
        # 准备系统消息和提示
        system_message = self._prepare_system_message(
            decomposition_context.get('context'), 
            decomposition_context['session_id']
        )
        prompt = self._generate_decomposition_prompt(decomposition_context)
        
        # 准备LLM输入
        messages = self._prepare_llm_messages(system_message, prompt)
        
        # 使用基类的流式处理和token跟踪
        message_id = str(uuid.uuid4())
        chunk_count = 0
        full_response = ""
        
        # 收集流式响应内容
        start_time = time.time()
        chunks = []
        
        # 状态管理
        unknown_content = ''
        last_tag_type = 'tag'
        
        for chunk in self._call_llm_streaming(messages):
            chunks.append(chunk)
            if len(chunk.choices) == 0:
                continue
            if chunk.choices[0].delta.content:
                delta_content = chunk.choices[0].delta.content
                
                for delta_content_char in delta_content:
                    delta_content_all = unknown_content+ delta_content_char
                    delta_content_type = self._judge_delta_content_type(delta_content_all, full_response, ['task_item'])
                    
                    full_response += delta_content_char
                    chunk_count += 1
                    show_delta_content = ''
                    if delta_content_type == 'unknown':
                        unknown_content = delta_content_all
                        continue
                    else:
                        unknown_content = ''
                        if delta_content_type == 'task_item':
                            if last_tag_type != 'task_item':
                                yield self._create_message_chunk(
                                    content=delta_content_char,
                                    message_id=message_id,
                                    show_content='\n- ',
                                    message_type='task_decomposition'
                                )
                            
                            yield self._create_message_chunk(
                                content=delta_content_char,
                                message_id=message_id,
                                show_content=delta_content_all,
                                message_type='task_decomposition'
                            )
                        last_tag_type = delta_content_type
                                
                                
        # 跟踪token使用
        self._track_streaming_token_usage(chunks, "task_decomposition", start_time)
        
        logger.info(f"TaskDecomposeAgent: 流式分解完成，共生成 {chunk_count} 个文本块")
        
        # 处理最终结果
        yield from self._finalize_decomposition_result(full_response, message_id)

    def _prepare_system_message(self, 
                              context: Optional[Dict[str, Any]], 
                              session_id: str) -> Dict[str, Any]:
        """
        准备系统消息
        
        Args:
            context: 附加上下文
            session_id: 会话ID
            
        Returns:
            Dict[str, Any]: 系统消息字典
        """
        logger.debug("TaskDecomposeAgent: 准备系统消息")
        
        # 设置默认系统前缀
        if len(self.system_prefix) == 0:
            self.system_prefix = self.SYSTEM_PREFIX_DEFAULT
        
        # 获取上下文信息
        current_time = context.get('current_time', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')) if context else datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        file_workspace = context.get('file_workspace', '无') if context else '无'
        
        # 构建系统消息
        system_content = self.system_prefix + self.SYSTEM_MESSAGE_TEMPLATE.format(
            session_id=session_id,
            current_time=current_time,
            file_workspace=file_workspace
        )
        
        return {
            'role': 'system',
            'content': system_content
        }

    def _prepare_llm_messages(self, 
                            system_message: Dict[str, Any], 
                            prompt: str) -> List[Dict[str, Any]]:
        """
        准备LLM输入消息
        
        Args:
            system_message: 系统消息
            prompt: 用户提示
            
        Returns:
            List[Dict[str, Any]]: LLM输入消息列表
        """
        logger.debug("TaskDecomposeAgent: 准备LLM输入消息")
        
        user_message = {
            'role': 'user',
            'content': prompt
        }
        
        return [system_message, user_message]

    def _finalize_decomposition_result(self, 
                                     full_response: str, 
                                     message_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        完成任务分解并返回最终结果
        
        Args:
            full_response: 完整的响应内容
            message_id: 消息ID
            
        Yields:
            List[Dict[str, Any]]: 最终任务分解结果消息块
        """
        logger.debug("TaskDecomposeAgent: 处理最终任务分解结果")
        
        try:
            # 解析任务列表
            tasks = self._convert_xlm_to_json(full_response)
            logger.info(f"TaskDecomposeAgent: 成功分解为 {len(tasks)} 个子任务")
            
            # 返回最终结果
            result_content = '任务拆解规划：\n' + json.dumps({"tasks": tasks}, ensure_ascii=False)
            
            result_message = {
                'role': 'assistant',
                'content': result_content,
                'type': 'task_decomposition',
                'message_id': message_id,
                'show_content': ''
            }
            
            yield [result_message]
            
        except Exception as e:
            logger.error(f"TaskDecomposeAgent: 处理最终结果时发生错误: {str(e)}")
            yield from self._handle_decomposition_error(e)

    def _handle_decomposition_error(self, error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理任务分解过程中的错误
        
        Args:
            error: 发生的异常
            
        Yields:
            List[Dict[str, Any]]: 错误消息块
        """
        yield from self._handle_error_generic(
            error=error,
            error_context="任务分解",
            message_type='task_decomposition'
        )

    def _convert_xlm_to_json(self, content: str) -> List[Dict[str, Any]]:
        """
        将任务列表从XML格式转换为JSON格式
        
        Args:
            content: XML格式的内容字符串
            
        Returns:
            List[Dict[str, Any]]: 转换后的任务列表
            
        Example:
            输入XML格式：
            <task_item>任务1描述</task_item>
            <task_item>任务2描述</task_item>
            
            输出JSON格式：
            [
                {"description": "任务1描述"},
                {"description": "任务2描述"}
            ]
        """
        logger.debug("TaskDecomposeAgent: 转换XML内容为JSON格式")
        
        try:
            tasks = []
            task_items = re.findall(r'<task_item>(.*?)</task_item>', content, re.DOTALL)

            for item in task_items:
                task = {
                    "description": item.strip(),
                }
                tasks.append(task)

            logger.debug(f"TaskDecomposeAgent: XML转JSON完成，共提取 {len(tasks)} 个任务")
            return tasks
            
        except Exception as e:
            logger.error(f"TaskDecomposeAgent: XML转JSON失败: {str(e)}")
            raise

    def _extract_tasks_from_response(self, content: str) -> List[Dict[str, Any]]:
        """
        从LLM响应中提取任务列表（备用方法）
        
        Args:
            content: LLM响应内容
            
        Returns:
            List[Dict[str, Any]]: 提取的任务列表
        """
        logger.debug("TaskDecomposeAgent: 从响应中提取任务列表")
        
        try:
            # 尝试从markdown代码块中提取JSON
            json_str = self._extract_json_from_markdown(content)
            
            # 尝试解析为JSON
            tasks_data = json.loads(json_str)
            
            if isinstance(tasks_data, dict) and "tasks" in tasks_data:
                logger.debug(f"TaskDecomposeAgent: 从字典格式提取任务，数量: {len(tasks_data['tasks'])}")
                return tasks_data["tasks"]
            elif isinstance(tasks_data, list):
                logger.debug(f"TaskDecomposeAgent: 从列表格式提取任务，数量: {len(tasks_data)}")
                return tasks_data
            else:
                logger.warning("TaskDecomposeAgent: 响应中的任务格式不符合预期")
                return []
                
        except json.JSONDecodeError as e:
            logger.error(f"TaskDecomposeAgent: 从响应中解析任务失败: {str(e)}")
            return []

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            context: Optional[Dict[str, Any]] = None,
            session_id: str = None) -> List[Dict[str, Any]]:
        """
        执行任务分解（非流式版本）
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            context: 附加上下文信息
            session_id: 会话ID
            
        Returns:
            List[Dict[str, Any]]: 任务分解结果消息列表
        """
        logger.info("TaskDecomposeAgent: 执行非流式任务分解")
        
        # 调用父类的默认实现，将流式结果合并
        return super().run(
            messages=messages,
            tool_manager=tool_manager,
            context=context,
            session_id=session_id
        )