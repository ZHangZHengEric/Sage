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
    TaskSummaryAgent,
    WorkflowSelectAgent,
    ToolSuggestionAgent,
    MemoryRecallAgent,
    PlanAgent,
    SelfCheckAgent,
)
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.session_context import (
    SessionContext,
    SessionStatus,
)

from sagents.observability import AgentRuntime, ObservabilityManager, OpenTelemetryTraceHandler, ObservableAsyncOpenAI
from sagents.skill import SkillManager, SkillProxy
from sagents.tool import ToolManager, ToolProxy
from sagents.tool.impl.todo_tool import ToDoTool
from sagents.utils.lock_manager import lock_manager, safe_release
from sagents.utils.logger import logger
from sagents.flow.schema import AgentFlow
from sagents.flow.executor import FlowExecutor
from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.message_control_flags import extract_control_flags_from_messages


_session_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("session_id", default=None)


def _load_json_file_sync(file_path: str) -> Optional[Any]:
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


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
        self.session_workspace: Optional[str] = None
        self.status: SessionStatus = SessionStatus.IDLE
        self.interrupt_reason: Optional[str] = None
        self.interrupt_event = asyncio.Event()
        self.child_session_ids: List[str] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self._agents: Dict[str, AgentBase] = {}
        self.model: Any = None
        self.model_config: Dict[str, Any] = {}
        self.system_prefix: str = ""
        self.session_space: str = "./sage_sessions"
        # workspace 配置
        self.sandbox_agent_workspace: Optional[str] = None  # Agent 私有工作空间
        self.volume_mounts: Optional[List[VolumeMount]] = None  # 卷挂载配置
        self.sandbox_id: Optional[str] = None  # 远程沙箱 ID
        self.observability_manager: Optional[ObservabilityManager] = None
        self._runtime_signature: Optional[tuple] = None
        self._persisted_snapshot: Optional[Dict[str, Any]] = None
        self._persisted_messages: Optional[List[MessageChunk]] = None
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
            "fibre": FibreAgent,
            "memory_recall": MemoryRecallAgent,
            "plan": PlanAgent,
            "self_check": SelfCheckAgent,
        }

    def has_context(self) -> bool:
        return self.session_context is not None

    def set_context(self, session_context: SessionContext) -> None:
        self.session_context = session_context
        self.session_workspace = getattr(session_context, "session_workspace", self.session_workspace)
        session_context.start_time = self.start_time
        session_context.end_time = self.end_time
        session_context.child_session_ids = list(self.child_session_ids)
        if hasattr(session_context, "audit_status"):
            session_context.audit_status["interrupt_reason"] = self.interrupt_reason

    def clear_context(self) -> None:
        self.session_context = None

    def set_workspace(self, session_workspace: Optional[str]) -> None:
        if session_workspace:
            self.session_workspace = str(session_workspace)

    def get_context(self) -> Optional[SessionContext]:
        return self.session_context

    def set_status(self, status: SessionStatus, cascade: bool = True) -> None:
        old_status = self.status
        self.status = status
        if status == SessionStatus.INTERRUPTED:
            self.interrupt_event.set()
        elif status == SessionStatus.RUNNING:
            # 进入新的运行周期，清掉历史中断状态（可能来自上一轮被中断后持久化的状态）
            if self.interrupt_event.is_set() or self.interrupt_reason:
                logger.info(
                    f"SessionRuntime: Session {self.session_id} entering RUNNING, "
                    f"clearing stale interrupt state (reason={self.interrupt_reason!r})"
                )
            self.interrupt_event.clear()
            self.interrupt_reason = None
            if self.session_context and isinstance(getattr(self.session_context, "audit_status", None), dict):
                self.session_context.audit_status.pop("interrupt_reason", None)
        if self.session_context:
            self.session_context.end_time = time.time() if status in {SessionStatus.COMPLETED, SessionStatus.ERROR, SessionStatus.INTERRUPTED} else self.session_context.end_time
        if status in {SessionStatus.COMPLETED, SessionStatus.ERROR, SessionStatus.INTERRUPTED}:
            self.end_time = time.time()
        logger.debug(f"SessionRuntime: Session {self.session_id} status changed from {old_status.value} to {status.value}")

        if cascade and status in {SessionStatus.INTERRUPTED, SessionStatus.ERROR} and self.child_session_ids:
            try:
                manager = get_global_session_manager()
            except Exception:
                manager = None
            if manager:
                for child_session_id in list(self.child_session_ids):
                    try:
                        child_session = manager.get_live_session(child_session_id) or manager.get(child_session_id)
                        if child_session:
                            child_session.set_status(status, cascade=False)
                    except Exception as exc:
                        logger.warning(
                            f"SessionRuntime: cascade {status.value} to child session {child_session_id} failed: {exc}"
                        )

    def should_interrupt(self) -> bool:
        if self.interrupt_event.is_set():
            return True
        return self.status == SessionStatus.INTERRUPTED

    def add_child_session(self, child_session_id: str) -> None:
        if child_session_id not in self.child_session_ids:
            self.child_session_ids.append(child_session_id)
        if self.session_context and child_session_id not in self.session_context.child_session_ids:
            self.session_context.child_session_ids.append(child_session_id)

    def remove_child_session(self, child_session_id: str) -> None:
        if child_session_id in self.child_session_ids:
            self.child_session_ids.remove(child_session_id)
        if self.session_context and child_session_id in self.session_context.child_session_ids:
            self.session_context.child_session_ids.remove(child_session_id)

    def _load_persisted_snapshot(self) -> Optional[Dict[str, Any]]:
        if self._persisted_snapshot is not None:
            return self._persisted_snapshot
        if not self.session_workspace:
            return None

        context_path = os.path.join(self.session_workspace, "session_context.json")
        if not os.path.exists(context_path):
            return None

        try:
            snapshot = _load_json_file_sync(context_path)
            if isinstance(snapshot, dict):
                self._persisted_snapshot = snapshot
                return snapshot
        except Exception as exc:
            logger.debug(f"SessionRuntime: 读取 session {self.session_id} 快照失败: {exc}")
        return None

    def _load_persisted_messages(self) -> List[MessageChunk]:
        if self._persisted_messages is not None:
            return self._persisted_messages
        if not self.session_workspace:
            return []

        messages_path = os.path.join(self.session_workspace, "messages.json")
        if not os.path.exists(messages_path):
            self._persisted_messages = []
            return self._persisted_messages

        try:
            raw_messages = _load_json_file_sync(messages_path)
            if isinstance(raw_messages, list):
                self._persisted_messages = [
                    MessageChunk.from_dict(msg)
                    for msg in raw_messages
                    if isinstance(msg, dict)
                ]
            else:
                self._persisted_messages = []
        except Exception as exc:
            logger.debug(f"SessionRuntime: 读取 session {self.session_id} messages 失败: {exc}")
            self._persisted_messages = []
        return self._persisted_messages

    def load_persisted_state(self, session_workspace: Optional[str] = None) -> bool:
        if session_workspace:
            self.set_workspace(session_workspace)
        snapshot = self._load_persisted_snapshot()
        if snapshot is None and not self.session_workspace:
            return False

        if self.session_workspace:
            self._persisted_messages = self._load_persisted_messages()

        if snapshot is not None and self.session_context is None:
            try:
                agent_config = snapshot.get("agent_config") or {}
                system_context = snapshot.get("system_context") or {}
                self.session_context = SessionContext(
                    session_id=str(snapshot.get("session_id") or self.session_id),
                    user_id=str(snapshot.get("user_id") or ""),
                    agent_id=str(agent_config.get("agent_id") or ""),
                    session_root_space=str(snapshot.get("session_root_space") or self.session_space),
                    sandbox_agent_workspace=snapshot.get("sandbox_agent_workspace"),
                    volume_mounts=None,
                    sandbox_id=None,
                    context_budget_config=None,
                    system_context=system_context if isinstance(system_context, dict) else {},
                    tool_manager=None,
                    skill_manager=None,
                    parent_session_id=snapshot.get("parent_session_id"),
                )
                self.session_context.session_workspace = snapshot.get("session_workspace") or self.session_workspace
                self.status = SessionStatus(str(snapshot.get("status") or SessionStatus.IDLE.value))
                self.start_time = float(snapshot.get("created_at") or self.session_context.start_time)
                self.end_time = snapshot.get("updated_at")
                self.session_context.start_time = self.start_time
                self.session_context.end_time = self.end_time
                self.session_context.child_session_ids = list(snapshot.get("child_session_ids") or [])
                self.child_session_ids = list(self.session_context.child_session_ids)
                self.session_context.audit_status = snapshot.get("audit_status") or {}
                if isinstance(agent_config, dict):
                    self.session_context.agent_config = agent_config
                self.session_context.message_manager.messages = self._load_persisted_messages()
                # 注意：这里不再根据持久化的 INTERRUPTED 状态去 set interrupt_event。
                # interrupt_event 是用于"当前运行周期"的中断信号，磁盘里的 INTERRUPTED 仅是上一轮
                # 结束时的历史状态。如果在加载时把 event 置位，下一次新的 run_stream 进入时即使
                # set_status(RUNNING)，FlowExecutor 仍会因 should_interrupt() 为 True 而立刻退出。
                # 当前轮次是否需要中断，由 SessionManager.interrupt_session(...) 在运行期再次触发。
            except Exception as exc:
                logger.warning(f"SessionRuntime: 恢复 session {self.session_id} 快照失败: {exc}")
                return False

        return snapshot is not None or bool(self._persisted_messages)

    def get_status(self) -> SessionStatus:
        if self.status == SessionStatus.IDLE:
            snapshot = self._load_persisted_snapshot()
            if snapshot and snapshot.get("status"):
                try:
                    self.status = SessionStatus(str(snapshot.get("status")))
                except Exception:
                    self.status = SessionStatus.IDLE
        return self.status

    def is_interrupted(self) -> bool:
        return self.get_status() == SessionStatus.INTERRUPTED

    def get_start_time(self) -> Optional[float]:
        if self.session_context:
            self.start_time = self.session_context.start_time
            return self.start_time
        if self.start_time is None:
            snapshot = self._load_persisted_snapshot()
            if snapshot is not None:
                created_at = snapshot.get("created_at")
                self.start_time = float(created_at) if created_at is not None else None
        return self.start_time

    def get_messages(self) -> List[MessageChunk]:
        if not self.session_context:
            return list(self._load_persisted_messages())
        return self.session_context.get_messages()

    def get_tasks_status(self) -> Dict[str, Any]:
        if not self.session_context or not self.session_context.task_manager:
            snapshot = self._load_persisted_snapshot()
            if snapshot is not None:
                return snapshot.get("tasks_status") or {"tasks": []}
            return {"tasks": []}
        try:
            return self.session_context.task_manager.to_dict()
        except Exception as exc:
            logger.warning(f"SessionRuntime: 获取 session {self.session_id} 任务状态失败: {exc}")
            return {"tasks": []}

    def request_interrupt(self, message: str = "用户请求中断", cascade: bool = True) -> bool:
        if not self.session_context:
            return False
        try:
            self.interrupt_reason = message
            if self.session_context:
                self.session_context.audit_status["interrupt_reason"] = message
            self.interrupt_event.set()
            self.set_status(SessionStatus.INTERRUPTED, cascade=cascade)
            return True
        except Exception as exc:
            logger.warning(f"SessionRuntime: 中断 session {self.session_id} 失败: {exc}")
            return False

    def configure_runtime(
        self,
        model: Any,
        model_config: Optional[Dict[str, Any]] = None,
        system_prefix: str = "",
        session_root_space: str = "./sage_sessions",
        sandbox_agent_workspace: Optional[str] = None,
        volume_mounts: Optional[List[VolumeMount]] = None,
        sandbox_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ):
        runtime_signature = (
            id(model),
            str(model_config or {}),
            system_prefix,
            str(session_root_space),
            str(sandbox_agent_workspace or ""),
            str(volume_mounts or []),
            str(sandbox_id or ""),
            str(agent_id or ""),
        )
        if self._runtime_signature != runtime_signature:
            self._agents = {}
        self._runtime_signature = runtime_signature
        self.model = model
        self.model_config = model_config or {}
        self.system_prefix = system_prefix or ""
        self.session_root_space = str(session_root_space)

        # workspace 配置
        self.sandbox_agent_workspace = sandbox_agent_workspace
        self.volume_mounts = volume_mounts or []
        self.sandbox_id = sandbox_id

        logger.info(f"SessionRuntime: configure_runtime "
                   f"sandbox_agent_workspace={self.sandbox_agent_workspace}, "
                   f"volume_mounts_count={len(self.volume_mounts)}, "
                   f"sandbox_id={self.sandbox_id}")

        # agent_id 为 None 时生成随机 UUID
        self.agent_id = agent_id or str(uuid.uuid4())

        # 设置沙箱类型环境变量，供 SessionContext 和其他组件使用
        os.environ["SAGE_SANDBOX_MODE"] = self.sandbox_type

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
                        data = _load_json_file_sync(context_path)
                        return data.get("system_context") if isinstance(data, dict) else None
                            
            default_path = os.path.join(self.session_root_space, session_id, "session_context.json")
            if os.path.exists(default_path):
                data = _load_json_file_sync(default_path)
                return data.get("system_context") if isinstance(data, dict) else None
                 
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
        tool_manager: Optional[Any],
        skill_manager: Optional[Union[SkillManager, SkillProxy]],
        parent_session_id: Optional[str] = None,
    ) -> SessionContext:
        if not parent_session_id and system_context:
            parent_session_id = system_context.get("parent_session_id")
            if parent_session_id:
                logger.info(f"SessionRuntime: 从 system_context 中提取 parent_session_id={parent_session_id}")

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
            if getattr(self.session_context, "sandbox", None) is None:
                logger.warning(
                    f"SessionRuntime: session_context for {session_id} has no sandbox, reinitializing"
                )
                await self.session_context.init_more(self.session_context._session_root_space)
            return self.session_context

        # saved_system_context = self._load_saved_system_context(session_id)
        merged_system_context = dict(system_context or {})
        # if saved_system_context:
        #     if merged_system_context:
        #         base = saved_system_context.copy()
        #         base.update(merged_system_context)
        #         merged_system_context = base
        #         logger.info(f"SessionContext: Merged saved system_context with provided for session {session_id}")
        #     else:
        #         merged_system_context = saved_system_context
        #         logger.info(f"SessionContext: Using saved system_context for session {session_id}")

        # 调试：检查 workspace 配置
        logger.info(f"SessionRuntime: 创建 SessionContext，"
                   f"sandbox_agent_workspace={self.sandbox_agent_workspace}, "
                   f"volume_mounts_count={len(self.volume_mounts or [])}, "
                   f"sandbox_id={self.sandbox_id}")

        self.session_context = SessionContext(
            session_id=session_id,
            user_id=user_id,
            agent_id=self.agent_id,
            session_root_space=self.session_root_space,
            sandbox_agent_workspace=self.sandbox_agent_workspace,
            volume_mounts=self.volume_mounts,
            sandbox_id=self.sandbox_id,
            context_budget_config=context_budget_config,
            system_context=merged_system_context,
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
        max_loop_count: Optional[int] = None,
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
            if max_loop_count is None:
                raise ValueError("max_loop_count is required")
            # 确保SessionContext存在，并进行初始化
            session_context = await self._ensure_session_context(
                session_id=session_id,
                user_id=user_id,
                system_context=merged_system_context,
                context_budget_config=context_budget_config,
                tool_manager=tool_manager,
                skill_manager=skill_manager,
                parent_session_id=parent_session_id,
            )
            logger.info("SAgent: 会话开始")
            self.session_context = session_context

            if custom_sub_agents:
                session_context.custom_sub_agents = custom_sub_agents
                logger.debug(f"SAgent: 设置了 {len(custom_sub_agents)} 个自定义 Sub Agent")

            if available_workflows:
                logger.info(f"SAgent: 提供了 {len(available_workflows)} 个工作流模板: {list(available_workflows.keys())}")
                session_context.workflow_manager.load_workflows_from_dict(available_workflows)

            initial_messages = self._prepare_initial_messages(input_messages)
            control_flags = extract_control_flags_from_messages(initial_messages)
            enable_deep_thinking = bool(control_flags.get("enable_deep_thinking", False))
            if deep_thinking is not None:
                logger.warning("SAgent: 参数 deep_thinking 已过时且已忽略，请改用消息控制标签 <enable_deep_thinking>")

            session_context.set_agent_config(
                model=self.model,
                model_config=self.model_config,
                system_prefix=self.system_prefix,
                available_tools=tool_manager.list_all_tools_name() if tool_manager else [],
                available_skills=skill_manager.list_skills() if skill_manager else [],
                system_context=session_context.system_context,
                available_workflows=available_workflows,
                deep_thinking=enable_deep_thinking,
                agent_mode=agent_mode,
                more_suggest=more_suggest,
                max_loop_count=max_loop_count,
            )

            self.set_status(SessionStatus.RUNNING)

            try:
                session_context.start_request({
                    "agent_mode": agent_mode,
                    "model": (self.model_config or {}).get("model") if isinstance(self.model_config, dict) else None,
                    "max_loop_count": max_loop_count,
                })
            except Exception as exc:
                logger.warning(f"SAgent: 开启 per-request tokens 统计失败: {exc}")

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
            
            # 初始化消息历史切分，设置 active_start_index
            # 在所有消息（包括用户输入）添加完成后调用
            if session_context.message_manager.messages:
                try:
                    session_context.message_manager.prepare_history_split(session_context.agent_config)
                    logger.debug(f"SAgent: 初始化消息历史切分完成，active_start_index={session_context.message_manager.active_start_index}")
                except Exception as e:
                    logger.warning(f"SAgent: 初始化消息历史切分失败: {e}")
    
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
            session_context.audit_status["deep_thinking"] = enable_deep_thinking
            session_context.audit_status["enable_plan"] = bool(control_flags.get("enable_plan", False))
            if agent_mode is not None:
                session_context.audit_status["agent_mode"] = agent_mode
            if more_suggest is not None:
                session_context.audit_status["more_suggest"] = more_suggest
            if force_summary is not None:
                session_context.audit_status["force_summary"] = force_summary
            session_context.audit_status.pop("self_check_passed", None)
            session_context.audit_status.pop("self_check_issues", None)
            session_context.audit_status.pop("self_check_summary", None)
            session_context.audit_status.pop("self_check_checked_files", None)
                
            # 2. 准备工具白名单
            # 这里直接按显式 agent_mode 收敛可用工具，不再经过自动路由分叉
            session_context.restrict_tools_for_mode(agent_mode)
            tool_manager = session_context.tool_manager
            
            # 3. 执行 Flow
            executor = FlowExecutor(tool_manager, self, session_id, session_manager=get_global_session_manager())
            async for message_chunks in executor.execute(flow.root):
                yield message_chunks

            # --- 会话结束处理 (原 run_stream 尾部逻辑) ---
            if self.get_status() != SessionStatus.INTERRUPTED:
                self.set_status(SessionStatus.COMPLETED, cascade=False)
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
                self.set_status(SessionStatus.ERROR)
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
            session_context = self.session_context
            if self.observability_manager and session_context:
                try:
                    timing_summary = session_context._build_execution_timing_summary()
                    for item in timing_summary.get("message_timings", []):
                        message_id = item.get("message_id")
                        if not message_id:
                            continue
                        role = item.get("role")
                        if role not in {"assistant", "tool"}:
                            continue
                        self.observability_manager.on_message_end(
                            session_id=session_id,
                            message_id=message_id,
                            role=role,
                            message_type=item.get("message_type"),
                            tool_call_id=item.get("tool_call_id"),
                            end_ts=item.get("end_ts"),
                            duration_ms=item.get("duration_ms"),
                        )
                except Exception as e:
                    logger.debug(f"SAgent: 发送 message_end 观测事件失败: {e}")

            if self.observability_manager:
                self.observability_manager.on_chain_end(output_data={"status": "finished"}, session_id=session_id)
            self._cache_session_workspace(session_id, session_context)

            # 顺序原则：先做"必须落盘"的副作用（end_request / save / 资源清理），
            # 再尝试把 token_usage 作为最后一条 chunk 推给消费者。
            # 因为 yield 在 finally 里如果遇到 GeneratorExit（消费者断开 / 取消）会
            # 抛 BaseException，必须用 try/except BaseException 兜住，否则
            # 后续清理会被跳过；同时保证就算推送失败，统计文件也已经落地。
            if session_context:
                try:
                    if self.status == SessionStatus.ERROR:
                        request_status = "error"
                    elif self.status == SessionStatus.INTERRUPTED:
                        request_status = "interrupted"
                    else:
                        request_status = "completed"
                    await asyncio.to_thread(session_context.end_request, status=request_status)
                except Exception as exc:
                    logger.warning(f"SAgent: 关闭 per-request tokens 统计失败: {exc}")

            token_usage_chunks: List[MessageChunk] = []
            if session_context:
                try:
                    token_usage_chunks = await self._emit_token_usage_if_any(session_context, session_id)
                except Exception as e:
                    logger.error(f"SAgent: 计算 token usage 失败: {e}")

            if session_context:
                try:
                    logger.debug("SAgent: 会话状态保存")
                    await asyncio.to_thread(
                        session_context.save,
                        session_status=self.status,
                        child_session_ids=list(self.child_session_ids),
                        interrupt_reason=self.interrupt_reason,
                    )
                except Exception as e:
                    logger.error(f"SAgent: 会话状态保存时出错: {e}")
            await self._cleanup_session_resources(session_id)

            # 真正向消费者推送 token_usage 放在最后；任何 yield 异常（含
            # GeneratorExit）都不得影响前面的清理，因此放在所有清理之后。
            for chunk in token_usage_chunks:
                try:
                    yield [chunk]
                except BaseException as e:  # noqa: BLE001 - 包含 GeneratorExit
                    logger.warning(
                        f"SAgent: 发送 token_usage chunk 失败（消费者可能已断开）: "
                        f"{type(e).__name__}: {e}"
                    )
                    break


    async def _execute_agent_phase(
        self,
        session_id: str,
        agent: AgentBase,
        phase_name: str,
        override_config: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[List[MessageChunk], None]:
        session_manager = get_global_session_manager()
        if not session_manager:
            raise RuntimeError(f"SAgent: session_manager 未初始化，session_id={session_id}")
        session = session_manager.get_live_session(session_id)
        if session is None:
            raise RuntimeError(f"SAgent: session 未绑定，session_id={session_id}")
        session_context = session.get_context()
        if session_context is None:
            raise RuntimeError(f"SAgent: session_context 未绑定，session_id={session_id}")

        logger.info(f"SAgent: 使用 {agent.agent_description} 智能体，{phase_name}阶段")
        # 检查中断
        if session.should_interrupt():
            logger.info(f"SAgent: {phase_name} 阶段被中断，会话ID: {session_id}")
            return

        async for chunk in agent.run_stream(session_context):
            # 在每个块之间检查中断
            if session.should_interrupt():
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
        self.clear_context()

    async def _emit_token_usage_if_any(self, session_context: SessionContext, session_id: str) -> list[MessageChunk]:
        """生成 token_usage MessageChunk。

        约定：只要 session_context 存在，本方法**一定**返回一条 chunk，便于上游
        无论会话因何种原因结束（completed / interrupted / error / 未发生 LLM 调用）
        都能拿到 token_usage 终态消息；统计字段为空时也保留稳定结构与 model 信息。
        """
        if not session_context:
            return []

        token_usage: Dict[str, Any]
        try:
            token_usage = session_context.get_tokens_usage_info() or {}
        except Exception as e:
            logger.error(f"SAgent: 计算 token_usage 失败，会话 {session_id}: {e}")
            token_usage = {}

        token_usage.setdefault("total_info", {})
        token_usage.setdefault("per_step_info", [])
        token_usage.setdefault("models", [])

        # 兜底从 agent_config.llmConfig 取主 model，避免 0 LLM 调用 / 全部流式无 usage 时 model 缺失
        primary_model = token_usage["total_info"].get("model")
        if not primary_model:
            try:
                agent_cfg = getattr(session_context, "agent_config", None) or {}
                llm_cfg = agent_cfg.get("llmConfig") or {}
                primary_model = llm_cfg.get("model") or None
            except Exception:
                primary_model = None
        if primary_model:
            token_usage["total_info"]["model"] = primary_model
            if primary_model not in token_usage["models"]:
                token_usage["models"].insert(0, primary_model)

        logger.info(
            f"SAgent: 生成 token_usage MessageChunk，会话 {session_id}: "
            f"model={primary_model} steps={len(token_usage['per_step_info'])} "
            f"total={token_usage['total_info']}"
        )

        return [
            MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content="",
                message_type=MessageType.TOKEN_USAGE.value,
                metadata={
                    "token_usage": token_usage,
                    "model": primary_model,
                    "models": list(token_usage.get("models") or []),
                    "session_id": session_id,
                },
            )
        ]

    def _cache_session_workspace(self, session_id: Optional[str], session_context: Optional[SessionContext]):
        if not session_id or not session_context:
            return
        try:
            manager = get_global_session_manager()
            if manager:
                manager.cache_session_workspace(
                    session_id,
                    session_context.session_workspace,
                    parent_session_id=getattr(session_context, 'parent_session_id', None),
                )
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

        from sagents.session_registry import SessionRegistry
        db_path = os.path.join(self.session_root_space, "sessions_index.sqlite")
        need_migrate = not os.path.exists(db_path)
        os.makedirs(self.session_root_space, exist_ok=True)
        self._registry = SessionRegistry(db_path, root_dir=self.session_root_space)
        if need_migrate:
            self._migrate_from_filesystem()

    def _migrate_from_filesystem(self):
        """One-time migration: scan existing directories and populate the SQLite registry."""
        if not os.path.exists(self.session_root_space):
            logger.info(f"SessionManager: Session root space does not exist: {self.session_root_space}")
            return

        logger.info(f"SessionManager: Migrating existing sessions from {self.session_root_space} into SQLite registry")
        entries = []
        try:
            with os.scandir(self.session_root_space) as root_entries:
                for entry in root_entries:
                    if not entry.is_dir():
                        continue
                    entry_path = entry.path
                    if os.path.exists(os.path.join(entry_path, "session_context.json")) or os.path.exists(os.path.join(entry_path, "messages.json")):
                        entries.append((entry.name, entry_path, None))
                        logger.debug(f"Migrating root session: {entry.name}")

                    sub_sessions_dir = os.path.join(entry_path, "sub_sessions")
                    if not os.path.isdir(sub_sessions_dir):
                        continue
                    with os.scandir(sub_sessions_dir) as sub_entries:
                        for sub_entry in sub_entries:
                            if not sub_entry.is_dir():
                                continue
                            sub_entry_path = sub_entry.path
                            if os.path.exists(os.path.join(sub_entry_path, "session_context.json")) or os.path.exists(os.path.join(sub_entry_path, "messages.json")):
                                entries.append((sub_entry.name, sub_entry_path, entry.name))
                                logger.debug(f"Migrating sub session: {sub_entry.name}")
        except FileNotFoundError:
            logger.info(f"SessionManager: Session root space disappeared during migration: {self.session_root_space}")
            return
        except Exception as e:
            logger.warning(f"SessionManager: Failed to scan sessions in {self.session_root_space}: {e}")
            return

        if entries:
            self._registry.register_batch(entries)
        logger.info(f"SessionManager: Migrated {len(entries)} sessions into SQLite registry")

    def _is_sub_session(self, session_id: str) -> bool:
        """判断是否为子会话"""
        return self._registry.is_sub_session(session_id)

    def get_parent_session_id(self, session_id: str) -> Optional[str]:
        """获取父会话 ID"""
        return self._registry.get_parent_session_id(session_id)

    def get_session_workspace(self, session_id: str, only_all_session_paths: bool = False) -> Optional[str]:
        """
        获取指定 session 的工作区路径
        
        Args:
            session_id: 会话 ID（全局唯一）
            only_all_session_paths: 保留参数以兼容旧调用，行为不变
        
        Returns:
            工作区路径，找不到则返回 None
        """
        return self._registry.get_workspace(session_id)

    def cache_session_workspace(self, session_id: str, session_workspace: Optional[str], parent_session_id: Optional[str] = None):
        if not session_id or not session_workspace:
            return
        self._registry.register(session_id, session_workspace, parent_session_id=parent_session_id)

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
        获取 Session。优先返回内存中的活对象；如果不存在，则尝试从磁盘恢复。
        
        Args:
            session_id: 会话 ID
        
        Returns:
            Session 实例，找不到则返回 None
        """
        session = self._sessions.get(session_id)
        if session:
            return session

        workspace = self.get_session_workspace(session_id)
        if not workspace:
            return None

        session = self.get_or_create(session_id)
        session.set_workspace(workspace)
        loaded = session.load_persisted_state(workspace)
        if not loaded and not session.has_context() and not session.get_messages():
            self._sessions.pop(session_id, None)
            return None
        return session

    def get_live_session(self, session_id: str) -> Optional[Session]:
        """仅获取内存中的活 session，不做磁盘恢复。"""
        return self._sessions.get(session_id)

    def _get_live_session(self, session_id: str) -> Optional[Session]:
        """兼容旧内部调用，优先使用 get_live_session。"""
        return self.get_live_session(session_id)

    def register_session_context(self, session_id: str, session_context: SessionContext):
        """注册 SessionContext"""
        session = self.get_or_create(session_id)
        session.set_context(session_context)
        session.set_workspace(getattr(session_context, "session_workspace", None))

    def remove_session_context(self, session_id: str):
        """移除 SessionContext"""
        session = self.get_live_session(session_id)
        if session:
            session.clear_context()

    def close_session(self, session_id: str):
        """关闭 Session"""
        session = self._sessions.pop(session_id, None)
        if session:
            try:
                logger.cleanup_session_logger(session_id)
            except Exception as e:
                logger.warning(f"清理session {session_id} 日志资源时出错: {e}")
            session.close()

    def interrupt_session(self, session_id: str, message: str = "用户请求中断") -> bool:
        """请求中断指定会话，并级联到已登记的子会话。"""
        session = self.get_live_session(session_id)
        if not session:
            return False

        try:
            return session.request_interrupt(message)
        except Exception as e:
            logger.warning(f"SessionManager: 中断会话 {session_id} 失败: {e}")
            return False

    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取 Session 状态"""
        session = self.get(session_id)
        if session:
            return {"status": session.get_status().value}
        return None

    def list_active_sessions(self) -> List[Dict[str, Any]]:
        """列出活跃的根会话（子会话在运行期保留于内存，但不对外展示）"""
        return [
            {
                "session_id": sid,
                "status": sess.get_status().value,
                "start_time": sess.get_start_time(),
            }
            for sid, sess in self._sessions.items()
            if sess.has_context() and not self._is_sub_session(sid)
        ]

    def get_session_messages(self, session_id: str) -> List[MessageChunk]:
        """
        获取会话消息历史
        
        Args:
            session_id: 会话 ID（全局唯一）
        """
        # 1. 尝试从内存获取（只有根会话会保留在内存中）
        session = self.get(session_id)
        if session:
            return session.get_messages()

        # 2. 尝试从磁盘获取（支持子会话按需加载）
        session_workspace_path = self.get_session_workspace(session_id)
        if not session_workspace_path:
             logger.warning(f"SessionManager: 无法找到会话 {session_id} 的路径")
             return []

        messages_path = os.path.join(session_workspace_path, "messages.json")
        if not os.path.exists(messages_path):
            return []
            
        try:
            raw_messages = _load_json_file_sync(messages_path)
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

    def get_tasks_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        session = self.get(session_id)
        if not session:
            return None
        return session.get_tasks_status()

    def save_session(self, session_id: str) -> bool:
        session = self.get(session_id)
        if not session or not session.has_context():
            return False
        try:
            session.get_context().save(
                session_status=session.get_status(),
                child_session_ids=list(session.child_session_ids),
                interrupt_reason=session.interrupt_reason,
            )
            return True
        except Exception as exc:
            logger.warning(f"SessionManager: 保存会话 {session_id} 失败: {exc}")
            return False


def build_conversation_messages_view(session_id: str) -> Dict[str, Any]:
    """从 sagents 会话中构造统一的对话消息视图。"""
    session_manager = get_global_session_manager()
    if not session_manager:
        logger.error("会话管理器未初始化")
        return {"conversation_id": session_id, "messages": []}

    raw_messages = list(session_manager.get_session_messages(session_id))
    messages: List[Dict[str, Any]] = []
    seen_message_keys = set()

    def append_message(message_dict: Dict[str, Any]):
        message_key = (
            message_dict.get("message_id")
            or (
                message_dict.get("role"),
                message_dict.get("tool_call_id"),
                json.dumps(message_dict.get("tool_calls", []), ensure_ascii=False, sort_keys=True),
                json.dumps(message_dict.get("content"), ensure_ascii=False, sort_keys=True),
                message_dict.get("timestamp"),
            )
        )
        if message_key in seen_message_keys:
            return
        seen_message_keys.add(message_key)
        messages.append(message_dict)

    for message in raw_messages:
        result = message.to_dict()
        append_message(result)

        if result.get("role") != "assistant" or not result.get("tool_calls"):
            continue

        for tool_call in result["tool_calls"]:
            if tool_call.get("function", {}).get("name") != "sys_delegate_task":
                continue

            try:
                arguments = tool_call["function"]["arguments"]
                args = json.loads(arguments) if isinstance(arguments, str) else arguments
                tasks = args.get("tasks", [])
                if not isinstance(tasks, list):
                    continue

                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    sub_session_id = task.get("session_id")
                    if not sub_session_id:
                        continue
                    if sub_session_id == session_id:
                        logger.warning(
                            f"build_conversation_messages_view: 跳过与当前会话相同的子会话引用 session_id={session_id}"
                        )
                        continue
                    for sub_msg in session_manager.get_session_messages(sub_session_id):
                        append_message(sub_msg.to_dict())
            except Exception as e:
                logger.warning(f"处理子任务消息失败: {e}")

    return {
        "conversation_id": session_id,
        "messages": messages,
    }


# 全局 SessionManager 实例
_global_session_manager: Optional[SessionManager] = None


def initialize_global_session_manager(session_root_space: str, enable_obs: bool = True):
    """初始化全局 SessionManager"""
    global _global_session_manager
    _global_session_manager = SessionManager(session_root_space, enable_obs)
    return _global_session_manager


def get_global_session_manager(session_root_space: Optional[str] = None, enable_obs: bool = True) -> SessionManager:
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
