import asyncio
import json
import os
import time
import traceback
import uuid
import contextvars
from contextlib import contextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional, Union, Type

from sagents.agent import (
    AgentBase,
    FibreAgent,
    QuerySuggestAgent,
    SimpleAgent,
    TaskAnalysisAgent,
    TaskCompletionJudgeAgent,
    TaskDecomposeAgent,
    TaskExecutorAgent,
    TaskObservationAgent,
    TaskPlanningAgent,
    TaskRouterAgent,
    TaskSummaryAgent,
    WorkflowSelectAgent,
    ToolSuggestionAgent,
    MemoryRecallAgent,
)
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import (
    SessionContext,
    SessionStatus,
)
from sagents.context.user_memory import MemoryExtractor, UserMemoryManager
from sagents.observability import AgentRuntime, ObservabilityManager, OpenTelemetryTraceHandler, ObservableAsyncOpenAI
from sagents.skill import SkillManager, SkillProxy
from sagents.tool import ToolManager, ToolProxy
from sagents.tool.impl.todo_tool import ToDoTool
from sagents.utils.lock_manager import lock_manager, safe_release
from sagents.utils.logger import logger
from sagents.flow.schema import AgentFlow
from sagents.flow.executor import FlowExecutor


_session_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("session_id", default=None)


@contextmanager
def session_scope(session_id: Optional[str]):
    token = _session_id_var.set(session_id)
    try:
        yield session_id
    finally:
        _session_id_var.reset(token)


def get_current_session_id() -> Optional[str]:
    return _session_id_var.get()


def get_session_run_lock(session_id: str):
    return lock_manager.get_lock(session_id)


def delete_session_run_lock(session_id: str):
    lock_manager.delete_lock_ref(session_id)


class Session:
    def __init__(self, session_id: str, enable_obs: bool = True, sandbox_type: str = "local"):
        self.session_id = session_id
        self.enable_obs = enable_obs
        self.sandbox_type = sandbox_type
        self.session_context: Optional[SessionContext] = None
        self._agents: Dict[str, AgentBase] = {}
        self.model: Any = None
        self.model_config: Dict[str, Any] = {}
        self.system_prefix: str = ""
        self.session_space: str = "./sage_sessions"
        self.host_workspace: Optional[str] = None  # 代理工作区的宿主机路径（本地/直通沙箱需要）
        self.default_memory_type: str = "session"
        self.user_memory_manager: Optional[UserMemoryManager] = None
        self.observability_manager: Optional[ObservabilityManager] = None
        self._runtime_signature: Optional[tuple] = None
        self._agent_registry: Dict[str, Type[AgentBase]] = {
            "simple": SimpleAgent,
            "task_analysis": TaskAnalysisAgent,
            "task_decompose": TaskDecomposeAgent,
            "task_executor": TaskExecutorAgent,
            "task_observation": TaskObservationAgent,
            "task_completion_judge": TaskCompletionJudgeAgent,
            "task_planning": TaskPlanningAgent,
            "task_summary": TaskSummaryAgent,
            "workflow_select": WorkflowSelectAgent,
            "query_suggest": QuerySuggestAgent,
            "tool_suggestion": ToolSuggestionAgent,
            "task_router": TaskRouterAgent,
            "fibre": FibreAgent,
            "memory_recall": MemoryRecallAgent,
        }

    def configure_runtime(
        self,
        model: Any,
        model_config: Optional[Dict[str, Any]] = None,
        system_prefix: str = "",
        session_root_space: str = "./sage_sessions",
        host_workspace: Optional[str] = None,
        virtual_workspace: str = "/sage-workspace",
        default_memory_type: str = "session",
        agent_id: Optional[str] = None,
    ):
        runtime_signature = (
            id(model),
            str(model_config or {}),
            system_prefix,
            str(session_root_space),
            str(host_workspace or ""),
            str(virtual_workspace),
            default_memory_type,
            str(agent_id or ""),
        )
        if self._runtime_signature != runtime_signature:
            self._agents = {}
        self._runtime_signature = runtime_signature
        self.model = model
        self.model_config = model_config or {}
        self.system_prefix = system_prefix or ""
        self.session_root_space = str(session_root_space)
        self.host_workspace = str(host_workspace) if host_workspace else None
        self.virtual_workspace = str(virtual_workspace)
        self.default_memory_type = default_memory_type or "session"
        # agent_id 为 None 时生成随机 UUID
        self.agent_id = agent_id or str(uuid.uuid4())

        # 设置沙箱类型环境变量，供 SessionContext 和其他组件使用
        os.environ["SAGE_SANDBOX_MODE"] = self.sandbox_type

        if self.default_memory_type == "user":
            self.user_memory_manager = UserMemoryManager(model=self.model, workspace=self.session_root_space)
        else:
            self.user_memory_manager = None

        self.observability_manager = None
        if self.enable_obs:
            otel_handler = OpenTelemetryTraceHandler(service_name="sagents")
            self.observability_manager = ObservabilityManager(handlers=[otel_handler])
            self.model = ObservableAsyncOpenAI(self.model, self.observability_manager)

    def _load_saved_system_context(self, session_id: str) -> Optional[Dict[str, Any]]:
        # 尝试从 SessionManager 获取已知的 session_workspace
        # 如果是第一次创建，可能还不知道路径，返回 None
        # 如果 SessionManager 已经扫描到，则直接使用
        
        # 我们需要访问全局 SessionManager 吗？
        # Session 实例本身不知道自己属于哪个 Manager，除非传入。
        # 但我们有 get_global_session_manager。
        
        # 更好的方式：Session 初始化时，应该尝试定位自己的 workspace
        
        # 假设我们通过全局 Manager 查找
        try:
            manager = get_global_session_manager()
            if manager:
                session_workspace = manager.get_session_workspace(session_id, only_all_session_paths=True)
                if session_workspace:
                    context_path = os.path.join(session_workspace, "session_context.json")
                    if os.path.exists(context_path):
                        with open(context_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            return data.get("system_context")
                            
            default_path = os.path.join(self.session_root_space, session_id, "session_context.json")
            if os.path.exists(default_path):
                with open(default_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("system_context")
                 
        except UnicodeDecodeError:
            logger.warning(f"SessionRuntime: Failed to decode session_context.json for {session_id}, file may be in legacy encoding")
        except Exception as e:
            logger.warning(f"SessionRuntime: Failed to load saved system_context for {session_id}: {e}")
            
        return None

    async def _ensure_session_context(
        self,
        session_id: str,
        user_id: Optional[str],
        system_context: Optional[Dict[str, Any]],
        context_budget_config: Optional[Dict[str, Any]],
        user_memory_manager: Optional[Any],
        tool_manager: Optional[Any],
        skill_manager: Optional[Union[SkillManager, SkillProxy]],
        parent_session_id: Optional[str] = None,
    ) -> SessionContext:
        if self.session_context:
            self._cache_session_workspace(session_id, self.session_context)
            if tool_manager:
                self.session_context.tool_manager = tool_manager
            if skill_manager:
                self.session_context.skill_manager = skill_manager
            if system_context:
                self.session_context.add_and_update_system_context(system_context)
                logger.debug(f"SAgent: 更新了 system_context 参数 keys: {list(system_context.keys())}")
            if parent_session_id and not self.session_context.parent_session_id:
                self.session_context.parent_session_id = parent_session_id
            return self.session_context

        saved_system_context = self._load_saved_system_context(session_id)
        merged_system_context = dict(system_context or {})
        if saved_system_context:
            if merged_system_context:
                base = saved_system_context.copy()
                base.update(merged_system_context)
                merged_system_context = base
                logger.info(f"SessionContext: Merged saved system_context with provided for session {session_id}")
            else:
                merged_system_context = saved_system_context
                logger.info(f"SessionContext: Using saved system_context for session {session_id}")

        self.session_context = SessionContext(
            session_id=session_id,
            user_id=user_id,
            agent_id=self.agent_id,
            session_root_space=self.session_root_space,
            virtual_workspace=getattr(self, 'virtual_workspace', "/sage-workspace"),
            host_workspace=self.host_workspace,
            context_budget_config=context_budget_config,
            system_context=merged_system_context,
            user_memory_manager=user_memory_manager,
            tool_manager=tool_manager,
            skill_manager=skill_manager,
            parent_session_id=parent_session_id,
        )
        
        # 异步初始化 SessionContext
        await self.session_context.init_more()
        
        self._cache_session_workspace(session_id, self.session_context)
        return self.session_context

    def _get_agent(self, agent_key: str) -> AgentBase:
        if agent_key in self._agents:
            return self._agents[agent_key]

        agent_cls = self._agent_registry[agent_key]
        if agent_cls is FibreAgent:
            agent = agent_cls(
                self.model,
                self.model_config,
                system_prefix=self.system_prefix,
                enable_obs=False,
            )
        else:
            agent = agent_cls(self.model, self.model_config, system_prefix=self.system_prefix)
        if self.observability_manager:
            agent = AgentRuntime(agent, self.observability_manager)
        self._agents[agent_key] = agent
        return agent

    async def run_stream_with_flow(
        self,
        input_messages: Union[List[Dict[str, Any]], List[MessageChunk]],
        flow: AgentFlow,
        tool_manager: Optional[Union[ToolManager, ToolProxy]] = None,
        skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        deep_thinking: Optional[Union[bool, str]] = None,
        max_loop_count: int = 10,
        agent_mode: Optional[str] = None,
        more_suggest: bool = False,
        force_summary: bool = False,
        system_context: Optional[Dict[str, Any]] = None,
        available_workflows: Optional[Dict[str, Any]] = None,
        context_budget_config: Optional[Dict[str, Any]] = None,
        custom_sub_agents: Optional[List[Dict[str, Any]]] = None,
        parent_session_id: Optional[str] = None,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        available_workflows = available_workflows or {}
        merged_system_context = dict(system_context or {})
        with session_scope(session_id):
            # 确保SessionContext存在，并进行初始化
            session_context = await self._ensure_session_context(
                session_id=session_id,
                user_id=user_id,
                system_context=merged_system_context,
                context_budget_config=context_budget_config,
                user_memory_manager=self.user_memory_manager,
                tool_manager=tool_manager,
                skill_manager=skill_manager,
                parent_session_id=parent_session_id,
            )
            logger.info("SAgent: 会话开始")
            self.session_context = session_context

            if custom_sub_agents:
                session_context.custom_sub_agents = custom_sub_agents
                logger.debug(f"SAgent: 设置了 {len(custom_sub_agents)} 个自定义 Sub Agent")
            
            init_memory_start = time.perf_counter()
            # 初始化用户内存上下文
            await session_context.init_user_memory_context()
            init_memory_cost = time.perf_counter() - init_memory_start
            if init_memory_cost > 0.2:
                logger.warning(f"SAgent: init_user_memory_context slow, cost={init_memory_cost:.3f}s")

            if available_workflows:
                logger.info(f"SAgent: 提供了 {len(available_workflows)} 个工作流模板: {list(available_workflows.keys())}")
                session_context.workflow_manager.load_workflows_from_dict(available_workflows)

            session_context.set_agent_config(
                model=self.model,
                model_config=self.model_config,
                system_prefix=self.system_prefix,
                available_tools=tool_manager.list_all_tools_name() if tool_manager else [],
                available_skills=skill_manager.list_skills() if skill_manager else [],
                system_context=session_context.system_context,
                available_workflows=available_workflows,
                deep_thinking=deep_thinking if isinstance(deep_thinking, bool) else False,
                agent_mode=agent_mode,
                more_suggest=more_suggest,
                max_loop_count=max_loop_count,
            )

            session_context.set_status(SessionStatus.RUNNING)
            initial_messages = self._prepare_initial_messages(input_messages)

            merge_before_num = len(session_context.message_manager.messages)
            all_message_ids = [m.message_id for m in session_context.message_manager.messages]
            add_new_messages_num = 0
            update_messages_num = 0
            for message in initial_messages:
                if message.message_id not in all_message_ids:
                    session_context.add_messages(message)
                    add_new_messages_num += 1
                else:
                    session_context.message_manager.update_messages(message)
                    update_messages_num += 1

            logger.info(
                f"SAgent: 初始消息数量:{merge_before_num} 合并后数量：{len(session_context.message_manager.messages)} 新增消息数量：{add_new_messages_num} 更新消息数量：{update_messages_num}"
            )
    
            load_recent_skill_start = time.perf_counter()

            # 加载最近使用的技能到上下文
            await session_context.load_recent_skill_to_context()
            load_recent_skill_cost = time.perf_counter() - load_recent_skill_start
            if load_recent_skill_cost > 0.2:
                logger.warning(f"SAgent: load_recent_skill_to_context slow, cost={load_recent_skill_cost:.3f}s")

            # history_context_start = time.perf_counter()
            # 设置会话历史上下文
            # session_context.set_session_history_context()
            # history_context_cost = time.perf_counter() - history_context_start
            # if history_context_cost > 0.2:
            #     logger.warning(f"SAgent: set_session_history_context slow, cost={history_context_cost:.3f}s")

            # --- 新的 Flow 执行逻辑 ---
            # 1. 预处理状态 (兼容旧逻辑)
            # 确保一些状态已经设置到 SessionContext 中，供 ConditionRegistry 使用
            if deep_thinking is not None:
                session_context.audit_status["deep_thinking"] = deep_thinking
            if agent_mode is not None:
                session_context.audit_status["agent_mode"] = agent_mode
            if more_suggest is not None:
                session_context.audit_status["more_suggest"] = more_suggest
            if force_summary is not None:
                session_context.audit_status["force_summary"] = force_summary
                
            # 2. 如果没有显式设置 agent_mode，可能需要通过 router 决定，但现在 Flow 逻辑应该包含 router
            # 旧逻辑：先跑 router，然后根据结果设置 mode
            # 新逻辑：Flow 中应该包含 router 节点，然后 Switch 节点根据上下文变量跳转
            
            # 为了支持动态设置工具，我们可能需要在 Flow 执行过程中动态调整
            session_context.restrict_tools_for_mode(agent_mode)
            tool_manager = session_context.tool_manager
            
            # 3. 执行 Flow
            executor = FlowExecutor(session_context, tool_manager, self, session_id)
            async for message_chunks in executor.execute(flow.root):
                yield message_chunks

            # --- 会话结束处理 (原 run_stream 尾部逻辑) ---
            if session_context.user_memory_manager and session_context.user_memory_manager.is_enabled():
                logger.info("SAgent: 启动异步记忆提取任务")
                extractor = MemoryExtractor(self.model)
                asyncio.create_task(extractor.extract_and_save(session_context=session_context, session_id=session_id))

            if session_context.status != SessionStatus.INTERRUPTED:
                session_context.set_status(SessionStatus.COMPLETED)
            else:
                logger.warning(f"SAgent: 会话被中断，会话ID: {session_id}")

    async def _handle_workflow_error(self, error: Exception) -> AsyncGenerator[List[MessageChunk], None]:
        logger.error(f"SAgent: 处理工作流错误: {str(error)}\n{traceback.format_exc()}")
        error_message = self._extract_friendly_error_message(error)
        yield [MessageChunk(role="assistant", content=f"工作流执行失败: {error_message}", type="final_answer")]

    def _extract_friendly_error_message(self, error: Exception) -> str:
        """从异常中提取友好的错误信息"""
        error_str = str(error)

        # 处理数据检查失败错误（内容审核）
        if "DataInspectionFailed" in error_str or "data_inspection_failed" in error_str:
            if "inappropriate content" in error_str or "inappropriate" in error_str:
                return "输入内容可能包含不适当的内容，请修改后重试"
            return "内容安全检查未通过，请修改输入后重试"

        # 处理速率限制错误
        if "rate_limit" in error_str.lower() or "RateLimitError" in error_str:
            return "请求过于频繁，请稍后再试"

        # 处理配额不足错误
        if "quota" in error_str.lower() or "insufficient_quota" in error_str.lower():
            return "API 配额不足，请检查账户余额或配额设置"

        # 处理认证错误
        if "authentication" in error_str.lower() or "unauthorized" in error_str.lower() or "401" in error_str:
            return "API 认证失败，请检查 API Key 是否正确"

        # 处理模型不存在错误
        if "model" in error_str.lower() and ("not found" in error_str.lower() or "does not exist" in error_str.lower()):
            return "指定的模型不存在或不可用，请检查模型配置"

        # 处理上下文长度超限
        if "context_length" in error_str.lower() or "token" in error_str.lower() and "exceed" in error_str.lower():
            return "输入内容过长，请缩短后重试"

        # 处理连接错误
        if "connection" in error_str.lower() or "timeout" in error_str.lower() or "network" in error_str.lower():
            return "网络连接失败，请检查网络设置或稍后重试"

        # 处理服务不可用
        if "service unavailable" in error_str.lower() or "503" in error_str or "502" in error_str:
            return "服务暂时不可用，请稍后再试"

        # 默认返回原始错误信息（但截断过长的）
        if len(error_str) > 200:
            return error_str[:200] + "..."
        return error_str

    async def run_stream_safe(self, **kwargs) -> AsyncGenerator[List[MessageChunk], None]:
        session_id = kwargs.get("session_id")
        try:
            # 尝试获取 flow 参数，如果存在则调用 run_stream_with_flow
            if "flow" in kwargs and kwargs["flow"] is not None:
                async for message_chunks in self.run_stream_with_flow(**kwargs):
                    yield message_chunks
            else:
                raise ValueError("SAgent: run_stream_safe 必须提供 flow 参数")
        except Exception as e:
            if self.observability_manager:
                self.observability_manager.on_chain_error(e, session_id=session_id)
            session_context = self.session_context
            if session_context:
                session_context.set_status(SessionStatus.ERROR)
                async for chunk in self._handle_workflow_error(e):
                    session_context.add_messages(chunk)
                    yield chunk
            else:
                logger.error(f"Failed to initialize session: {e}")
                yield [
                    MessageChunk(
                        role="assistant",
                        content=f"Error initializing session: {str(e)},traceback: {traceback.format_exc()}",
                        type="text",
                    )
                ]
        finally:
            if self.observability_manager:
                self.observability_manager.on_chain_end(output_data={"status": "finished"}, session_id=session_id)
            session_context = self.session_context
            self._cache_session_workspace(session_id, session_context)
            
            if session_context:
                try:
                     chunks = await self._emit_token_usage_if_any(session_context, session_id)
                     if chunks:
                         for i, chunk in enumerate(chunks):
                             yield [chunk]
                except Exception as e:
                    logger.error(f"SAgent: 发送 token usage 失败: {e}")
            
            if session_context:
                try:
                    logger.debug("SAgent: 会话状态保存")
                    session_context.save()
                except Exception as e:
                    logger.error(f"SAgent: 会话状态保存时出错: {e}")
            await self._cleanup_session_resources(session_id)


    async def _execute_agent_phase(
        self,
        session_context: SessionContext,
        agent: AgentBase,
        phase_name: str,
        override_config: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        session_id = session_context.session_id
        logger.info(f"SAgent: 使用 {agent.agent_description} 智能体，{phase_name}阶段")
        # 检查中断
        if session_context.status == SessionStatus.INTERRUPTED:
            logger.info(f"SAgent: {phase_name} 阶段被中断，会话ID: {session_id}")
            return

        async for chunk in agent.run_stream(session_context):
            # 在每个块之间检查中断
            if session_context.status == SessionStatus.INTERRUPTED:
                logger.info(f"SAgent: {phase_name} 阶段在块处理中被中断，会话ID: {session_id}")
                return
            yield chunk

        logger.info(f"SAgent: {phase_name} 阶段完成")

    def _prepare_initial_messages(self, input_messages: Union[List[Dict[str, Any]], List[MessageChunk]]) -> List[MessageChunk]:
        for msg in input_messages:
            if not isinstance(msg, (dict, MessageChunk)):
                raise ValueError("每个消息必须是字典或MessageChunk类型")
        return [MessageChunk.from_dict(msg) if isinstance(msg, dict) else msg for msg in input_messages]

    def close(self):
        self.session_context = None

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

            logger.debug(f"SAgent: 生成 token_usage MessageChunk，会话 {session_id}: {token_usage}")

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

    def _cache_session_workspace(self, session_id: Optional[str], session_context: Optional[SessionContext]):
        if not session_id or not session_context:
            return
        try:
            manager = get_global_session_manager()
            if manager:
                manager.cache_session_workspace(session_id, session_context.session_workspace)
        except Exception as e:
            logger.warning(f"SAgent: 缓存会话路径失败: {e}")

    async def _cleanup_session_resources(self, session_id: str):
        """
        统一的会话清理逻辑
        """
        try:
            lock = get_session_run_lock(session_id)
            if lock and lock.locked():
                await safe_release(lock, session_id, "SAgent 会话清理")
            delete_session_run_lock(session_id)
        except Exception as e:
            logger.error(f"SAgent: 清理会话锁时出错: {e}", session_id=session_id)

        try:
            # 获取全局 session_manager 并移除 session_context
            manager = get_global_session_manager()
            if manager:
                manager.remove_session_context(session_id)
                logger.debug(f"SAgent: 会话 {session_id} 已清理", session_id=session_id)
        except Exception as e:
            logger.error(f"SAgent: 清理会话 {session_id} 时出错: {e}", session_id=session_id)

class SessionManager:
    def __init__(self, session_root_space: str, enable_obs: bool = True):
        self.session_root_space = str(session_root_space)
        self.enable_obs = enable_obs
        self._sessions: Dict[str, Session] = {}
        # 格式: {session_id: workspace_path}
        self._all_session_paths: Dict[str, str] = {}
        self._scan_all_sessions()

    def _scan_all_sessions(self):
        """启动时扫描所有会话（根会话+子会话），建立 ID 到 workspace 的映射"""
        if not os.path.exists(self.session_root_space):
            logger.info(f"SessionManager: Session root space does not exist: {self.session_root_space}")
            return
        
        logger.debug(f"SessionManager: Scanning all sessions in {self.session_root_space}")
        
        for entry in os.listdir(self.session_root_space):
            entry_path = os.path.join(self.session_root_space, entry)
            if not os.path.isdir(entry_path):
                continue
                
            # 检查是否是根会话
            if os.path.exists(os.path.join(entry_path, "session_context.json")) or os.path.exists(os.path.join(entry_path, "messages.json")):
                self._all_session_paths[entry] = entry_path
                logger.debug(f"Found root session: {entry}")
            
            # 扫描子会话
            sub_sessions_dir = os.path.join(entry_path, "sub_sessions")
            if os.path.exists(sub_sessions_dir):
                for sub_entry in os.listdir(sub_sessions_dir):
                    sub_entry_path = os.path.join(sub_sessions_dir, sub_entry)
                    if os.path.isdir(sub_entry_path):
                        if os.path.exists(os.path.join(sub_entry_path, "session_context.json")) or os.path.exists(os.path.join(sub_entry_path, "messages.json")):
                            self._all_session_paths[sub_entry] = sub_entry_path
                            logger.debug(f"Found sub session: {sub_entry}")
        
        logger.info(f"SessionManager: Found {len(self._all_session_paths)} sessions total")

    def _is_sub_session(self, session_id: str) -> bool:
        """判断是否为子会话（通过检查路径是否包含 sub_sessions）"""
        if session_id not in self._all_session_paths:
            return False
        path = self._all_session_paths[session_id]
        return "sub_sessions" in path

    def get_session_workspace(self, session_id: str, only_all_session_paths: bool = False) -> Optional[str]:
        """
        获取指定 session 的工作区路径
        
        Args:
            session_id: 会话 ID（全局唯一）
        
        Returns:
            工作区路径，找不到则返回 None
        """
        # 1. 首先尝试从内存缓存获取
        if session_id in self._all_session_paths:
            return self._all_session_paths[session_id]
        if only_all_session_paths:
            return None
        # 2. 如果内存中没有，重新扫描会话目录
        # 这处理了会话在其他进程中创建的情况
        logger.debug(f"SessionManager: Session {session_id} not in cache, rescanning...")
        self._scan_all_sessions()
        
        # 3. 再次尝试获取
        return self._all_session_paths.get(session_id)

    def cache_session_workspace(self, session_id: str, session_workspace: Optional[str]):
        if not session_id or not session_workspace:
            return
        self._all_session_paths[session_id] = os.path.abspath(session_workspace)

    def get_or_create(
        self,
        session_id: str,
        sandbox_type: str = "local",
        session_space: Optional[str] = None
    ) -> Session:
        """
        获取或创建 Session

        Args:
            session_id: 会话 ID（全局唯一）
            sandbox_type: 沙箱类型 (local|remote|passthrough)
            session_space: 会话空间路径

        Returns:
            Session 实例
        """
        # 判断是否为子会话
        is_sub_session = self._is_sub_session(session_id)

        # 子会话：总是创建新实例，不保留在 _sessions 中
        if is_sub_session:
            session = Session(
                session_id=session_id,
                enable_obs=self.enable_obs,
                sandbox_type=sandbox_type
            )
            return session

        # 根会话：保留在内存中
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(
                session_id=session_id,
                enable_obs=self.enable_obs,
                sandbox_type=sandbox_type
            )

        else:
            self._sessions[session_id].sandbox_type = sandbox_type

        return self._sessions[session_id]

    def get(self, session_id: str) -> Optional[Session]:
        """
        获取 Session（根会话从内存获取，子会话返回 None 因为不保留在内存中）
        
        Args:
            session_id: 会话 ID
        
        Returns:
            Session 实例，找不到则返回 None
        """
        # 子会话不保留在内存中，返回 None
        if self._is_sub_session(session_id):
            return None
        return self._sessions.get(session_id)

    def register_session_context(self, session_id: str, session_context: SessionContext):
        """注册 SessionContext"""
        session = self.get_or_create(session_id)
        session.session_context = session_context

    def remove_session_context(self, session_id: str):
        """移除 SessionContext"""
        session = self.get(session_id)
        if session:
            session.session_context = None

    def close_session(self, session_id: str):
        """关闭 Session"""
        # 子会话不保留在内存中，无需清理
        if self._is_sub_session(session_id):
            return
        session = self._sessions.pop(session_id, None)
        if session:
            try:
                logger.cleanup_session_logger(session_id)
            except Exception as e:
                logger.warning(f"清理session {session_id} 日志资源时出错: {e}")
            session.close()

    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取 Session 状态"""
        session = self.get(session_id)
        if session and session.session_context:
            return {"status": session.session_context.status}
        return None

    def list_active_sessions(self) -> List[Dict[str, Any]]:
        """列出活跃的根会话（子会话不保留在内存中，不列出）"""
        return [
            {
                "session_id": sid,
                "status": sess.session_context.status.value if sess.session_context else SessionStatus.IDLE.value,
                "start_time": sess.session_context.start_time if sess.session_context else None,
            }
            for sid, sess in self._sessions.items()
            if sess.session_context
        ]

    def get_session_messages(self, session_id: str) -> List[MessageChunk]:
        """
        获取会话消息历史
        
        Args:
            session_id: 会话 ID（全局唯一）
        """
        # 1. 尝试从内存获取（只有根会话会保留在内存中）
        session = self.get(session_id)
        if session and session.session_context:
            return session.session_context.get_messages()

        # 2. 尝试从磁盘获取（支持子会话按需加载）
        session_workspace_path = self.get_session_workspace(session_id)
        if not session_workspace_path:
             logger.warning(f"SessionManager: 无法找到会话 {session_id} 的路径")
             return []

        messages_path = os.path.join(session_workspace_path, "messages.json")
        if not os.path.exists(messages_path):
            return []
            
        try:
            with open(messages_path, "r", encoding="utf-8") as f:
                raw_messages = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"SessionManager: Failed to decode messages.json for session {session_id}: {e}")
            return []
        except UnicodeDecodeError:
            logger.error(f"SessionManager: messages.json encoding error for session {session_id}, file may be in legacy encoding")
            return []
        except Exception as e:
            logger.error(f"SessionManager: 读取 messages.json 失败: {e}")
            return []

        if not isinstance(raw_messages, list):
            return []

        messages: List[MessageChunk] = []
        for msg in raw_messages:
            if isinstance(msg, dict):
                try:
                    messages.append(MessageChunk.from_dict(msg))
                except Exception as e:
                    logger.warning(f"SessionManager: 解析消息失败: {e}")
            elif isinstance(msg, MessageChunk):
                messages.append(msg)
        return messages


# 全局 SessionManager 实例
_global_session_manager: Optional[SessionManager] = None


def initialize_global_session_manager(session_root_space: str, enable_obs: bool = True):
    """初始化全局 SessionManager"""
    global _global_session_manager
    _global_session_manager = SessionManager(session_root_space, enable_obs)
    return _global_session_manager


def get_global_session_manager(session_root_space: Optional[str] = None, enable_obs: bool = True) -> Optional[SessionManager]:
    """
    获取全局 SessionManager 实例
    
    Args:
        session_root_space: 会话根目录（如果是第一次初始化，需要提供）
        enable_obs: 是否启用观测
    
    Returns:
        SessionManager 实例
    """
    global _global_session_manager
    if _global_session_manager is None:
        if session_root_space is None:
            raise ValueError("session_root_space is required for first initialization")
        _global_session_manager = SessionManager(session_root_space, enable_obs)
    return _global_session_manager
