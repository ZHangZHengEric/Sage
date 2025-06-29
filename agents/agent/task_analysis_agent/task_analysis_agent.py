"""
TaskAnalysisAgent 重构版本

任务分析智能体，负责分析任务并将其分解为组件。
改进了代码结构、错误处理、日志记录和可维护性。

作者: Eric ZZ
版本: 2.0 (重构版)
"""

import json
import uuid
import datetime
import traceback
from typing import List, Dict, Any, Optional, Generator

from agents.agent.agent_base import AgentBase
from agents.utils.logger import logger


class TaskAnalysisAgent(AgentBase):
    """
    任务分析智能体
    
    负责分析任务并将其分解为组件，理解用户的核心需求。
    支持流式输出，实时返回分析过程。
    """

    # 任务分析提示模板常量
    ANALYSIS_PROMPT_TEMPLATE = """请仔细分析以下对话，并以自然流畅的语言解释你的思考过程：
对话记录：
{conversation}

当前有以下的工具可以使用：
{available_tools}



请按照以下步骤进行分析：
首先，我需要理解用户的核心需求。从对话中可以提取哪些关键信息？用户真正想要实现的目标是什么？

接下来，我会逐步分析这个任务。具体来说，需要考虑以下几个方面：
- 任务的背景和上下文
- 需要解决的具体问题 
- 可能涉及的数据或信息来源 
- 潜在的解决方案路径

在分析过程中，我会思考：
- 哪些信息是已知的、可以直接使用的
- 哪些信息需要进一步验证或查找
- 可能存在的限制或挑战
- 最优的解决策略是什么

最后，我会用清晰、自然的语言总结分析结果，包括：
- 对任务需求的详细解释
- 具体的解决步骤和方法
- 需要特别注意的关键点
- 任何可能的备选方案

请用完整的段落形式表达你的分析，就像在向同事解释你的思考过程一样自然流畅。直接输出分析，不要添加额外的解释或注释，以及质问用户。尽可能口语化。不要说出工具的原始名称以及数据库或者知识库的ID。
当前时间是 {current_datatime_str}
"""

    # 系统提示模板常量
    SYSTEM_PREFIX_DEFAULT = """你是一个任务分析智能体，专门负责分析任务并将其分解为组件。请仔细理解用户需求，提供清晰、自然的分析过程。"""
    
    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
        """
        初始化任务分析智能体
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
        """
        super().__init__(model, model_config, system_prefix)
        self.agent_name = "TaskAnalysisAgent"
        self.agent_description = "任务分析智能体，专门负责分析任务并将其分解为组件"
        logger.info("TaskAnalysisAgent 初始化完成")

    def run_stream(self, 
                   message_manager: Any,
                   task_manager: Optional[Any] = None,
                   tool_manager: Optional[Any] = None,
                   session_id: Optional[str] = None,
                   system_context: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        流式执行任务分析
        
        分析用户输入并提取关键信息，实时返回分析结果。
        
        Args:
            message_manager: 消息管理器（必需）
            task_manager: 任务管理器
            tool_manager: 可选的工具管理器
            session_id: 会话ID
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Yields:
            List[Dict[str, Any]]: 流式输出的任务分析消息块
            
        Raises:
            Exception: 当分析过程出现错误时抛出异常
        """
        if not message_manager:
            raise ValueError("TaskAnalysisAgent: message_manager 是必需参数")
        
        # 从MessageManager获取优化后的消息
        optimized_messages = message_manager.filter_messages_for_agent(self.__class__.__name__)
        logger.info(f"TaskAnalysisAgent: 开始流式任务分析，获取到 {len(optimized_messages)} 条优化消息")
        message_manager.log_print_messages(optimized_messages)
        
        # 使用基类方法收集和记录流式输出，并将结果添加到MessageManager
        for chunk_batch in self._collect_and_log_stream_output(
            self._execute_analysis_stream_internal(optimized_messages, tool_manager, session_id, system_context, task_manager)
        ):
            # Agent自己负责将生成的消息添加到MessageManager
            message_manager.add_messages(chunk_batch, agent_name="TaskAnalysisAgent")
            yield chunk_batch

    def _execute_analysis_stream_internal(self, 
                                        messages: List[Dict[str, Any]], 
                                        tool_manager: Optional[Any],
                                        session_id: str,
                                        system_context: Optional[Dict[str, Any]],
                                        task_manager: Optional[Any] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        内部任务分析流式执行方法
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            session_id: 会话ID
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Yields:
            List[Dict[str, Any]]: 流式输出的任务分析消息块
        """
        try:
            # 准备分析上下文
            analysis_context = self._prepare_analysis_context(
                messages=messages,
                tool_manager=tool_manager,
                session_id=session_id,
                system_context=system_context
            )
            
            # 生成分析提示
            prompt = self._generate_analysis_prompt(analysis_context)
            
            # 执行流式任务分析
            yield from self._execute_streaming_analysis(prompt, analysis_context)
            
        except Exception as e:
            logger.error(f"TaskAnalysisAgent: 任务分析过程中发生异常: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            yield from self._handle_analysis_error(e)

    def _prepare_analysis_context(self, 
                                messages: List[Dict[str, Any]],
                                tool_manager: Optional[Any],
                                session_id: str,
                                system_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        准备任务分析所需的上下文信息
        
        Args:
            messages: 对话消息列表
            tool_manager: 工具管理器
            session_id: 会话ID
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Returns:
            Dict[str, Any]: 包含分析所需信息的上下文字典
        """
        logger.debug("TaskAnalysisAgent: 准备任务分析上下文")
        
        # 提取任务描述对话
        conversation_messages = self._extract_task_description_messages(messages)
        conversation = self.convert_messages_to_str(conversation_messages)
        logger.info(f"TaskAnalysisAgent: 准备了长度为 {len(conversation)} 的对话上下文")
        
        # 获取可用工具
        available_tools = tool_manager.list_tools_simplified() if tool_manager else []
        # 只提取工具名称，不显示描述
        tool_names = [tool['name'] for tool in available_tools]
        available_tools_str = ", ".join(tool_names) if tool_names else "无可用工具"
        logger.debug(f"TaskAnalysisAgent: 可用工具数量: {len(available_tools)}")
        
        # 获取当前时间（从system_context或生成默认值）
        current_datatime_str = system_context.get('current_time') if system_context else datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        analysis_context = {
            'conversation': conversation,
            'available_tools': available_tools_str,
            'current_datatime_str': current_datatime_str,
            'session_id': session_id,
            'system_context': system_context
        }
        
        logger.info("TaskAnalysisAgent: 任务分析上下文准备完成")
        return analysis_context

    def _generate_analysis_prompt(self, context: Dict[str, Any]) -> str:
        """
        生成任务分析提示
        
        Args:
            context: 分析上下文信息
            
        Returns:
            str: 格式化后的分析提示
        """
        logger.debug("TaskAnalysisAgent: 生成任务分析提示")
        
        prompt = self.ANALYSIS_PROMPT_TEMPLATE.format(
            conversation=context['conversation'],
            available_tools=context['available_tools'],
            current_datatime_str=context['current_datatime_str'],
            session_id=context['session_id']
        )
        
        logger.debug("TaskAnalysisAgent: 分析提示生成完成")
        return prompt

    def _execute_streaming_analysis(self, prompt: str, context: Dict[str, Any]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行流式任务分析
        
        Args:
            prompt: 分析提示
            context: 分析上下文信息
            
        Yields:
            List[Dict[str, Any]]: 流式输出的消息块
        """
        logger.info("TaskAnalysisAgent: 开始执行流式任务分析")
        
        # 为整个分析流程生成统一的message_id
        message_id = str(uuid.uuid4())
                
        # 发送初始思考提示
        yield self._create_message_chunk(
            content="Thinking: ",
            message_id=message_id,
            show_content="",
            message_type='task_analysis_result'
        )

        # 始终准备系统消息
        system_message = self.prepare_unified_system_message(
            session_id=context.get('session_id'),
            system_context=context.get('system_context')
        )
        
        # 使用基类的流式处理和token跟踪
        yield from self._execute_streaming_with_token_tracking_with_message_id(
            prompt=prompt,
            step_name="task_analysis",
            system_message=system_message,
            message_type='task_analysis_result',
            session_id=context.get('session_id'),
            message_id=message_id
        )

    def _handle_analysis_error(self, error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理分析过程中的错误
        
        Args:
            error: 发生的异常
            
        Yields:
            List[Dict[str, Any]]: 错误消息块
        """
        yield from self._handle_error_generic(
            error=error,
            error_context="任务分析",
            message_type='task_analysis_result'
        )

    def run(self, 
            messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None,
            session_id: str = None,
            system_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        执行任务分析（非流式版本）
        
        Args:
            messages: 对话历史记录
            tool_manager: 可选的工具管理器
            session_id: 会话ID
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Returns:
            List[Dict[str, Any]]: 任务分析结果消息列表
        """
        logger.info("TaskAnalysisAgent: 执行非流式任务分析")
        
        # 调用父类的默认实现，将流式结果合并
        return super().run(
            messages=messages,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        )
