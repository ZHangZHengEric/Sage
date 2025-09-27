import json
from math import log
import uuid
import re
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import datetime
import traceback
import time
import threading
from typing import List, Dict, Any, Optional, Generator, Union
from enum import Enum
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy
from sagents.agent.simple_agent import SimpleAgent,AgentBase
from sagents.agent.task_analysis_agent import TaskAnalysisAgent
from sagents.agent.task_decompose_agent import TaskDecomposeAgent
from sagents.agent.task_executor_agent import TaskExecutorAgent
from sagents.agent.task_obversation_agent import TaskObservationAgent
from sagents.agent.task_planning_agent import TaskPlanningAgent
from sagents.agent.task_summary_agent import TaskSummaryAgent
from sagents.agent.task_stage_summary_agent import TaskStageSummaryAgent
from sagents.agent.workflow_select_agent import WorkflowSelectAgent
from sagents.agent.simple_react_agent import SimpleReactAgent
from sagents.agent.query_suggest_agent import QuerySuggestAgent
from sagents.agent.task_rewrite_agent import TaskRewriteAgent
from sagents.agent.memory_extraction_agent import MemoryExtractionAgent
from sagents.agent.task_router_agent import TaskRouterAgent
from sagents.utils.logger import logger
from sagents.context.session_context import SessionContext,init_session_context,SessionStatus,get_session_context,delete_session_context,list_active_sessions
from sagents.context.messages.message import MessageChunk,MessageRole,MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.context.tasks.task_base import TaskBase, TaskStatus

class SAgent:
    """
    智能体容器
    
    负责协调多个智能体协同工作，管理任务执行流程，
    包括任务分析、规划、执行、观察和总结等阶段。
    """

    # 默认配置常量
    DEFAULT_MAX_LOOP_COUNT = 10
    DEFAULT_MESSAGE_LIMIT = 10000

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", workspace: str = "/tmp/sage", memory_root: str = None):
        """
        初始化智能体控制器
        
        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
            workspace: 工作空间根目录，默认为 /tmp/sage
            memory_root: 记忆存储根目录，默认为 workspace/user_memories
        """
        self.model = model
        self.model_config = model_config
        self.system_prefix = system_prefix
        self.workspace = workspace
        self.memory_root = memory_root  # 如果为None则不使用本地记忆工具
        self._init_agents()
                
        logger.info("SAgent: 智能体控制器初始化完成")

    def _init_agents(self) -> None:
        """
        初始化所有必需的智能体
        
        使用共享的模型实例为所有智能体进行初始化。
        """
        logger.debug("SAgent: 初始化各类智能体")
        
        # self.simple_agent = SimpleAgent(
        #     self.model, self.model_config, system_prefix=self.system_prefix
        # )
        self.simple_agent = SimpleAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.task_analysis_agent = TaskAnalysisAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.task_decompose_agent = TaskDecomposeAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.task_executor_agent = TaskExecutorAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.task_observation_agent = TaskObservationAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.task_planning_agent = TaskPlanningAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.task_summary_agent = TaskSummaryAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.task_stage_summary_agent = TaskStageSummaryAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.workflow_select_agent = WorkflowSelectAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.query_suggest_agent = QuerySuggestAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.task_rewrite_agent = TaskRewriteAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.memory_extraction_agent = MemoryExtractionAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        self.task_router_agent = TaskRouterAgent(
            self.model, self.model_config, system_prefix=self.system_prefix
        )
        
        logger.info("SAgent: 所有智能体初始化完成")

    def run_stream(self, 
        input_messages: Union[List[Dict[str, Any]], List[MessageChunk]], 
        tool_manager: Optional[Union[ToolManager, ToolProxy]] = None, 
        session_id: Optional[str] = None, 
        user_id: Optional[str] = None,
        deep_thinking: bool = None, 
        max_loop_count: int = DEFAULT_MAX_LOOP_COUNT,
        multi_agent: bool = None,
        more_suggest: bool = False,
        system_context: Optional[Dict[str, Any]] = None,
        available_workflows: Optional[Dict[str, Any]] = {}) -> Generator[List['MessageChunk'], None, None]:
        """
        执行智能体任务的主流程
        
        Args:
            input_messages: 输入消息列表
            tool_manager: 工具管理器实例
            session_id: 会话ID
            user_id: 用户ID
            deep_thinking: 是否开启深度思考
            max_loop_count: 最大循环次数
            multi_agent: 是否开启多智能体模式
            more_suggest: 是否开启更多建议
            system_context: 系统上下文
            available_workflows: 可用工作流列表
        
        Yields:
            消息块列表
        """
        try:
            # 初始化会话
            session_id = session_id or str(uuid.uuid4())
            # 初始化该session 的context 管理器
            session_context = init_session_context(session_id,user_id=user_id, workspace_root= self.workspace, memory_root= self.memory_root)
            logger.info(f"开始流式工作流，会话ID: {session_id}")

            if system_context:
                logger.info(f"SAgent: 设置了system_context参数: {list(system_context.keys())}")
                session_context.add_and_update_system_context(system_context)
            
            if available_workflows:
                if len(available_workflows.keys()) > 0:
                    logger.info(f"SAgent: 提供了 {len(available_workflows)} 个工作流模板: {list(available_workflows.keys())}")
                    session_context.workflow_manager.load_workflows_from_dict(available_workflows)

            session_context.status = SessionStatus.RUNNING
            initial_messages = self._prepare_initial_messages(input_messages)
            
            # 尝试初始化记忆
            session_context.init_user_memory_manager(tool_manager)
            
            # print(f"initial_messages: {initial_messages}")
            # print(f"session_context.message_manager.messages: {session_context.message_manager.messages}")

            # 判断initial_messages 的message 是否已经存在，没有的话添加，通过message_id 来进行判断
            for message in initial_messages:
                if message.message_id not in [m.message_id for m in session_context.message_manager.messages]:
                    session_context.message_manager.add_messages(message)

            

            # 先检查历史对话的文本长度，如果超过一定30000token 则用一下rewrite
            # if session_context.message_manager.get_all_messages_content_length() > 30000:
            #     for message_chunks in self._execute_agent_phase(
            #         session_context=session_context,
            #         tool_manager=tool_manager,
            #         session_id=session_id,
            #         agent=self.task_rewrite_agent,
            #         phase_name="任务重写"
            #     ):
            #         session_context.message_manager.add_messages(message_chunks)
            #         yield message_chunks


            # 检查WorkflowManager中是否有工作流
            if session_context.workflow_manager.list_workflows():
                if len(session_context.workflow_manager.list_workflows()) > 5:
                    for message_chunks in self._execute_agent_phase(
                            session_context=session_context,
                            tool_manager=tool_manager,
                            session_id=session_id,
                            agent=self.workflow_select_agent,
                            phase_name="工作流选择"
                        ):
                            session_context.message_manager.add_messages(message_chunks)
                            yield message_chunks
                else:
                    session_context.add_and_update_system_context({'workflow_guidance': session_context.workflow_manager.format_workflows_for_context(session_context.workflow_manager.list_workflows())})
            
            # 当deep_thinking 或者 multi_agent 为None，其一为none时，调用task router
            if deep_thinking is None or multi_agent is None:
                for message_chunks in self._execute_agent_phase(
                    session_context=session_context,
                    tool_manager=tool_manager,
                    session_id=session_id,
                    agent=self.task_router_agent,
                    phase_name="任务路由"
                ):
                    session_context.message_manager.add_messages(message_chunks)
                    yield message_chunks

            if deep_thinking is None:
                deep_thinking = session_context.audit_status.get('deep_thinking', False)

            if multi_agent is None:
                router_agent = session_context.audit_status.get('router_agent', "单智能体")
                multi_agent = router_agent != "单智能体"

            # 1. 任务分析阶段
            if deep_thinking:
                for message_chunks in self._execute_agent_phase(
                    session_context=session_context,
                    tool_manager=tool_manager,
                    session_id=session_id,
                    agent=self.task_analysis_agent,
                    phase_name="任务分析"
                ):
                    session_context.message_manager.add_messages(message_chunks)
                    yield message_chunks
                    
            if multi_agent:
                for message_chunks in self._execute_multi_agent_workflow(
                    session_context=session_context,
                    tool_manager=tool_manager,
                    session_id=session_id,
                    max_loop_count=max_loop_count
                ):
                    session_context.message_manager.add_messages(message_chunks)
                    yield message_chunks
            else:
                # 直接执行模式：可选的任务分析 + 直接执行
                logger.info("SAgent: 开始简化工作流")                
                for message_chunks in self._execute_agent_phase(
                    session_context=session_context,
                    tool_manager=tool_manager,
                    session_id=session_id,
                    agent=self.simple_agent,
                    phase_name="直接执行"
                ):
                    session_context.message_manager.add_messages(message_chunks)
                    yield message_chunks
                yield from self._execute_agent_phase(session_context, tool_manager, session_id, self.task_summary_agent, "任务总结")
            if more_suggest:
                for message_chunks in self._execute_agent_phase(
                    session_context=session_context,
                    tool_manager=tool_manager,
                    session_id=session_id,
                    agent=self.query_suggest_agent,
                    phase_name="查询建议"
                ):
                    session_context.message_manager.add_messages(message_chunks)
                    yield message_chunks

            logger.debug(f"SAgent: 检查是否需要提取记忆")            
            if session_context.user_memory_manager:
                logger.debug(f"SAgent: 开始记忆提取")
                for message_chunks in self._execute_agent_phase(
                    session_context=session_context,
                    tool_manager=tool_manager,
                    session_id=session_id,
                    agent=self.memory_extraction_agent,
                    phase_name="记忆提取"
                ):
                    session_context.message_manager.add_messages(message_chunks)
                    # yield message_chunks

            # 检查最终状态，如果不是中断状态则标记为完成
            if session_context.status != SessionStatus.INTERRUPTED:
                session_context.status = SessionStatus.COMPLETED
                logger.info(f"SAgent: 流式工作流完成，会话ID: {session_id}")
            else:
                logger.info(f"SAgent: 流式工作流被中断，会话ID: {session_id}")
            
        except Exception as e:
            # 标记会话错误
            logger.error(f"traceback: {traceback.format_exc()}")
            session_context.status = SessionStatus.ERROR
            yield from self._handle_workflow_error(e)
        finally:
            # 保存会话状态到文件
            try:
                session_context.save()
            except Exception as save_error:
                logger.error(f"traceback: {traceback.format_exc()}")
                logger.error(f"SAgent: 保存会话状态 {session_id} 时出错: {save_error}")
            
            # 清理会话，防止内存泄漏
            try:
                delete_session_context(session_id)
                logger.info(f"SAgent: 已清理会话 {session_id}")
            except Exception as cleanup_error:
                logger.error(f"SAgent: 清理会话 {session_id} 时出错: {cleanup_error}")

    def _execute_multi_agent_workflow(self, 
                                     session_context: SessionContext,
                                     tool_manager: Optional[Any],
                                     session_id: str,
                                     max_loop_count: int) -> Generator[List[MessageChunk], None, None]:
        # 执行任务分解
        yield from self._execute_agent_phase(session_context, tool_manager, session_id, self.task_decompose_agent, "任务分解")
        current_completed_tasks= session_context.task_manager.get_tasks_by_status(TaskStatus.COMPLETED)
        loop_count = 0
        while True:
            loop_count += 1
            logger.info(f"SAgent: 开始第 {loop_count} 轮循环")
            if session_context.status == SessionStatus.INTERRUPTED:
                logger.info(f"SAgent: 主循环第 {loop_count} 轮被中断，会话ID: {session_id}")
                return  
            
            if loop_count >= max_loop_count:
                logger.info(f"SAgent: 主循环已达到最大轮数 {max_loop_count}，会话ID: {session_id}")
                break
            yield from self._execute_agent_phase(session_context, tool_manager, session_id, self.task_planning_agent, "任务规划")
            
            yield from self._execute_agent_phase(session_context, tool_manager, session_id, self.task_executor_agent, "任务执行")
            
            yield from self._execute_agent_phase(session_context, tool_manager, session_id, self.task_observation_agent, "任务观察")
            if session_context.status == SessionStatus.INTERRUPTED:
                logger.info(f"SAgent: 规划-执行-观察循环第 {loop_count} 轮被中断，会话ID: {session_id}")
                return
            # 从message 中查看observation 信息
            now_completed_tasks= session_context.task_manager.get_tasks_by_status(TaskStatus.COMPLETED)
            if len(now_completed_tasks) > len(current_completed_tasks):
                logger.info(f"SAgent: 检测到任务状态变化，完成任务数从 {len(current_completed_tasks)} 增加到 {len(now_completed_tasks)}")
                yield from self._execute_agent_phase(session_context, tool_manager, session_id, self.task_stage_summary_agent, "任务阶段总结")
                current_completed_tasks = now_completed_tasks

            # 从任务管理器当前的最新状态，如果完成的任务数与失败的任务数之和等于总任务数，将 observation_result 的completion_status 设为 completed
            completed_tasks = session_context.task_manager.get_tasks_by_status(TaskStatus.COMPLETED)
            failed_tasks = session_context.task_manager.get_tasks_by_status(TaskStatus.FAILED)
            # 判断是否需要继续执行

            if len(completed_tasks) + len(failed_tasks) == len(session_context.task_manager.get_all_tasks()):
                logger.info(f"SAgent: 所有任务已完成，会话ID: {session_id}")
                break
            
            if "all_observations" not in session_context.audit_status:
                continue
            if len(session_context.audit_status['all_observations']) == 0:
                continue

            observation_dict = session_context.audit_status['all_observations'][-1]
            if observation_dict:
                if observation_dict.get("is_completed",False) == True:
                    logger.info(f"SAgent: 规划-执行-观察循环完成，会话ID: {session_id}")
                    break
                elif observation_dict.get('needs_more_input',False) == True:
                    logger.info(f"SAgent: 规划-执行-观察循环需要更多输入，会话ID: {session_id}")
                    user_query = observation_dict.get('user_query', '')
                    if user_query:
                        clarify_msg = MessageChunk(
                            content=user_query,
                            message_id=str(uuid.uuid4()),
                            role=MessageRole.ASSISTANT.value,
                            show_content=user_query + '\n',
                            message_type=MessageType.FINAL_ANSWER.value
                        )
                        yield [clarify_msg]
                    break
        
        # 执行任务总结
        yield from self._execute_agent_phase(session_context, tool_manager, session_id, self.task_summary_agent, "任务总结")

    def _execute_agent_phase(self,
                             session_context: SessionContext,
                             tool_manager: Optional[Any],
                             session_id: str,
                             agent: AgentBase,
                             phase_name: str):
        logger.info(f"SAgent: 使用 {agent.agent_description} 智能体")
        # 检查中断
        if session_context.status == SessionStatus.INTERRUPTED:
            logger.info(f"SAgent: {phase_name} 阶段被中断，会话ID: {session_id}")
            return
        
        for chunk in agent.run_stream(
            session_context=session_context,
            tool_manager=tool_manager,
            session_id=session_id,
        ):
            # 在每个块之间检查中断
            if session_context.status == SessionStatus.INTERRUPTED:
                logger.info(f"SAgent: {phase_name} 阶段在块处理中被中断，会话ID: {session_id}")
                return
            yield chunk
        
        logger.info(f"SAgent: {phase_name} 阶段完成")

    def _prepare_initial_messages(self, input_messages: Union[List[Dict[str, Any]], List[MessageChunk]]) -> List[MessageChunk]:
        """
        准备初始消息
        
        Args:
            input_messages: 输入消息列表
            
        Returns:
            List[MessageChunk]: 准备好的消息列表
        """
        logger.debug("SAgent: 准备初始消息")
        # 先检查input_message 格式以及类型
        if not isinstance(input_messages, list):
            raise ValueError("input_messages 必须是列表类型")
        # 检查每个消息的格式
        for msg in input_messages:
            if not isinstance(msg, (dict, MessageChunk)):
                raise ValueError("每个消息必须是字典或MessageChunk类型")
        # 对dict 的消息输入，转化成MessageChunk
        input_messages = [MessageChunk(**msg) if isinstance(msg, dict) else msg for msg in input_messages]        
        # 清理过长的消息历史
        logger.info(f"SAgent: 初始化消息数量: {len(input_messages)}")
        return input_messages
    
    def _handle_workflow_error(self, error: Exception) -> Generator[List[MessageChunk], None, None]:
        """
        处理工作流执行错误
        
        Args:
            error: 发生的异常
            
        Yields:
            List[MessageChunk]: 错误消息块
        """
        logger.error(f"SAgent: 处理工作流错误: {str(error)}\n{traceback.format_exc()}")
        
        error_message = f"工作流执行失败: {str(error)}"
        message_id = str(uuid.uuid4())
        
        yield [MessageChunk(
            role='assistant',
            content=error_message,
            type='final_answer',
            message_id=message_id,
            show_content=error_message
        )]
    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        
        session_context_ = get_session_context(session_id) 
        if session_context_:
            return session_context_.status
        return None
    
    def list_active_sessions(self) -> List[Dict[str, Any]]:
        
        return list_active_sessions()
    
    def cleanup_session(self, session_id: str) -> bool:
        
        return delete_session_context(session_id)

    def interrupt_session(self, session_id: str, message: str = "用户请求中断") -> bool:
        session_context_ = get_session_context(session_id=session_id)
        if session_context_:
            session_context_.status = SessionStatus.INTERRUPTED
            return True
        return False
    
    def get_tasks_status(self,session_id: str) -> Optional[Dict[str, Any]]:
        session_context_ = get_session_context(session_id=session_id)
        if session_context_:
            return session_context_.task_manager.to_dict()
        return None
    

