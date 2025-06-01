"""
TaskSummaryAgent 重构版本

任务总结智能体，负责根据原始任务和执行历史生成清晰完整的回答。
改进了代码结构、错误处理、日志记录和可维护性。

作者: Multi-Agent Framework Team
日期: 2024
版本: 2.0 (重构版)
"""

import json
import uuid
import datetime
import traceback
from typing import List, Dict, Any, Optional, Generator

from agents.agent.agent_base import AgentBase
from agents.utils.logger import logger


class TaskSummaryAgent(AgentBase):
    """
    任务总结智能体
    
    负责根据原始任务和执行历史生成清晰完整的回答。
    支持流式输出，实时返回总结结果。
    """

    # 任务总结提示模板常量
    SUMMARY_PROMPT_TEMPLATE = """根据以下任务和执行历史，用自然语言提供清晰完整的回答。
可以使用markdown格式组织内容。

任务: 
{task_description}

执行历史:
{completed_actions}

你的回答应该:
1. 直接回答原始任务。
2. 使用清晰详细的语言，但要保证回答的完整性和准确性，保留执行过程中的关键结果。
3. 如果原始任务的执行过程中，有保存文件并且上传到云端的操作，那么在回答中也应该包含文件的云端地址引用，方便用户下载。
4. 不要引用没有出现在执行历史中的文件。
5. 图表直接使用markdown进行显示。
6. 不是为了总结执行过程，而是以执行过程的信息为基础，生成一个针对用户任务的完美回答。
"""

    # 系统提示模板常量
    SYSTEM_PREFIX_DEFAULT = """你是一个任务总结者，你需要根据原始任务和执行历史，生成清晰完整的回答。"""
    
    # 系统消息模板常量
    SYSTEM_MESSAGE_TEMPLATE = """
你的当前工作目录是：{file_workspace}
当前时间是：{current_time}
你当前数据库_id或者知识库_id：{session_id}
"""

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        """
        初始化任务总结智能体
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        super().__init__(model, model_config, system_prefix)
        self.agent_description = "任务总结智能体，专门负责根据任务和执行历史生成完整回答"
        logger.info("TaskSummaryAgent 初始化完成")

    def run_stream(self, 
                   messages: List[Dict[str, Any]], 
                   tool_manager: Optional[Any] = None,
                   context: Optional[Dict[str, Any]] = None,
                   session_id: str = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式执行任务总结
        
        分析整个任务流程并生成详细总结，实时返回总结结果。
        
        Args:
            messages: 对话历史记录，包含整个任务流程
            tool_manager: 可选的工具管理器
            context: 附加执行上下文
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 流式输出的任务总结消息块
            
        Raises:
            Exception: 当总结过程出现错误时抛出异常
        """
        logger.info(f"TaskSummaryAgent: 开始流式任务总结，消息数量: {len(messages)}")
        
        # 使用基类方法收集和记录流式输出
        yield from self._collect_and_log_stream_output(
            self._execute_summary_stream_internal(messages, tool_manager, context, session_id)
        )

    def _execute_summary_stream_internal(self, 
                                       messages: List[Dict[str, Any]], 
                                       tool_manager: Optional[Any],
                                       context: Optional[Dict[str, Any]],
                                       session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        内部任务总结流式执行方法
        
        Args:
            messages: 对话历史记录，包含整个任务流程
            tool_manager: 可选的工具管理器
            context: 附加执行上下文
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 流式输出的任务总结消息块
        """
        try:
            # 准备总结上下文
            summary_context = self._prepare_summary_context(
                messages=messages,
                context=context,
                session_id=session_id
            )
            
            # 生成总结提示
            prompt = self._generate_summary_prompt(summary_context)
            
            # 执行流式任务总结
            yield from self._execute_streaming_summary(prompt, summary_context)
            
        except Exception as e:
            logger.error(f"TaskSummaryAgent: 任务总结过程中发生异常: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            yield from self._handle_summary_error(e)

    def _prepare_summary_context(self, 
                                messages: List[Dict[str, Any]],
                                context: Optional[Dict[str, Any]],
                                session_id: str) -> Dict[str, Any]:
        """
        准备任务总结所需的上下文信息
        
        Args:
            messages: 对话消息列表
            context: 附加上下文
            session_id: 会话ID
            
        Returns:
            Dict[str, Any]: 包含总结所需信息的上下文字典
        """
        logger.debug("TaskSummaryAgent: 准备任务总结上下文")
        
        # 提取任务描述
        task_description = self._extract_task_description(messages)
        logger.debug(f"TaskSummaryAgent: 提取任务描述，长度: {len(task_description)}")
        
        # 提取完成的操作
        completed_actions = self._extract_completed_actions(messages)
        logger.debug(f"TaskSummaryAgent: 提取完成操作，长度: {len(completed_actions)}")
        
        # 获取上下文信息
        current_time = context.get('current_time', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')) if context else datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        file_workspace = context.get('file_workspace', '无') if context else '无'
        
        summary_context = {
            'task_description': task_description,
            'completed_actions': completed_actions,
            'current_time': current_time,
            'file_workspace': file_workspace,
            'session_id': session_id
        }
        
        logger.info("TaskSummaryAgent: 任务总结上下文准备完成")
        return summary_context

    def _generate_summary_prompt(self, context: Dict[str, Any]) -> str:
        """
        生成任务总结提示
        
        Args:
            context: 总结上下文信息
            
        Returns:
            str: 格式化后的总结提示
        """
        logger.debug("TaskSummaryAgent: 生成任务总结提示")
        
        prompt = self.SUMMARY_PROMPT_TEMPLATE.format(
            task_description=context['task_description'],
            completed_actions=context['completed_actions']
        )
        
        logger.debug("TaskSummaryAgent: 总结提示生成完成")
        return prompt

    def _execute_streaming_summary(self, 
                                 prompt: str, 
                                 summary_context: Dict[str, Any]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行流式任务总结
        
        Args:
            prompt: 总结提示
            summary_context: 总结上下文
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        logger.info("TaskSummaryAgent: 开始执行流式任务总结")
        
        # 准备系统消息
        system_message = self._prepare_system_message_with_context(
            context=summary_context,
            default_prefix=self.SYSTEM_PREFIX_DEFAULT
        )
        
        # 使用基类的流式处理和token跟踪
        yield from self._execute_streaming_with_token_tracking(
            prompt=prompt,
            step_name="task_summary",
            system_message=system_message,
            message_type='final_answer'
        )

    def _handle_summary_error(self, error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理总结过程中的错误
        
        Args:
            error: 发生的异常
            
        Yields:
            List[Dict[str, Any]]: 错误消息块
        """
        yield from self._handle_error_generic(
            error=error,
            error_context="任务总结",
            message_type='final_answer'
        )

    def _extract_task_description(self, messages: List[Dict[str, Any]]) -> str:
        """
        从消息中提取原始任务描述
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 任务描述字符串
        """
        logger.debug(f"TaskSummaryAgent: 处理 {len(messages)} 条消息以提取任务描述")
        
        task_description_messages = self._extract_task_description_messages(messages)
        result = self.convert_messages_to_str(task_description_messages)
        
        logger.debug(f"TaskSummaryAgent: 生成任务描述，长度: {len(result)}")
        return result

    def _extract_completed_actions(self, messages: List[Dict[str, Any]]) -> str:
        """
        从消息中提取已完成的操作
        
        Args:
            messages: 消息列表
            
        Returns:
            str: 已完成操作的字符串
        """
        logger.debug(f"TaskSummaryAgent: 处理 {len(messages)} 条消息以提取完成操作")
        
        completed_actions_messages = self._extract_completed_actions_messages(messages)
        result = self.convert_messages_to_str(completed_actions_messages)
        
        logger.debug(f"TaskSummaryAgent: 生成完成操作，长度: {len(result)}")
        return result

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            context: Optional[Dict[str, Any]] = None,
            session_id: str = None) -> List[Dict[str, Any]]:
        """
        执行任务总结（非流式版本）
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            context: 附加上下文信息
            session_id: 会话ID
            
        Returns:
            List[Dict[str, Any]]: 任务总结结果消息列表
        """
        logger.info("TaskSummaryAgent: 执行非流式任务总结")
        
        # 调用父类的默认实现，将流式结果合并
        return super().run(
            messages=messages,
            tool_manager=tool_manager,
            context=context,
            session_id=session_id
        )
        