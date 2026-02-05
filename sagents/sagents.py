from sagents.context.session_context import (
    SessionContext,
    init_session_context,
    SessionStatus,
    get_session_context,
    delete_session_context,
    list_active_sessions,
    get_session_run_lock,
    delete_session_run_lock,
)
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.tasks.task_base import TaskStatus
from sagents.context.session_context_manager import session_manager
from sagents.utils.logger import logger
from sagents.agent import (
    TaskRouterAgent,
    TaskRewriteAgent,
    QuerySuggestAgent,
    TaskCompletionJudgeAgent,
    WorkflowSelectAgent,
    TaskStageSummaryAgent,
    TaskSummaryAgent,
    TaskPlanningAgent,
    TaskObservationAgent,
    TaskExecutorAgent,
    TaskDecomposeAgent,
    TaskAnalysisAgent,
    SimpleAgent,
    AgentBase,
)
from sagents.tool import ToolManager, ToolProxy
from sagents.skill import SkillManager, SkillProxy
from sagents.context.user_memory import UserMemoryManager, MemoryExtractor
from sagents.observability import ObservabilityManager, OpenTelemetryTraceHandler, AgentRuntime, ObservableAsyncOpenAI
from typing import List, Dict, Any, Optional, Union, AsyncGenerator, Type
import time
import traceback
import uuid
import os
import sys
import asyncio
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class SAgent:
    """
    智能体容器

    负责协调多个智能体协同工作，管理任务执行流程，
    包括任务分析、规划、执行、观察和总结等阶段。
    """

    def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = "", workspace: str = "/tmp/sage", memory_type: str = "session", enable_obs: bool = True):
        """
        初始化智能体控制器

        Args:
            model: 语言模型实例
            model_config: 模型配置参数
            system_prefix: 系统前缀提示
            workspace: 工作空间根目录，默认为 /tmp/sage
            memory_type: 记忆类型，默认为 "session" (会话记忆), 可选 "user" (用户记忆)
            enable_obs: 是否启用可观察性，默认为 True
        """
        self.model = model
        self.model_config = model_config
        self.system_prefix = system_prefix
        self.workspace = workspace
        # 初始化全局用户记忆管理器
        if memory_type == "user":
            self.user_memory_manager = UserMemoryManager(model=self.model, workspace=workspace)
        else:
            logger.info(f"SAgent: 记忆类型为 {memory_type}，将禁用用户记忆功能")
            self.user_memory_manager = None
        
        # 懒加载代理缓存
        self._agents = {}

        self.observability_manager = None # Initialize to None
        if enable_obs:
            # 初始化观测性管理器
            otel_handler = OpenTelemetryTraceHandler(service_name="sagents")
            self.observability_manager = ObservabilityManager(handlers=[otel_handler])
            # 包装模型以支持可观测性
            # 注意：这会拦截 self.model 的调用以记录 LLM 事件
            self.model = ObservableAsyncOpenAI(self.model, self.observability_manager)
            
        logger.info("SAgent: 智能体控制器初始化完成 (Lazy Loading Enabled)")

    def _get_agent(self, agent_cls: Type[AgentBase], name: str) -> AgentBase:
        if name not in self._agents:
            agent = agent_cls(self.model, self.model_config, system_prefix=self.system_prefix)
            if self.observability_manager:
                agent = AgentRuntime(agent, self.observability_manager)
            self._agents[name] = agent
        return self._agents[name]

    @property
    def simple_agent(self):
        return self._get_agent(SimpleAgent, "simple_agent")

    @property
    def task_analysis_agent(self):
        return self._get_agent(TaskAnalysisAgent, "task_analysis_agent")

    @property
    def task_decompose_agent(self):
        return self._get_agent(TaskDecomposeAgent, "task_decompose_agent")

    @property
    def task_executor_agent(self):
        return self._get_agent(TaskExecutorAgent, "task_executor_agent")

    @property
    def task_observation_agent(self):
        return self._get_agent(TaskObservationAgent, "task_observation_agent")

    @property
    def task_completion_judge_agent(self):
        return self._get_agent(TaskCompletionJudgeAgent, "task_completion_judge_agent")

    @property
    def task_planning_agent(self):
        return self._get_agent(TaskPlanningAgent, "task_planning_agent")

    @property
    def task_summary_agent(self):
        return self._get_agent(TaskSummaryAgent, "task_summary_agent")

    @property
    def task_stage_summary_agent(self):
        return self._get_agent(TaskStageSummaryAgent, "task_stage_summary_agent")

    @property
    def workflow_select_agent(self):
        return self._get_agent(WorkflowSelectAgent, "workflow_select_agent")

    @property
    def query_suggest_agent(self):
        return self._get_agent(QuerySuggestAgent, "query_suggest_agent")

    @property
    def task_rewrite_agent(self):
        return self._get_agent(TaskRewriteAgent, "task_rewrite_agent")

    @property
    def task_router_agent(self):
        return self._get_agent(TaskRouterAgent, "task_router_agent")

    async def run_stream(
        self,
        input_messages: Union[List[Dict[str, Any]], List[MessageChunk]],
        tool_manager: Optional[Union[ToolManager, ToolProxy]] = None,
        skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        deep_thinking: Optional[Union[bool, str]] = None,
        max_loop_count: int = 10,
        multi_agent: Optional[bool] = None,
        more_suggest: bool = False,
        force_summary: bool = False,
        system_context: Optional[Dict[str, Any]] = None,
        available_workflows: Optional[Dict[str, Any]] = {},
        context_budget_config: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[List["MessageChunk"], None]:

        # 确保 session_id 存在，用于 trace
        session_id = session_id or str(uuid.uuid4())

        # 开启 Chain Trace
        if self.observability_manager:
            self.observability_manager.on_chain_start(session_id=session_id, input_data=input_messages)

        try:
            # 统计耗时：首个非空 show_content 与完整执行总耗时
            _start_time = time.time()
            _first_show_time = None

            # 调用内部方法执行流式处理，对结果进行过滤
            async for message_chunks in self.run_stream_internal(
                input_messages=input_messages,
                tool_manager=tool_manager,
                skill_manager=skill_manager,
                session_id=session_id,
                user_id=user_id,
                deep_thinking=deep_thinking,
                max_loop_count=max_loop_count,
                multi_agent=multi_agent,
                more_suggest=more_suggest,
                force_summary=force_summary,
                system_context=system_context,
                available_workflows=available_workflows,
                context_budget_config=context_budget_config,
            ):
                # 过滤掉空消息块
                for message_chunk in message_chunks:
                    # 记录首个 show_content 不为空的耗时
                    if _first_show_time is None:
                        try:
                            sc = getattr(message_chunk, "show_content", None)
                            if sc and str(sc).strip():
                                _first_show_time = time.time()
                                _delta_ms = int((_first_show_time - _start_time) * 1000)
                                logger.info(f"SAgent: 会话 {session_id} 首个可显示内容耗时 {_delta_ms} ms")
                        except Exception as _e:
                            logger.error(f"SAgent: 统计首个show_content耗时出错: {_e}\n{traceback.format_exc()}")
                    if message_chunk.content or message_chunk.show_content or message_chunk.tool_calls or message_chunk.type == MessageType.TOKEN_USAGE.value:
                        yield [message_chunk]

            # 流结束后记录完整执行总耗时
            _end_time = time.time()
            _total_ms = int((_end_time - _start_time) * 1000)
            logger.info(f"SAgent: 会话 {session_id} 完整执行耗时 {_total_ms} ms", session_id)
            # 结束 Chain Trace
            if self.observability_manager:
                self.observability_manager.on_chain_end(output_data={"status": "finished"}, session_id=session_id)

        except Exception as e:
            # 记录 Chain Error
            if self.observability_manager:
                self.observability_manager.on_chain_error(e, session_id=session_id)
            raise e

    async def run_stream_internal(
        self,
        input_messages: Union[List[Dict[str, Any]], List[MessageChunk]],
        tool_manager: Optional[Union[ToolManager, ToolProxy]] = None,
        skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        deep_thinking: Optional[Union[bool, str]] = None,
        max_loop_count: int = 10,
        multi_agent: Optional[bool] = None,
        more_suggest: bool = False,
        force_summary: bool = False,
        system_context: Optional[Dict[str, Any]] = None,
        available_workflows: Optional[Dict[str, Any]] = {},
        context_budget_config: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[List["MessageChunk"], None]:
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
            context_budget_config: 上下文预算管理器配置，包含以下键：
                - max_model_len: 模型最大token长度
                - history_ratio: 历史消息的比例（0-1之间），默认 0.2 (20%)
                - active_ratio: 活跃消息的比例（0-1之间），默认 0.3 (30%)
                - max_new_message_ratio: 新消息的比例（0-1之间），默认 0.5 (50%)
                - recent_turns: 限制最近的对话轮数，0表示不限制，默认 0

        Yields:
            消息块列表
        """
        session_context = None
        try:
            # 初始化会话
            # 初始化该session 的context 管理器
            session_id = session_id or str(uuid.uuid4())
            session_context = init_session_context(
                session_id=session_id,
                user_id=user_id,
                workspace_root=self.workspace,
                context_budget_config=context_budget_config,
                user_memory_manager=self.user_memory_manager,
                tool_manager=tool_manager,
                skill_manager=skill_manager,
            )
            with session_manager.session_context(session_id):
                logger.info(f"开始流式工作流，会话ID: {session_id}")

                # 1. 设置传入的 system_context
                if system_context:
                    try:
                        logger.info(f"SAgent: 设置了system_context参数 keys: {list(system_context.keys())}")
                    except Exception:
                        logger.info("SAgent: 设置了system_context参数 (content unprintable)")
                    session_context.add_and_update_system_context(system_context)

                # 2. 尝试初始化记忆 (这将更新 session_context.system_context 中的用户偏好)
                await session_context.init_user_memory_context()

                # 3.1 加载工作流
                if available_workflows:
                    logger.info(f"SAgent: 提供了 {len(available_workflows)} 个工作流模板: {list(available_workflows.keys())}")
                    session_context.workflow_manager.load_workflows_from_dict(available_workflows)
                # 4. 设置agent配置信息到SessionContext
                session_context.set_agent_config(
                    model=self.model,
                    model_config=self.model_config,
                    system_prefix=self.system_prefix,
                    available_tools=tool_manager.list_all_tools_name() if tool_manager else [],
                    system_context=session_context.system_context,  # 使用最新的完整上下文
                    available_workflows=available_workflows,
                    deep_thinking=deep_thinking if isinstance(deep_thinking, bool) else False,
                    multi_agent=multi_agent if isinstance(multi_agent, bool) else False,
                    more_suggest=more_suggest,
                    max_loop_count=max_loop_count,
                )

                session_context.status = SessionStatus.RUNNING
                initial_messages = self._prepare_initial_messages(input_messages)

                # 判断initial_messages 的message 是否已经存在，没有的话添加，通过message_id 来进行判断
                logger.info(f"SAgent: 合并前message_manager的消息数量：{len(session_context.message_manager.messages)}")
                all_message_ids = [m.message_id for m in session_context.message_manager.messages]
                for message in initial_messages:
                    if message.message_id not in all_message_ids:
                        session_context.message_manager.add_messages(message)
                    else:
                        # 如果message 存在，更新，以新的message 为准
                        session_context.message_manager.update_messages(message)

                logger.info(f"SAgent: 合并后message_manager的消息数量：{len(session_context.message_manager.messages)}")

                # 准备历史上下文：分割、BM25重排序、预算限制并保存到system_context
                session_context.set_history_context()

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
                        async for message_chunks in self._execute_agent_phase(
                            session_context=session_context, tool_manager=tool_manager, session_id=session_id, agent=self.workflow_select_agent, phase_name="工作流选择"
                        ):
                            if len(message_chunks) > 0:
                                session_context.message_manager.add_messages(message_chunks)
                            yield message_chunks
                    else:
                        session_context.add_and_update_system_context(
                            {"workflow_guidance": session_context.workflow_manager.format_workflows_for_context(session_context.workflow_manager.list_workflows())}
                        )

                # 当deep_thinking 或者 multi_agent 为None，其一为none时，调用task router
                if deep_thinking is None or multi_agent is None:
                    async for message_chunks in self._execute_agent_phase(
                        session_context=session_context, tool_manager=tool_manager, session_id=session_id, agent=self.task_router_agent, phase_name="任务路由"
                    ):
                        session_context.message_manager.add_messages(message_chunks)
                        yield message_chunks

                if deep_thinking is None:
                    deep_thinking = session_context.audit_status.get("deep_thinking", False)

                if multi_agent is None:
                    router_agent = session_context.audit_status.get("router_agent", "单智能体")
                    multi_agent = router_agent != "单智能体"

                # 1. 任务分析阶段
                if deep_thinking:
                    async for message_chunks in self._execute_agent_phase(
                        session_context=session_context, tool_manager=tool_manager, session_id=session_id, agent=self.task_analysis_agent, phase_name="任务分析"
                    ):
                        session_context.message_manager.add_messages(message_chunks)
                        yield message_chunks

                # 2. 多智能体工作流阶段
                if multi_agent:
                    async for message_chunks in self._execute_multi_agent_workflow(session_context=session_context, tool_manager=tool_manager, session_id=session_id, max_loop_count=max_loop_count):
                        session_context.message_manager.add_messages(message_chunks)
                        yield message_chunks
                else:
                    # 直接执行模式：可选的任务分析 + 直接执行
                    logger.info("SAgent: 开始简化工作流")

                    async for message_chunks in self._execute_agent_phase(
                        session_context=session_context, tool_manager=tool_manager, session_id=session_id, agent=self.simple_agent, phase_name="直接执行"
                    ):
                        session_context.message_manager.add_messages(message_chunks)
                        yield message_chunks

                    if force_summary:
                        async for message_chunks in self._execute_agent_phase(session_context, tool_manager, session_id, self.task_summary_agent, "任务总结"):
                            session_context.message_manager.add_messages(message_chunks)
                            yield message_chunks

                if more_suggest:
                    async for message_chunks in self._execute_agent_phase(
                        session_context=session_context, tool_manager=tool_manager, session_id=session_id, agent=self.query_suggest_agent, phase_name="查询建议"
                    ):
                        session_context.message_manager.add_messages(message_chunks)
                        yield message_chunks

                # 异步执行记忆提取，不阻塞主流程
                logger.info("SAgent: 检查是否需要提取记忆")
                if session_context.user_memory_manager and session_context.user_memory_manager.is_enabled():
                    logger.info("SAgent: 启动异步记忆提取任务")
                    extractor = MemoryExtractor(self.model)
                    # 创建异步任务，不等待其完成
                    asyncio.create_task(extractor.extract_and_save(session_context=session_context, session_id=session_id))

                # 检查最终状态，如果不是中断状态则标记为完成
                if session_context.status != SessionStatus.INTERRUPTED:
                    session_context.status = SessionStatus.COMPLETED
                    logger.info(f"SAgent: 流式工作流完成，会话ID: {session_id}")
                else:
                    logger.info(f"SAgent: 流式工作流被中断，会话ID: {session_id}")

        except Exception as e:
            # 标记会话错误
            if session_context:
                session_context.status = SessionStatus.ERROR
                async for message_chunks in self._handle_workflow_error(e):
                    session_context.message_manager.add_messages(message_chunks)
                    yield message_chunks
            else:
                 logger.error(f"Failed to initialize session: {e}")
                 # You might want to yield an error message here even without session context
                 yield [MessageChunk(
                     role="assistant", 
                     content=f"Error initializing session: {str(e)}", 
                     type="text"
                 )]
        finally:
            # 保存会话状态
            if session_context:
                try:
                    logger.info(f"SAgent: 会话状态保存 {session_id}")
                    session_context.save()
                except Exception as e:
                    logger.error(f"SAgent: 保存会话状态 {session_id} 时出错: {e}")
            # 生成 token_usage（注意：yield 在 cleanup 前）
            try:
                chunks = await self._emit_token_usage_if_any(session_context, session_id)
                if chunks:
                    yield chunks
            finally:
                # 无论如何都清理
                await self._cleanup_session(session_id or "")

    async def _execute_multi_agent_workflow(self, session_context: SessionContext, tool_manager: Optional[Any], session_id: str, max_loop_count: int) -> AsyncGenerator[List[MessageChunk], None]:
        """
        执行多智能体工作流
        """
        # 执行任务分解
        async for chunk in self._execute_agent_phase(session_context, tool_manager, session_id, self.task_decompose_agent, "任务分解"):
            yield chunk
        current_completed_tasks = session_context.task_manager.get_tasks_by_status(TaskStatus.COMPLETED)
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
            async for chunk in self._execute_agent_phase(session_context, tool_manager, session_id, self.task_planning_agent, "任务规划"):
                yield chunk

            async for chunk in self._execute_agent_phase(session_context, tool_manager, session_id, self.task_executor_agent, "任务执行"):
                yield chunk

            async for chunk in self._execute_agent_phase(session_context, tool_manager, session_id, self.task_observation_agent, "任务观察"):
                yield chunk

            async for chunk in self._execute_agent_phase(session_context, tool_manager, session_id, self.task_completion_judge_agent, "任务完成判断"):
                yield chunk
            if session_context.status == SessionStatus.INTERRUPTED:
                logger.info(f"SAgent: 规划-执行-观察循环第 {loop_count} 轮被中断，会话ID: {session_id}")
                return
            # 从message 中查看observation 信息
            now_completed_tasks = session_context.task_manager.get_tasks_by_status(TaskStatus.COMPLETED)
            if len(now_completed_tasks) > len(current_completed_tasks):
                logger.info(f"SAgent: 检测到任务状态变化，完成任务数从 {len(current_completed_tasks)} 增加到 {len(now_completed_tasks)}")
                async for chunk in self._execute_agent_phase(session_context, tool_manager, session_id, self.task_stage_summary_agent, "任务阶段总结"):
                    yield chunk
                current_completed_tasks = now_completed_tasks

            # 从任务管理器当前的最新状态，如果完成的任务数与失败的任务数之和等于总任务数，将 observation_result 的completion_status 设为 completed
            completed_tasks = session_context.task_manager.get_tasks_by_status(TaskStatus.COMPLETED)
            failed_tasks = session_context.task_manager.get_tasks_by_status(TaskStatus.FAILED)

            # 判断是否需要继续执行
            if len(completed_tasks) + len(failed_tasks) == len(session_context.task_manager.get_all_tasks()):
                logger.info(
                    f"SAgent: 规划-执行-观察循环完成，通过判断任务管理器中所有任务状态，完成任务数 {len(completed_tasks)} 加上失败任务数 {len(failed_tasks)} 等于总任务数 {len(session_context.task_manager.get_all_tasks())}，会话ID: {session_id}"
                )
                break
            if "completion_status" not in session_context.audit_status:
                continue
            if session_context.audit_status["completion_status"] in ["completed", "need_user_input", "failed"]:
                logger.info(f"SAgent: 规划-执行-观察循环完成，会话ID: {session_id}，完成状态: {session_context.audit_status['completion_status']}")
                break
        # 执行任务总结
        async for chunk in self._execute_agent_phase(session_context, tool_manager, session_id, self.task_summary_agent, "任务总结"):
            yield chunk

    async def _execute_agent_phase(self, session_context: SessionContext, tool_manager: Optional[Any], session_id: str, agent: AgentBase, phase_name: str) -> AsyncGenerator[List[MessageChunk], None]:
        """
        执行智能体阶段
        """
        logger.info(f"SAgent: 使用 {agent.agent_name} 智能体")
        # 检查中断
        if session_context.status == SessionStatus.INTERRUPTED:
            logger.info(f"SAgent: {phase_name} 阶段被中断，会话ID: {session_id}")
            return

        async for chunk in agent.run_stream(
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
        # 检查每个消息的格式
        for msg in input_messages:
            if not isinstance(msg, (dict, MessageChunk)):
                raise ValueError("每个消息必须是字典或MessageChunk类型")
        # 对dict 的消息输入，转化成MessageChunk
        input_messages = [MessageChunk(**msg) if isinstance(msg, dict) else msg for msg in input_messages]
        # 清理过长的消息历史
        logger.info(f"SAgent: 初始化消息数量: {len(input_messages)}")
        return input_messages

    async def _handle_workflow_error(self, error: Exception) -> AsyncGenerator[List[MessageChunk], None]:
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

        yield [MessageChunk(role="assistant", content=error_message, type="final_answer", message_id=message_id, show_content=error_message)]

    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:

        session_context_ = get_session_context(session_id)
        if session_context_:
            return {"status": session_context_.status}
        return None

    def list_active_sessions(self) -> List[Dict[str, Any]]:
        return list_active_sessions()

    def cleanup_session(self, session_id: str) -> bool:
        return delete_session_context(session_id)

    def save_session(self, session_id: str) -> bool:
        # 保存会话状态到文件
        session_context_ = get_session_context(session_id=session_id)
        if not session_context_:
            logger.error(f"SAgent: 会话 {session_id} 不存在，无法保存")
            return False

        try:
            session_context_.save()
        except Exception as save_error:
            logger.error(f"traceback: {traceback.format_exc()}")
            logger.error(f"SAgent: 保存会话状态 {session_id} 时出错: {save_error}")
            return False
        return True

    def interrupt_session(self, session_id: str, message: str = "用户请求中断") -> bool:
        session_context_ = get_session_context(session_id=session_id)
        if session_context_:
            session_context_.status = SessionStatus.INTERRUPTED
            return True
        return False

    def get_tasks_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        session_context_ = get_session_context(session_id=session_id)
        if session_context_:
            return session_context_.task_manager.to_dict()
        return None

    async def _emit_token_usage_if_any(self, session_context: SessionContext, session_id: str) -> list[MessageChunk]:
        """
        生成 token_usage MessageChunk（如有）
        """
        if not session_context:
            return []

        try:
            token_usage = session_context.get_tokens_usage_info()
            if not token_usage:
                logger.warning(f"SAgent: 会话 {session_id} 没有 token_usage 信息")
                return []

            logger.info(f"SAgent: 生成 token_usage MessageChunk，会话 {session_id}: {token_usage}")

            return [
                MessageChunk(
                    role=MessageRole.ASSISTANT.value,
                    content="",
                    message_type=MessageType.TOKEN_USAGE.value,
                    metadata={
                        "token_usage": token_usage,
                        "session_id": session_id,
                    },
                )
            ]

        except Exception as e:
            logger.error(f"SAgent: 生成 token_usage MessageChunk 失败，会话 {session_id}: {e}")
            return []

    async def _cleanup_session(self, session_id: str):
        """
        统一的会话清理逻辑
        """
        try:
            lock = get_session_run_lock(session_id)
            if lock and lock.locked():
                await lock.release()
            delete_session_run_lock(session_id)
        except Exception as e:
            logger.error(f"SAgent: 清理会话锁 {session_id} 时出错: {e}")

        try:
            delete_session_context(session_id)
            logger.info(f"SAgent: 已清理会话 {session_id}")
        except Exception as e:
            logger.error(f"SAgent: 清理会话 {session_id} 时出错: {e}")
