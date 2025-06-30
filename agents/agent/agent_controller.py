"""
AgentController 重构版本

智能体控制器，负责协调多个智能体协同工作。
改进了代码结构、错误处理、日志记录和可维护性。

作者: Eric ZZ
版本: 2.0 (重构版)
"""

import json
import uuid
import re
import os
import sys
import datetime
import traceback
import time
import threading
from typing import List, Dict, Any, Optional, Generator
from enum import Enum

from .agent_base import AgentBase
from .task_analysis_agent.task_analysis_agent import TaskAnalysisAgent
from .executor_agent.executor_agent import ExecutorAgent
from .task_summary_agent.task_summary_agent import TaskSummaryAgent
from .planning_agent.planning_agent import PlanningAgent
from .observation_agent.observation_agent import ObservationAgent
from .direct_executor_agent.direct_executor_agent import DirectExecutorAgent
from .task_decompose_agent.task_decompose_agent import TaskDecomposeAgent
from .stage_summary_agent.stage_summary_agent import StageSummaryAgent
from .workflow_selector import select_workflow_with_llm, create_workflow_guidance, WorkflowFormat
from .session_manager import SessionManager, SessionStatus
from agents.utils.logger import logger



class AgentController:
    """
    智能体控制器
    
    负责协调多个智能体协同工作，管理任务执行流程，
    包括任务分析、规划、执行、观察和总结等阶段。
    """

    # 默认配置常量
    DEFAULT_MAX_LOOP_COUNT = 10
    DEFAULT_MESSAGE_LIMIT = 10000

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", workspace: str = "/tmp/sage"):
        """
        初始化智能体控制器
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
            workspace: 工作空间根目录，默认为 /tmp/sage
        """
        self.model = model
        self.model_config = model_config
        self.system_prefix = system_prefix
        self.workspace = workspace
        self._init_agents()
        
        # 会话状态管理器
        self.session_manager = SessionManager()
        
        # 总体token统计
        self.overall_token_stats = {
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_cached_tokens': 0,
            'total_reasoning_tokens': 0,
            'total_calls': 0,
            'total_execution_time': 0,
            'workflow_start_time': None,
            'workflow_end_time': None
        }
        
        # 消息和任务管理器（每个会话都会创建独立的实例）
        self._session_managers = {}
        
        # 任务状态跟踪（用于检测任务完成状态变化）
        self._task_status_tracking = {}
        
        logger.info("AgentController: 智能体控制器初始化完成")

    def _init_agents(self) -> None:
        """
        初始化所有必需的智能体
        
        使用共享的模型实例为所有智能体进行初始化。
        """
        logger.debug("AgentController: 初始化各类智能体")
        
        self.task_analysis_agent = TaskAnalysisAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.executor_agent = ExecutorAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.task_summary_agent = TaskSummaryAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.planning_agent = PlanningAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.observation_agent = ObservationAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.direct_executor_agent = DirectExecutorAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.task_decompose_agent = TaskDecomposeAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.stage_summary_agent = StageSummaryAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        
        logger.info("AgentController: 所有智能体初始化完成")

    def _get_session_managers(self, session_id: str) -> tuple:
        """
        获取或创建会话的MessageManager和TaskManager
        
        Args:
            session_id: 会话ID
            
        Returns:
            tuple: (message_manager, task_manager)
        """
        if session_id not in self._session_managers:
            from agents.agent.message_manager import MessageManager
            from agents.task.task_manager import TaskManager
            
            message_manager = MessageManager(
                session_id=session_id,
                max_token_limit=8000,
                auto_merge_chunks=True
            )
            task_manager = TaskManager(session_id=session_id)
            
            self._session_managers[session_id] = {
                'message_manager': message_manager,
                'task_manager': task_manager
            }
            
            logger.info(f"AgentController: 为会话 {session_id} 创建了新的MessageManager和TaskManager")
        
        managers = self._session_managers[session_id]
        return managers['message_manager'], managers['task_manager']

    def run_stream(self, 
                   input_messages: List[Dict[str, Any]], 
                   tool_manager: Optional[Any] = None, 
                   session_id: Optional[str] = None, 
                   deep_thinking: bool = True, 
                   summary: bool = True,
                   max_loop_count: int = DEFAULT_MAX_LOOP_COUNT,
                   deep_research: bool = True,
                   system_context: Optional[Dict[str, Any]] = None,
                   available_workflows: Optional[WorkflowFormat] = None) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行智能体工作流并流式输出结果
        
        Args:
            input_messages: 输入消息字典列表
            tool_manager: 工具管理器实例
            session_id: 会话ID
            deep_thinking: 是否进行任务分析
            summary: 是否生成任务总结
            max_loop_count: 最大循环次数
            deep_research: 是否进行深度研究（完整流程）
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            available_workflows: 可用的工作流模板字典 (支持新旧格式)
            
        Yields:
            List[Dict[str, Any]]: 自上次yield以来的新消息字典列表，每个消息包含：
            - message_id: 消息的唯一标识符
            - 其他标准消息字段（role、content、type等）
        """
        # 重置所有agent的token统计
        logger.info("AgentController: 重置所有Agent的Token统计")
        self.reset_all_token_stats()
        
        # 记录工作流开始时间
        self.overall_token_stats['workflow_start_time'] = time.time()
        logger.info(f"AgentController: 开始流式工作流，会话ID: {session_id}")
        
        if system_context:
            logger.info(f"AgentController: 设置了system_context参数: {list(system_context.keys())}")
        if available_workflows:
            logger.info(f"AgentController: 提供了 {len(available_workflows)} 个工作流模板: {list(available_workflows.keys())}")
        
        try:
            # 准备会话和消息
            session_id = self._prepare_session_id(session_id)
            initial_messages = self._prepare_initial_messages(input_messages)
            
            # 创建会话并设置为运行状态
            self.session_manager.create_session(session_id)
            self.session_manager.update_session_status(session_id, SessionStatus.RUNNING, "初始化")
            
            # 设置执行上下文
            system_context = self._setup_system_context(session_id, system_context)
            
            # 初始化MessageManager和TaskManager
            message_manager, task_manager = self._get_session_managers(session_id)
            
            # 初始化LLM请求记录器
            from agents.utils.llm_request_logger import init_llm_logger
            # 使用system_context中的file_workspace作为workspace_root
            llm_logger = init_llm_logger(session_id, workspace_root=system_context['file_workspace'])
            
            # Controller负责将用户输入添加到MessageManager
            message_manager.add_messages(initial_messages, agent_name="AgentController")
            
            # 只有在多智能体协作模式下才进行工作流选择
            if available_workflows and deep_research:
                system_context = self._select_and_apply_workflow(
                    message_manager, available_workflows, system_context
                )
                if self.session_manager.is_interrupted(session_id):
                    logger.info(f"AgentController: 工作流选择阶段被中断，会话ID: {session_id}")
                    return
            
            # 执行工作流
            if deep_research:
                # 多智能体协作模式：执行完整工作流（分解->规划->执行->观察->总结）
                # deep_thinking 独立控制是否执行任务分析
                yield from self._execute_multi_agent_workflow(
                    message_manager=message_manager,
                    task_manager=task_manager,
                    tool_manager=tool_manager,
                    system_context=system_context,
                    session_id=session_id,
                    deep_thinking=deep_thinking,
                    summary=summary,
                    max_loop_count=max_loop_count
                )
            else:
                # 直接执行模式：可选的任务分析 + 直接执行
                yield from self._execute_simplified_workflow(
                    message_manager=message_manager,
                    task_manager=task_manager,
                    tool_manager=tool_manager,
                    system_context=system_context,
                    session_id=session_id,
                    deep_thinking=deep_thinking
                )
            
            # 检查最终状态，如果不是中断状态则标记为完成
            session_info = self.session_manager.get_session(session_id)
            if session_info and session_info['status'] != SessionStatus.INTERRUPTED:
                self.session_manager.update_session_status(session_id, SessionStatus.COMPLETED, "完成")
                logger.info(f"AgentController: 流式工作流完成，会话ID: {session_id}")
            else:
                logger.info(f"AgentController: 流式工作流被中断，会话ID: {session_id}")
            
        except Exception as e:
            # 标记会话错误
            self.session_manager.update_session_status(session_id, SessionStatus.ERROR, "错误")
            logger.error(f"AgentController: 流式工作流执行过程中发生异常: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            yield from self._handle_workflow_error(e)
        finally:
            # 记录工作流结束时间并打印统计
            self.overall_token_stats['workflow_end_time'] = time.time()
            self.print_comprehensive_token_stats(self.overall_token_stats['workflow_end_time'] - self.overall_token_stats['workflow_start_time'])
            
            # 保存会话状态到文件
            try:
                self._save_session_state(session_id, system_context)
            except Exception as save_error:
                logger.warning(f"AgentController: 保存会话状态 {session_id} 时出错: {save_error}")
            
            # 保存LLM请求记录到文件
            try:
                self._save_llm_request_logs(session_id)
            except Exception as llm_save_error:
                logger.warning(f"AgentController: 保存LLM请求记录 {session_id} 时出错: {llm_save_error}")
            
            # 清理会话，防止内存泄漏
            try:
                self.session_manager.remove_session(session_id)
                # 清理MessageManager和TaskManager
                if session_id in self._session_managers:
                    del self._session_managers[session_id]
                
                # 清理LLM记录器实例
                try:
                    from agents.utils.llm_request_logger import cleanup_logger
                    cleanup_logger(session_id)
                    logger.debug(f"AgentController: 已清理LLM记录器 {session_id}")
                except Exception as llm_cleanup_error:
                    logger.warning(f"AgentController: 清理LLM记录器 {session_id} 时出错: {llm_cleanup_error}")
                
                logger.info(f"AgentController: 已清理会话 {session_id}")
            except Exception as cleanup_error:
                logger.warning(f"AgentController: 清理会话 {session_id} 时出错: {cleanup_error}")

    def _prepare_session_id(self, session_id: Optional[str]) -> str:
        """
        准备会话ID
        
        Args:
            session_id: 可选的会话ID
            
        Returns:
            str: 准备好的会话ID
        """
        if session_id is None:
            session_id = str(uuid.uuid1())
            logger.info(f"AgentController: 生成新会话ID: {session_id}")
        return session_id

    def _prepare_initial_messages(self, input_messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        准备初始消息
        
        Args:
            input_messages: 输入消息列表
            
        Returns:
            List[Dict[str, Any]]: 准备好的消息列表
        """
        logger.debug("AgentController: 准备初始消息")
        
        # 为消息添加message_id（如果没有的话）
        all_messages = []
        for msg in input_messages.copy():
            if 'message_id' not in msg:
                msg = {**msg, 'message_id': str(uuid.uuid4())} 
            all_messages.append(msg)
        
        # 清理过长的消息历史
        all_messages = self._trim_message_history(all_messages)
        
        logger.info(f"AgentController: 初始化消息数量: {len(all_messages)}")
        return all_messages

    def _trim_message_history(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        修剪消息历史，防止内容过长
        
        Args:
            messages: 原始消息列表
            
        Returns:
            List[Dict[str, Any]]: 修剪后的消息列表
        """
        logger.debug("AgentController: 检查并修剪消息历史")
        
        # 如果消息内容过长，删除非关键消息
        start_index = 0
        while len(json.dumps(messages)) > self.DEFAULT_MESSAGE_LIMIT and start_index < len(messages):
            if messages[start_index]['role'] == 'user' or messages[start_index].get('type') == 'final_answer':
                start_index += 1
                continue
            else:
                del messages[start_index]
                continue
        
        logger.debug(f"AgentController: 修剪后消息数量: {len(messages)}")
        return messages

    def _setup_system_context(self, session_id: str, user_system_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        设置系统上下文（合并基础信息和用户自定义信息）
        
        Args:
            session_id: 会话ID
            user_system_context: 用户提供的系统上下文
            
        Returns:
            Dict[str, Any]: 完整的系统上下文字典
        """
        logger.debug("AgentController: 设置系统上下文")
        
        current_time_str = datetime.datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')
        # 使用时间+session_id格式组装路径
        start_time = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        folder_name = f"{start_time}_{session_id}"
        file_workspace = os.path.join(self.workspace, folder_name)
        
        # 创建工作目录
        if os.path.exists(file_workspace):
            logger.debug("AgentController: 使用现有工作目录")
        else:
            os.makedirs(file_workspace, exist_ok=True)
            logger.debug(f"AgentController: 创建工作目录: {file_workspace}")
        
        # 构建完整的系统上下文，基础信息在前
        system_context = {
            'session_id': session_id,
            'current_time': current_time_str, 
            'file_workspace': file_workspace
        }
        
        # 如果用户提供了自定义上下文，则合并
        if user_system_context:
            system_context.update(user_system_context)
            logger.info(f"AgentController: 合并用户系统上下文: {list(user_system_context.keys())}")
        
        logger.info(f"AgentController: 系统上下文设置完成，包含 {len(system_context)} 个字段")
        return system_context

    def _select_and_apply_workflow(self, 
                                   message_manager: Any, 
                                   available_workflows: WorkflowFormat, 
                                   system_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        选择并应用合适的工作流到系统上下文中
        
        Args:
            message_manager: MessageManager实例
            available_workflows: 可用的工作流模板
            system_context: 当前系统上下文
            
        Returns:
            Dict[str, Any]: 更新后的系统上下文
        """
        logger.info("AgentController: 开始工作流选择")
        
        try:
            # 从MessageManager获取消息用于工作流选择
            all_messages = message_manager.get_all_messages()
            
            # 使用LLM选择工作流，传入完整的消息历史
            workflow_name, workflow_steps = select_workflow_with_llm(
                model=self.model,
                model_config=self.model_config,
                messages=all_messages,
                available_workflows=available_workflows
            )
            
            if workflow_name and workflow_steps:
                # 创建工作流指导文本
                workflow_guidance = create_workflow_guidance(workflow_name, workflow_steps)
                
                # 添加到系统上下文（简化版本）
                system_context['workflow_guidance'] = workflow_guidance
                
                logger.info(f"AgentController: 成功选择工作流 '{workflow_name}'")
                logger.info(f"AgentController: 工作流指导已添加到系统上下文")
                
            else:
                logger.info("AgentController: 未选择工作流")
                
        except Exception as e:
            logger.error(f"AgentController: 工作流选择失败: {str(e)}")
        
        return system_context

    def _execute_multi_agent_workflow(self, 
                                     message_manager: Any,
                                     task_manager: Any,
                                     tool_manager: Optional[Any],
                                     system_context: Dict[str, Any],
                                     session_id: str,
                                     deep_thinking: bool,
                                     summary: bool,
                                     max_loop_count: int) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行完整的工作流
        
        Args:
            message_manager: MessageManager实例
            task_manager: TaskManager实例
            tool_manager: 工具管理器
            system_context: 执行上下文
            session_id: 会话ID
            deep_thinking: 是否进行深度思考
            summary: 是否生成总结
            max_loop_count: 最大循环次数
            
        Yields:
            List[Dict[str, Any]]: 工作流输出的消息块
        """
        logger.info("AgentController: 开始执行完整工作流")
        
        # 1. 任务分析阶段
        if deep_thinking:
            yield from self._execute_task_analysis_phase(
                message_manager, task_manager, tool_manager, system_context, session_id
            )
        
        # 2. 任务分解阶段
        yield from self._execute_task_decomposition_phase(
            message_manager, task_manager, tool_manager, system_context, session_id
        )
        
        # 3. 规划-执行-观察循环
        yield from self._execute_main_loop(
            message_manager, task_manager, tool_manager, system_context, session_id, max_loop_count
        )
        
        # 4. 任务总结阶段
        if summary:
            yield from self._execute_task_summary_phase(
                message_manager, task_manager, tool_manager, system_context, session_id
            )

    def _execute_task_analysis_phase(self, 
                                   message_manager: Any,
                                   task_manager: Any,
                                   tool_manager: Optional[Any],
                                   system_context: Dict[str, Any],
                                   session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行任务分析阶段
        
        Args:
            message_manager: MessageManager实例
            task_manager: TaskManager实例
            tool_manager: 工具管理器
            system_context: 执行上下文
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 任务分析输出的消息块
        """
        logger.info("AgentController: 开始任务分析阶段")
        self.session_manager.update_session_status(session_id, SessionStatus.RUNNING, "任务分析")
        
        # 检查中断
        if self.session_manager.is_interrupted(session_id):
            logger.info(f"AgentController: 任务分析阶段被中断，会话ID: {session_id}")
            return
        
        analysis_chunks = []
        for chunk in self.task_analysis_agent.run_stream(
            message_manager=message_manager,
            task_manager=task_manager,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        ):
            # 在每个块之间检查中断
            if self.session_manager.is_interrupted(session_id):
                logger.info(f"AgentController: 任务分析阶段在块处理中被中断，会话ID: {session_id}")
                return
            
            analysis_chunks.append(chunk)
            yield chunk
        
        logger.info(f"AgentController: 任务分析阶段完成，生成 {len(analysis_chunks)} 个块")

    def _execute_task_decomposition_phase(self, 
                                        message_manager: Any,
                                        task_manager: Any,
                                        tool_manager: Optional[Any],
                                        system_context: Dict[str, Any],
                                        session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行任务分解阶段
        
        Args:
            message_manager: MessageManager实例
            task_manager: TaskManager实例
            tool_manager: 工具管理器
            system_context: 执行上下文
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 任务分解输出的消息块
        """
        logger.info("AgentController: 开始任务分解阶段")
        self.session_manager.update_session_status(session_id, SessionStatus.RUNNING, "任务分解")
        
        # 检查中断
        if self.session_manager.is_interrupted(session_id):
            logger.info(f"AgentController: 任务分解阶段被中断，会话ID: {session_id}")
            return
        
        decompose_chunks = []
        for chunk in self.task_decompose_agent.run_stream(
            message_manager=message_manager,
            task_manager=task_manager,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        ):
            # 在每个块之间检查中断
            if self.session_manager.is_interrupted(session_id):
                logger.info(f"AgentController: 任务分解阶段在块处理中被中断，会话ID: {session_id}")
                return
            
            decompose_chunks.append(chunk)
            yield chunk
        
        logger.info(f"AgentController: 任务分解阶段完成，生成 {len(decompose_chunks)} 个块")

    def _execute_main_loop(self, 
                         message_manager: Any,
                         task_manager: Any,
                         tool_manager: Optional[Any],
                         system_context: Dict[str, Any],
                         session_id: str,
                         max_loop_count: int) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行主要的规划-执行-观察循环
        
        Args:
            message_manager: MessageManager实例
            task_manager: TaskManager实例
            tool_manager: 工具管理器
            system_context: 执行上下文
            session_id: 会话ID
            max_loop_count: 最大循环次数
            
        Yields:
            List[Dict[str, Any]]: 循环输出的消息块
        """
        logger.info("AgentController: 开始规划-执行-观察循环")
        
        loop_count = 0
        while True:
            loop_count += 1
            logger.info(f"AgentController: 开始第 {loop_count} 轮循环")
            
            # 在每轮循环开始时检查中断
            if self.session_manager.is_interrupted(session_id):
                logger.info(f"AgentController: 主循环第 {loop_count} 轮被中断，会话ID: {session_id}")
                return
            
            if loop_count > max_loop_count:
                logger.warning(f"AgentController: 达到最大循环次数 {max_loop_count}，停止工作流")
                break

            # 规划阶段
            yield from self._execute_planning_phase(
                message_manager, task_manager, tool_manager, system_context, session_id
            )
            
            # 执行阶段
            yield from self._execute_execution_phase(
                message_manager, task_manager, tool_manager, system_context, session_id
            )
            
            # 观察阶段
            should_break = yield from self._execute_observation_phase(
                message_manager, task_manager, tool_manager, system_context, session_id
            )
            
            if should_break:
                break
        
        logger.info("AgentController: 规划-执行-观察循环完成")

    def _execute_planning_phase(self, 
                              message_manager: Any,
                              task_manager: Any,
                              tool_manager: Optional[Any],
                              system_context: Dict[str, Any],
                              session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行规划阶段
        
        Args:
            message_manager: MessageManager实例
            task_manager: TaskManager实例
            tool_manager: 工具管理器
            system_context: 执行上下文
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 规划输出的消息块
        """
        logger.info("AgentController: 开始规划阶段")
        self.session_manager.update_session_status(session_id, SessionStatus.RUNNING, "规划")
        
        # 检查中断
        if self.session_manager.is_interrupted(session_id):
            logger.info(f"AgentController: 规划阶段被中断，会话ID: {session_id}")
            return
        
        plan_chunks = []
        for chunk in self.planning_agent.run_stream(
            message_manager=message_manager,
            task_manager=task_manager,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        ):
            # 在每个块之间检查中断
            if self.session_manager.is_interrupted(session_id):
                logger.info(f"AgentController: 规划阶段在块处理中被中断，会话ID: {session_id}")
                return
            
            plan_chunks.append(chunk)
            yield chunk
        
        logger.info(f"AgentController: 规划阶段完成，生成 {len(plan_chunks)} 个块")

    def _execute_execution_phase(self, 
                               message_manager: Any,
                               task_manager: Any,
                               tool_manager: Optional[Any],
                               system_context: Dict[str, Any],
                               session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行执行阶段
        
        Args:
            message_manager: MessageManager实例
            task_manager: TaskManager实例
            tool_manager: 工具管理器
            system_context: 执行上下文
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 执行输出的消息块
        """
        logger.info("AgentController: 开始执行阶段")
        self.session_manager.update_session_status(session_id, SessionStatus.RUNNING, "执行")
        
        # 检查中断
        if self.session_manager.is_interrupted(session_id):
            logger.info(f"AgentController: 执行阶段被中断，会话ID: {session_id}")
            return
        
        exec_chunks = []
        for chunk in self.executor_agent.run_stream(
            message_manager=message_manager,
            task_manager=task_manager,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        ):
            # 在每个块之间检查中断
            if self.session_manager.is_interrupted(session_id):
                logger.info(f"AgentController: 执行阶段在块处理中被中断，会话ID: {session_id}")
                return
            
            exec_chunks.append(chunk)
            yield chunk
        
        logger.info(f"AgentController: 执行阶段完成，生成 {len(exec_chunks)} 个块")
        
        # 通过message_manager获取ExecutorAgent的最新消息并简要展示
        try:
            # 获取ExecutorAgent的最新消息
            executor_messages = message_manager.get_latest_messages_by_agent("ExecutorAgent", limit=10)
            
            if executor_messages:
                logger.info(f"[ExecutorAgent本次输出] 共{len(executor_messages)}条消息:")
                for i, msg in enumerate(executor_messages, 1):
                    content = msg.get('content', '')
                    msg_type = msg.get('type', 'unknown')
                    if content and content.strip():
                        # 显示前100字
                        preview = content.strip()[:100]
                        logger.info(f"  {i}. [{msg_type}] {preview}{'...' if len(content.strip()) > 100 else ''}")
            else:
                logger.info("[ExecutorAgent本次输出] 暂无消息")
                
        except Exception as e:
            logger.warning(f"AgentController: 获取ExecutorAgent消息摘要失败: {str(e)}")

    def _execute_observation_phase(self, 
                                 message_manager: Any,
                                 task_manager: Any,
                                 tool_manager: Optional[Any],
                                 system_context: Dict[str, Any],
                                 session_id: str) -> Generator[List[Dict[str, Any]], None, bool]:
        """
        执行观察阶段
        
        Args:
            message_manager: MessageManager实例
            task_manager: TaskManager实例
            tool_manager: 工具管理器
            system_context: 执行上下文
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 观察输出的消息块
            
        Returns:
            bool: 是否应该中断循环
        """
        logger.info("AgentController: 开始观察阶段")
        self.session_manager.update_session_status(session_id, SessionStatus.RUNNING, "观察")
        
        # 检查中断
        if self.session_manager.is_interrupted(session_id):
            logger.info(f"AgentController: 观察阶段被中断，会话ID: {session_id}")
            return True  # 中断时也返回should_break=True
        
        obs_chunks = []
        for chunk in self.observation_agent.run_stream(
            message_manager=message_manager,
            task_manager=task_manager,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        ):
            # 在每个块之间检查中断
            if self.session_manager.is_interrupted(session_id):
                logger.info(f"AgentController: 观察阶段在块处理中被中断，会话ID: {session_id}")
                return True  # 中断时也返回should_break=True
            
            obs_chunks.append(chunk)
            yield chunk
        
        logger.info(f"AgentController: 观察阶段完成，生成 {len(obs_chunks)} 个块")
        
        # 检查任务完成状态变化并生成阶段总结
        for summary_chunk in self._check_task_completion_and_summarize(
            session_id=session_id,
            message_manager=message_manager,
            task_manager=task_manager,
            tool_manager=tool_manager,
            system_context=system_context
        ):
            yield summary_chunk
        
        # 检查是否应该继续循环
        should_break = self._check_loop_completion_from_manager(message_manager)
        
        return should_break

    def _execute_task_summary_phase(self, 
                                  message_manager: Any,
                                  task_manager: Any,
                                  tool_manager: Optional[Any],
                                  system_context: Dict[str, Any],
                                  session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行任务总结阶段
        
        Args:
            message_manager: MessageManager实例
            task_manager: TaskManager实例
            tool_manager: 工具管理器
            system_context: 执行上下文
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 总结输出的消息块
        """
        logger.info("AgentController: 开始任务总结阶段")
        self.session_manager.update_session_status(session_id, SessionStatus.RUNNING, "总结")
        
        # 检查中断
        if self.session_manager.is_interrupted(session_id):
            logger.info(f"AgentController: 任务总结阶段被中断，会话ID: {session_id}")
            return
        
        summary_chunks = []
        for chunk in self.task_summary_agent.run_stream(
            message_manager=message_manager,
            task_manager=task_manager,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        ):
            # 在每个块之间检查中断
            if self.session_manager.is_interrupted(session_id):
                logger.info(f"AgentController: 任务总结阶段在块处理中被中断，会话ID: {session_id}")
                return
            
            summary_chunks.append(chunk)
            yield chunk
        
        logger.info(f"AgentController: 任务总结阶段完成，生成 {len(summary_chunks)} 个块")

    def _execute_simplified_workflow(self, 
                                    message_manager: Any,
                                    task_manager: Any,
                                    tool_manager: Optional[Any],
                                    system_context: Dict[str, Any],
                                    session_id: str,
                                    deep_thinking: bool) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行简化工作流（可选的任务分析 + 直接执行）
        
        Args:
            message_manager: MessageManager实例
            task_manager: TaskManager实例
            tool_manager: 工具管理器
            system_context: 执行上下文
            session_id: 会话ID
            deep_thinking: 是否进行任务分析
            
        Yields:
            List[Dict[str, Any]]: 工作流输出的消息块
        """
        logger.info("AgentController: 开始简化工作流")
        
        # 1. 任务分析阶段
        if deep_thinking:
            yield from self._execute_task_analysis_phase(
                message_manager, task_manager, tool_manager, system_context, session_id
            )
        
        # 2. 直接执行
        yield from self._execute_direct_workflow(
            message_manager=message_manager,
            task_manager=task_manager,
            tool_manager=tool_manager,
            system_context=system_context,
            session_id=session_id
        )

    def _execute_direct_workflow(self, 
                               message_manager: Any,
                               task_manager: Any,
                               tool_manager: Optional[Any],
                               system_context: Dict[str, Any],
                               session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行直接工作流（使用直接执行智能体）
        
        Args:
            message_manager: MessageManager实例
            task_manager: TaskManager实例
            tool_manager: 工具管理器
            system_context: 执行上下文
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 直接执行输出的消息块
        """
        logger.info("AgentController: 使用直接执行智能体")
        self.session_manager.update_session_status(session_id, SessionStatus.RUNNING, "直接执行")
        
        # 检查中断
        if self.session_manager.is_interrupted(session_id):
            logger.info(f"AgentController: 直接执行阶段被中断，会话ID: {session_id}")
            return
        
        for chunk in self.direct_executor_agent.run_stream(
            message_manager=message_manager,
            task_manager=task_manager,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context
        ):
            # 在每个块之间检查中断
            if self.session_manager.is_interrupted(session_id):
                logger.info(f"AgentController: 直接执行阶段在块处理中被中断，会话ID: {session_id}")
                return
            
            yield chunk
        
        logger.info("AgentController: 直接执行智能体完成")

    def _check_loop_completion(self, all_messages: List[Dict[str, Any]]) -> bool:
        """
        检查循环是否应该完成
        
        Args:
            all_messages: 所有消息列表
            
        Returns:
            bool: 是否应该中断循环
        """
        logger.debug("AgentController: 检查循环完成条件")
        
        try:
            obs_content = all_messages[-1]['content'].replace('Observation: ', '')
            obs_result = json.loads(obs_content)
            
            if obs_result.get('is_completed', False):
                logger.info("AgentController: 观察阶段指示任务已完成")
                return True
                
            if obs_result.get('needs_more_input', False):
                logger.info("AgentController: 任务需要用户提供更多输入")
                clarify_msg = {
                    'role': 'assistant',
                    'content': obs_result.get('user_query', ''),
                    'type': 'final_answer',
                    'message_id': str(uuid.uuid4()),
                    'show_content': obs_result.get('user_query', '') + '\n'
                }
                all_messages.append(clarify_msg)
                return True
                
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.warning(f"AgentController: 解析观察结果失败: {str(e)}，继续循环")
            
        return False

    def _check_loop_completion_from_manager(self, message_manager: Any) -> bool:
        """
        从MessageManager检查循环是否应该完成
        
        Args:
            message_manager: MessageManager实例
            
        Returns:
            bool: 是否应该中断循环
        """
        logger.debug("AgentController: 从MessageManager检查循环完成条件")
        
        try:
            all_messages = message_manager.get_all_messages()
            if not all_messages:
                return False
            
            # 查找最后一个观察结果
            obs_messages = [msg for msg in all_messages if msg.get('type') == 'observation_result']
            if not obs_messages:
                return False
            
            last_obs_msg = obs_messages[-1]
            obs_content = last_obs_msg['content'].replace('Observation: ', '')
            obs_result = json.loads(obs_content)
            
            if obs_result.get('is_completed', False):
                logger.info("AgentController: 观察阶段指示任务已完成")
                return True
                
            if obs_result.get('needs_more_input', False):
                logger.info("AgentController: 任务需要用户提供更多输入")
                user_query = obs_result.get('user_query', '')
                if user_query:
                    clarify_msg = {
                        'role': 'assistant',
                        'content': user_query,
                        'type': 'final_answer',
                        'message_id': str(uuid.uuid4()),
                        'show_content': user_query + '\n'
                    }
                    message_manager.add_messages([clarify_msg], agent_name="AgentController")
                return True
                
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.warning(f"AgentController: 解析观察结果失败: {str(e)}，继续循环")
            
        return False

    def _check_task_completion_and_summarize(self, 
                                           session_id: str,
                                           message_manager: Any,
                                           task_manager: Any,
                                           tool_manager: Optional[Any],
                                           system_context: Dict[str, Any]) -> Generator[List[Dict[str, Any]], None, None]:
        """
        检查任务完成状态变化，如果从未完成变成完成，则调用StageSummaryAgent
        
        Args:
            session_id: 会话ID
            message_manager: 消息管理器
            task_manager: 任务管理器
            tool_manager: 工具管理器
            system_context: 系统上下文
            
        Yields:
            List[Dict[str, Any]]: StageSummaryAgent的输出消息
        """
        if not task_manager:
            return
        
        # 获取当前任务状态
        current_tasks = task_manager.get_all_tasks()
        current_completed_count = len([task for task in current_tasks if task.status.value == "completed"])
        
        # 获取之前的状态
        previous_completed_count = self._task_status_tracking.get(session_id, 0)
        
        # 检查是否有新完成的任务
        if current_completed_count > previous_completed_count:
            logger.info(f"AgentController: 检测到任务状态变化，完成任务数从 {previous_completed_count} 增加到 {current_completed_count}")
            
            # 更新跟踪状态
            self._task_status_tracking[session_id] = current_completed_count
            
            # 调用StageSummaryAgent生成任务执行总结
            yield from self._execute_stage_summary_phase(
                message_manager=message_manager,
                task_manager=task_manager,
                tool_manager=tool_manager,
                system_context=system_context,
                session_id=session_id
            )
        else:
            # 初始化跟踪状态
            if session_id not in self._task_status_tracking:
                self._task_status_tracking[session_id] = current_completed_count

    def _execute_stage_summary_phase(self, 
                                   message_manager: Any,
                                   task_manager: Any,
                                   tool_manager: Optional[Any],
                                   system_context: Dict[str, Any],
                                   session_id: str) -> Generator[List[Dict[str, Any]], None, None]:
        """
        执行阶段总结阶段
        
        Args:
            message_manager: MessageManager实例
            task_manager: TaskManager实例
            tool_manager: 工具管理器
            system_context: 执行上下文
            session_id: 会话ID
            
        Yields:
            List[Dict[str, Any]]: 阶段总结输出的消息块
        """
        logger.info("AgentController: 开始阶段总结阶段")
        self.session_manager.update_session_status(session_id, SessionStatus.RUNNING, "阶段总结")
        
        # 检查中断
        if self.session_manager.is_interrupted(session_id):
            logger.info(f"AgentController: 阶段总结阶段被中断，会话ID: {session_id}")
            return
        
        # 准备阶段信息
        stage_info = {
            "stage_type": "task_completion",
            "completed_tasks_count": len([task for task in task_manager.get_all_tasks() if task.status.value == "completed"]),
            "total_tasks_count": len(task_manager.get_all_tasks()),
            "session_id": session_id
        }
        
        summary_chunks = []
        for chunk in self.stage_summary_agent.run_stream(
            message_manager=message_manager,
            task_manager=task_manager,
            tool_manager=tool_manager,
            session_id=session_id,
            system_context=system_context,
            stage_info=stage_info
        ):
            # 在每个块之间检查中断
            if self.session_manager.is_interrupted(session_id):
                logger.info(f"AgentController: 阶段总结阶段在块处理中被中断，会话ID: {session_id}")
                return
            
            summary_chunks.append(chunk)
            yield chunk
        
        logger.info(f"AgentController: 阶段总结阶段完成，生成 {len(summary_chunks)} 个块")

    def _handle_workflow_error(self, error: Exception) -> Generator[List[Dict[str, Any]], None, None]:
        """
        处理工作流执行错误
        
        Args:
            error: 发生的异常
            
        Yields:
            List[Dict[str, Any]]: 错误消息块
        """
        logger.error(f"AgentController: 处理工作流错误: {str(error)}")
        
        error_message = f"工作流执行失败: {str(error)}"
        message_id = str(uuid.uuid4())
        
        yield [{
            'role': 'assistant',
            'content': error_message,
            'type': 'final_answer',
            'message_id': message_id,
            'show_content': error_message
        }]

    def run(self, 
            input_messages: List[Dict[str, Any]], 
            tool_manager: Optional[Any] = None, 
            session_id: Optional[str] = None, 
            deep_thinking: bool = True,
            summary: bool = True,
            max_loop_count: int = DEFAULT_MAX_LOOP_COUNT,
            deep_research: bool = True,
            system_context: Optional[Dict[str, Any]] = None,
            available_workflows: Optional[WorkflowFormat] = None) -> Dict[str, Any]:
        """
        执行智能体工作流（非流式版本）
        
        Args:
            input_messages: 输入消息字典列表
            tool_manager: 工具管理器实例
            session_id: 会话ID
            deep_thinking: 是否进行任务分析
            summary: 是否生成任务总结
            max_loop_count: 最大循环次数
            deep_research: 是否进行深度研究（完整流程）
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            available_workflows: 可用的工作流模板字典 {name: [steps]}
            
        Returns:
            Dict[str, Any]: 包含all_messages、new_messages、final_output和session_id的结果字典
        """
        logger.info(f"AgentController: 开始非流式工作流，会话ID: {session_id}")
        
        if system_context:
            logger.info(f"AgentController: 设置了system_context参数: {list(system_context.keys())}")
        
        # 重置所有agent的token统计
        logger.info("AgentController: 重置所有Agent的Token统计")
        self.reset_all_token_stats()
        
        # 记录工作流开始时间
        self.overall_token_stats['workflow_start_time'] = time.time()
        
        try:
            # 准备会话和消息
            session_id = self._prepare_session_id(session_id)
            
            # 初始化消息和状态
            all_messages = input_messages.copy()
            new_messages = []
            
            logger.info(f"AgentController: 初始化 {len(all_messages)} 条输入消息")
            
            # 设置执行上下文
            system_context = self._setup_system_context(session_id, system_context)
            
            # 只有在多智能体协作模式下才进行工作流选择
            if available_workflows and deep_research:
                system_context = self._select_and_apply_workflow(
                    all_messages, available_workflows, system_context
                )
            
            # 根据deep_research参数选择执行路径
            if deep_research:
                # 多智能体协作模式：执行完整流程（分解->规划->执行->观察->总结）
                # deep_thinking 独立控制是否执行任务分析
                if deep_thinking:
                    all_messages, new_messages = self._execute_task_analysis_non_stream(
                        all_messages, new_messages, tool_manager, system_context
                    )
                
                # 任务分解阶段
                all_messages, new_messages = self._execute_task_decompose_non_stream(
                    all_messages, new_messages, tool_manager, system_context
                )
                
                # 主循环
                all_messages, new_messages = self._execute_main_loop_non_stream(
                    all_messages, new_messages, tool_manager, session_id, max_loop_count, system_context
                )
                
                # 总结阶段
                if summary:
                    all_messages, new_messages, final_output = self._execute_task_summary_non_stream(
                        all_messages, new_messages, tool_manager, system_context
                    )
                else:
                    final_output = new_messages[-1] if new_messages else None
            else:
                # 简化模式：可选的任务分析 + 直接执行
                if deep_thinking:
                    all_messages, new_messages = self._execute_task_analysis_non_stream(
                        all_messages, new_messages, tool_manager, system_context
                    )
                
                # 直接执行
                direct_messages = self.direct_executor_agent.run(
                    all_messages, tool_manager, session_id=session_id, system_context=system_context
                )
                all_messages.extend(direct_messages)
                new_messages.extend(direct_messages)
                final_output = new_messages[-1] if new_messages else None
            
            logger.info(f"AgentController: 非流式工作流完成，会话ID: {session_id}")
            
            return {
                'all_messages': all_messages,
                'new_messages': new_messages,
                'final_output': final_output,
                'session_id': session_id,
            }
            
        except Exception as e:
            logger.error(f"AgentController: 非流式工作流执行过程中发生异常: {str(e)}")
            logger.error(f"异常详情: {traceback.format_exc()}")
            
            error_message = {
                'role': 'assistant',
                'content': f"工作流执行失败: {str(e)}",
                'type': 'final_answer'
            }
            
            return {
                'all_messages': input_messages + [error_message],
                'new_messages': [error_message],
                'final_output': error_message,
                'session_id': session_id or str(uuid.uuid1()),
            }
        finally:
            # 记录工作流结束时间并打印统计
            self.overall_token_stats['workflow_end_time'] = time.time()
            self.print_comprehensive_token_stats(self.overall_token_stats['workflow_end_time'] - self.overall_token_stats['workflow_start_time'])

    def _execute_task_analysis_non_stream(self, 
                                        all_messages: List[Dict[str, Any]], 
                                        new_messages: List[Dict[str, Any]], 
                                        tool_manager: Optional[Any],
                                        system_context: Optional[Dict[str, Any]]) -> tuple:
        """
        执行任务分析（非流式版本）
        
        Args:
            all_messages: 所有消息列表
            new_messages: 新消息列表
            tool_manager: 工具管理器
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Returns:
            tuple: 更新后的(all_messages, new_messages)
        """
        logger.info("AgentController: 开始初始任务分析")
        
        analysis_messages = self.task_analysis_agent.run(all_messages, tool_manager, system_context=system_context)
        logger.info(f"AgentController: 任务分析完成，生成 {len(analysis_messages)} 条消息")
        
        all_messages.extend(analysis_messages)
        new_messages.extend(analysis_messages)
        
        return all_messages, new_messages

    def _execute_task_decompose_non_stream(self, 
                                         all_messages: List[Dict[str, Any]], 
                                         new_messages: List[Dict[str, Any]], 
                                         tool_manager: Optional[Any],
                                         system_context: Optional[Dict[str, Any]]) -> tuple:
        """
        执行任务分解（非流式版本）
        
        Args:
            all_messages: 所有消息列表
            new_messages: 新消息列表
            tool_manager: 工具管理器
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Returns:
            tuple: 更新后的(all_messages, new_messages)
        """
        logger.info("AgentController: 开始任务分解")
        
        decompose_messages = self.task_decompose_agent.run(all_messages, tool_manager, system_context=system_context)
        logger.info(f"AgentController: 任务分解完成，生成 {len(decompose_messages)} 条消息")
        
        all_messages.extend(decompose_messages)
        new_messages.extend(decompose_messages)
        
        return all_messages, new_messages

    def _execute_main_loop_non_stream(self, 
                                    all_messages: List[Dict[str, Any]], 
                                    new_messages: List[Dict[str, Any]], 
                                    tool_manager: Optional[Any], 
                                    session_id: str,
                                    max_loop_count: int,
                                    system_context: Optional[Dict[str, Any]]) -> tuple:
        """
        执行主循环（非流式版本）
        
        Args:
            all_messages: 所有消息列表
            new_messages: 新消息列表
            tool_manager: 工具管理器
            session_id: 会话ID
            max_loop_count: 最大循环次数
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Returns:
            tuple: 更新后的(all_messages, new_messages)
        """
        loop_count = 0
        
        while loop_count < max_loop_count:
            loop_count += 1
            logger.info(f"AgentController: 开始第 {loop_count} 轮规划-执行-观察循环")
            
            # 规划阶段
            plan_messages = self.planning_agent.run(all_messages, tool_manager, system_context=system_context)
            logger.info(f"AgentController: 规划阶段完成，生成 {len(plan_messages)} 条消息")
            all_messages.extend(plan_messages)
            new_messages.extend(plan_messages)
            
            # 执行阶段
            exec_messages = self.executor_agent.run(all_messages, tool_manager, session_id=session_id, system_context=system_context)
            logger.info(f"AgentController: 执行阶段完成，生成 {len(exec_messages)} 条消息")
            all_messages.extend(exec_messages)
            new_messages.extend(exec_messages)
            
            # 观察阶段
            obs_messages = self.observation_agent.run(all_messages, system_context=system_context)
            logger.info(f"AgentController: 观察阶段完成，生成 {len(obs_messages)} 条消息")
            all_messages.extend(obs_messages)
            new_messages.extend(obs_messages)
            
            # 检查任务是否完成
            should_break = self._check_task_completion(obs_messages, all_messages, new_messages)
            if should_break:
                break
        
        if loop_count >= max_loop_count:
            logger.warning(f"AgentController: 达到最大循环次数 {max_loop_count}，强制结束")
        
        return all_messages, new_messages

    def _check_task_completion(self, 
                             obs_messages: List[Dict[str, Any]], 
                             all_messages: List[Dict[str, Any]], 
                             new_messages: List[Dict[str, Any]]) -> bool:
        """
        检查任务是否完成
        
        Args:
            obs_messages: 观察消息列表
            all_messages: 所有消息列表
            new_messages: 新消息列表
            
        Returns:
            bool: 是否应该中断循环
        """
        try:
            obs_result_content = obs_messages[-1]['content'].replace('Observation: ', '')
            obs_result_json = json.loads(obs_result_content)
            
            if obs_result_json.get('is_completed', False):
                logger.info("AgentController: 观察阶段指示任务已完成")
                return True
                
            if obs_result_json.get('needs_more_input', False):
                logger.info("AgentController: 任务需要用户提供更多输入")
                clarify_message = {
                    'role': 'assistant',
                    'content': obs_result_json.get('user_query', ''),
                    'type': 'final_answer'
                }
                all_messages.append(clarify_message)
                new_messages.append(clarify_message)
                return True
                
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.warning(f"AgentController: 观察结果解析失败: {str(e)}，继续执行")
            
        return False

    def _execute_task_summary_non_stream(self, 
                                       all_messages: List[Dict[str, Any]], 
                                       new_messages: List[Dict[str, Any]], 
                                       tool_manager: Optional[Any],
                                       system_context: Optional[Dict[str, Any]]) -> tuple:
        """
        执行任务总结（非流式版本）
        
        Args:
            all_messages: 所有消息列表
            new_messages: 新消息列表
            tool_manager: 工具管理器
            system_context: 运行时系统上下文字典，用于自定义推理时的变化信息
            
        Returns:
            tuple: 更新后的(all_messages, new_messages, final_output)
        """
        logger.info("AgentController: 开始任务总结阶段")
        
        summary_result = self.task_summary_agent.run(all_messages, tool_manager, system_context=system_context)
        logger.info(f"AgentController: 任务总结完成，生成 {len(summary_result)} 条消息")
        
        all_messages.extend(summary_result)
        new_messages.extend(summary_result)
        
        # 获取最终输出（最后一条正常消息）
        final_output = next(
            (m for m in reversed(summary_result) if m.get('type') == 'final_answer'),
            summary_result[-1] if summary_result else None
        )
        
        return all_messages, new_messages, final_output

    def _is_task_complete(self, messages: List[Dict[str, Any]]) -> bool:
        """
        基于评估输出检查任务是否完成
        
        Args:
            messages: 消息列表
            
        Returns:
            bool: 任务是否完成
        """
        logger.debug("AgentController: 检查任务完成状态")
        
        # 查找工具响应消息
        tool_response = next(
            (msg for msg in messages 
             if msg.get('role') == 'tool' and 
                msg.get('tool_call_id', '').startswith('decision_')),
            None
        )
        
        if not tool_response or not tool_response.get('content'):
            return False
            
        content = tool_response['content']
        
        try:
            # 尝试直接解析为JSON
            result = json.loads(content)
        except json.JSONDecodeError:
            # 尝试从markdown代码块中提取JSON
            code_block_pattern = r'```(?:json)?\n([\s\S]*?)\n```'
            match = re.search(code_block_pattern, content)
            if match:
                try:
                    result = json.loads(match.group(1))
                except json.JSONDecodeError:
                    return False
            else:
                return False
                
        is_complete = result.get('task_status', '') == 'completed'
        logger.debug(f"AgentController: 任务完成状态: {is_complete}")
        return is_complete

    def _collect_agent_stats(self) -> Dict[str, Any]:
        """
        收集所有agent的token统计信息
        
        Returns:
            Dict[str, Any]: 汇总的统计信息
        """
        all_stats = {}
        total_stats = {
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_cached_tokens': 0,
            'total_reasoning_tokens': 0,
            'total_calls': 0,
            'agents': {}
        }
        
        # 收集各个agent的统计
        agents = [
            self.task_analysis_agent,
            self.executor_agent,
            self.task_summary_agent,
            self.planning_agent,
            self.observation_agent,
            self.direct_executor_agent,
            self.task_decompose_agent
        ]
        
        for agent in agents:
            if hasattr(agent, 'get_token_stats'):
                stats = agent.get_token_stats()
                all_stats[stats['agent_name']] = stats
                
                # 累加到总统计
                total_stats['total_input_tokens'] += stats['total_input_tokens']
                total_stats['total_output_tokens'] += stats['total_output_tokens']
                total_stats['total_cached_tokens'] += stats['total_cached_tokens']
                total_stats['total_reasoning_tokens'] += stats['total_reasoning_tokens']
                total_stats['total_calls'] += stats['total_calls']
                total_stats['agents'][stats['agent_name']] = stats
        
        return {
            'individual_stats': all_stats,
            'total_stats': total_stats
        }
    
    def print_comprehensive_token_stats(self, workflow_time: float):
        """
        打印所有Agent的综合Token使用统计（简化版本）
        
        Args:
            workflow_time: 整个工作流的执行时间
        """
        logger.info("📊 综合Token使用统计")
        
        # 收集所有agent的统计信息
        all_stats = []
        for agent in [self.task_analysis_agent, self.planning_agent, self.executor_agent, self.observation_agent, self.task_summary_agent]:
            if agent:
                stats = agent.get_token_stats()
                all_stats.append(stats)
        
        # 计算总体统计
        total = {
            'total_calls': sum(stats['total_calls'] for stats in all_stats),
            'total_input_tokens': sum(stats['total_input_tokens'] for stats in all_stats),
            'total_output_tokens': sum(stats['total_output_tokens'] for stats in all_stats),
            'total_cached_tokens': sum(stats['total_cached_tokens'] for stats in all_stats),
            'total_reasoning_tokens': sum(stats['total_reasoning_tokens'] for stats in all_stats)
        }
        
        logger.info(f"总计: {total['total_calls']}次调用, {total['total_input_tokens'] + total['total_output_tokens']:,}tokens, 耗时{workflow_time:.1f}s")
        
        # 简化的各Agent统计
        for stats in all_stats:
            if stats['total_calls'] > 0:
                agent_total = stats['total_input_tokens'] + stats['total_output_tokens']
                logger.info(f"  {stats['agent_name']}: {stats['total_calls']}次, {agent_total:,}tokens")

    def reset_all_token_stats(self):
        """
        重置所有agent的token统计
        """
        agents = [
            self.task_analysis_agent,
            self.executor_agent,
            self.task_summary_agent,
            self.planning_agent,
            self.observation_agent,
            self.direct_executor_agent,
            self.task_decompose_agent
        ]
        
        for agent in agents:
            if hasattr(agent, 'reset_token_stats'):
                agent.reset_token_stats()
        
        # 重置总体统计
        self.overall_token_stats = {
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'total_cached_tokens': 0,
            'total_reasoning_tokens': 0,
            'total_calls': 0,
            'total_execution_time': 0,
            'workflow_start_time': None,
            'workflow_end_time': None
        }
        
        logger.info("AgentController: 所有Token统计已重置")

    # ==================== 会话管理接口 ====================
    
    def interrupt_session(self, session_id: str, message: str = "用户请求中断") -> bool:
        """
        中断指定会话
        
        Args:
            session_id: 会话ID
            message: 中断消息
            
        Returns:
            bool: 是否成功请求中断
        """
        return self.session_manager.request_interrupt(session_id, message)
    
    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话状态
        
        Args:
            session_id: 会话ID
            
        Returns:
            Optional[Dict[str, Any]]: 会话信息，如果会话不存在则返回 None
        """
        return self.session_manager.get_session(session_id)
    
    def list_active_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有活跃会话
        
        Returns:
            List[Dict[str, Any]]: 会话信息列表
        """
        return self.session_manager.list_active_sessions()
    
    def cleanup_session(self, session_id: str) -> bool:
        """
        清理指定会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            bool: 是否成功清理
        """
        return self.session_manager.remove_session(session_id)
    
    def cleanup_old_sessions(self, max_age_seconds: int = 3600) -> int:
        """
        清理过期会话
        
        Args:
            max_age_seconds: 最大存活时间（秒）
            
        Returns:
            int: 清理的会话数量
        """
        return self.session_manager.cleanup_old_sessions(max_age_seconds)
    
    def is_session_running(self, session_id: str) -> bool:
        """
        检查会话是否正在运行
        
        Args:
            session_id: 会话ID
            
        Returns:
            bool: 会话是否正在运行
        """
        session = self.session_manager.get_session(session_id)
        return session and session['status'] == SessionStatus.RUNNING
    
    def get_session_phase(self, session_id: str) -> Optional[str]:
        """
        获取会话当前执行阶段
        
        Args:
            session_id: 会话ID
            
        Returns:
            Optional[str]: 当前执行阶段，如果会话不存在则返回 None
        """
        session = self.session_manager.get_session(session_id)
        return session.get('current_phase') if session else None

    def _save_session_state(self, session_id: str, system_context: Dict[str, Any]) -> None:
        """
        保存会话状态到文件
        
        Args:
            session_id: 会话ID
            system_context: 系统上下文
        """
        import json
        import os
        
        try:
            if session_id not in self._session_managers:
                logger.warning(f"AgentController: 会话 {session_id} 的管理器不存在，跳过保存")
                return
            
            # 获取会话管理器
            managers = self._session_managers[session_id]
            message_manager = managers['message_manager']
            task_manager = managers['task_manager']
            
            # 使用system_context中的file_workspace
            workspace_dir = system_context['file_workspace']
            os.makedirs(workspace_dir, exist_ok=True)
            
            # 保存MessageManager状态
            message_file = os.path.join(workspace_dir, "message_manager.json")
            if hasattr(message_manager, 'to_dict'):
                message_data = message_manager.to_dict()
            else:
                # 如果没有to_dict方法，保存核心数据
                message_data = {
                    'session_id': message_manager.session_id,
                    'messages': message_manager.get_all_messages(),
                    'max_token_limit': getattr(message_manager, 'max_token_limit', None),
                    'auto_merge_chunks': getattr(message_manager, 'auto_merge_chunks', None)
                }
            
            with open(message_file, 'w', encoding='utf-8') as f:
                json.dump(message_data, f, ensure_ascii=False, indent=2)
            logger.info(f"AgentController: 已保存MessageManager状态到 {message_file}")
            
            # 保存TaskManager状态
            task_file = os.path.join(workspace_dir, "task_manager.json")
            if hasattr(task_manager, 'to_dict'):
                task_data = task_manager.to_dict()
            else:
                # 如果没有to_dict方法，保存核心数据
                all_tasks = task_manager.get_all_tasks()
                task_data = {
                    'session_id': task_manager.session_id,
                    'next_task_number': getattr(task_manager, 'next_task_number', 1),
                    'tasks': [task.to_dict() if hasattr(task, 'to_dict') else str(task) for task in all_tasks]
                }
            
            with open(task_file, 'w', encoding='utf-8') as f:
                json.dump(task_data, f, ensure_ascii=False, indent=2)
            logger.info(f"AgentController: 已保存TaskManager状态到 {task_file}")
            
        except Exception as e:
            logger.error(f"AgentController: 保存会话状态失败: {str(e)}")
            raise

    def _save_llm_request_logs(self, session_id: str) -> None:
        """
        记录LLM请求完成情况（极简版本）
        
        Args:
            session_id: 会话ID
        """
        logger.debug(f"AgentController: 检查LLM请求记录 {session_id}")
        
        try:
            from agents.utils.llm_request_logger import get_llm_logger
            
            # 获取LLM记录器
            llm_logger = get_llm_logger(session_id)
            
            # 获取请求文件列表
            request_files = llm_logger.list_request_files()
            
            if len(request_files) > 0:
                logger.info(f"AgentController: LLM请求记录完成 - 总计 {len(request_files)} 个请求")
                
                # 打印简化的摘要信息
                self._print_llm_request_summary(session_id, self.workspace)
                
            else:
                logger.info(f"AgentController: 会话 {session_id} 无LLM请求记录")
                
        except Exception as e:
            logger.error(f"AgentController: 检查LLM请求记录 {session_id} 失败: {str(e)}")
            # 不抛出异常，避免影响主流程

    def _print_llm_request_summary(self, session_id: str, workspace_dir: str):
        """
        打印LLM请求记录摘要（简化版本）
        
        Args:
            session_id: 会话ID
            workspace_dir: 工作空间目录
        """
        try:
            logger.info(f"AgentController: 开始打印LLM请求摘要，session_id: {session_id}")
            
            from agents.utils.llm_request_logger import get_llm_logger
            llm_logger = get_llm_logger(session_id)
            request_files = llm_logger.list_request_files()
            
            logger.info(f"AgentController: 获取到 {len(request_files)} 个请求文件")
            logger.info(f"AgentController: request_files类型: {type(request_files)}")
            if request_files:
                logger.info(f"AgentController: 第一个文件信息: {request_files[0]}")
                logger.info(f"AgentController: 第一个文件类型: {type(request_files[0])}")
            
            if not request_files:
                logger.info("📊 LLM请求记录: 无记录")
                return
            
            # 统计智能体请求数量
            agent_stats = {}
            for i, file_info in enumerate(request_files):
                logger.info(f"AgentController: 处理第 {i+1} 个文件信息: {file_info}")
                logger.info(f"AgentController: file_info类型: {type(file_info)}")
                
                if isinstance(file_info, dict):
                    agent_name = file_info.get('agent_name', 'unknown')
                elif isinstance(file_info, str):
                    # 如果是文件路径字符串，读取JSON文件获取agent_name
                    try:
                        import json
                        import os
                        
                        if os.path.exists(file_info):
                            with open(file_info, 'r', encoding='utf-8') as f:
                                file_data = json.load(f)
                                agent_name = file_data.get('agent_name', 'unknown')
                                logger.info(f"AgentController: 从JSON文件读取agent_name: {agent_name}")
                        else:
                            logger.warning(f"AgentController: 文件不存在: {file_info}")
                            agent_name = 'unknown'
                    except Exception as e:
                        logger.warning(f"AgentController: 读取JSON文件失败: {str(e)}")
                        # 如果读取失败，尝试从文件名提取
                        import os
                        filename = os.path.basename(file_info)
                        logger.info(f"AgentController: 从文件名提取: {filename}")
                        
                        if '_' in filename:
                            parts = filename.split('_')
                            if len(parts) >= 3:
                                agent_name = parts[2]  # TaskAnalysisAgent
                            else:
                                agent_name = 'unknown'
                        else:
                            agent_name = 'unknown'
                else:
                    logger.info(f"AgentController: file_info是其他类型: {type(file_info)}")
                    agent_name = 'unknown'
                
                logger.info(f"AgentController: 最终提取的agent_name: {agent_name}")
                agent_stats[agent_name] = agent_stats.get(agent_name, 0) + 1
            
            logger.info(f"📊 LLM请求记录: {len(request_files)}个请求")
            for agent_name, count in sorted(agent_stats.items()):
                if count > 0:
                    logger.info(f"  • {agent_name}: {count}个请求")
                    
        except Exception as e:
            import traceback
            logger.warning(f"📊 LLM请求记录统计失败: {str(e)}")
            logger.warning(f"📊 LLM请求记录统计失败详情: {traceback.format_exc()}")
