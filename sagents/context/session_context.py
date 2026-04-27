# 负责管理会话的上下文，以及过程中产生的日志以及状态记录。
import asyncio
import time
import threading
import uuid
from typing import Dict, Any, Optional, List, Union
from enum import Enum
from concurrent.futures import ThreadPoolExecutor

from sagents.context.messages.message import MessageChunk
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_memory import create_session_memory_manager
from sagents.skill import SkillProxy, SkillManager
from sagents.skill.sandbox_skill_manager import SandboxSkillManager
from sagents.utils.prompt_manager import prompt_manager
from sagents.context.workflows import WorkflowManager

from sagents.utils.logger import logger
from sagents.utils.lock_manager import lock_manager, UnifiedLock
from sagents.utils.serialization import make_serializable
import json
import os
import re
import datetime
import pytz
from sagents.utils.sandbox import SandboxProviderFactory, SandboxConfig, SandboxType
from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.common_utils import detect_machine_environment

_session_context_file_io_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="session-context-io")

class SessionStatus(Enum):
    """会话状态枚举"""
    IDLE = "idle"                    # 空闲状态
    RUNNING = "running"              # 运行中
    INTERRUPTED = "interrupted"      # 被中断
    COMPLETED = "completed"          # 已完成
    ERROR = "error"                  # 错误状态


class SessionContext:

    def __init__(
        self,
        session_id: str,
        user_id: str,
        agent_id: str,
        session_root_space: str,
        sandbox_agent_workspace: Optional[str] = None,
        volume_mounts: Optional[List[VolumeMount]] = None,
        sandbox_id: Optional[str] = None,
        context_budget_config: Optional[Dict[str, Any]] = None,
        system_context: Optional[Dict[str, Any]] = None,
        tool_manager: Optional[Any] = None,
        skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
        parent_session_id: Optional[str] = None,
    ):
        # 基础身份与外部依赖
        self.session_id = session_id
        self.user_id = user_id
        self.agent_id = agent_id
        self.system_context: Dict[str, Any] = system_context or {}
        self.session_root_space = session_root_space

        # workspace 配置
        self.sandbox_agent_workspace: Optional[str] = sandbox_agent_workspace  # Agent 工作目录（沙箱内路径）
        self.volume_mounts: List[VolumeMount] = volume_mounts or []  # 额外卷挂载
        self.sandbox_id: Optional[str] = sandbox_id
        # sandbox 会在 init_more() 中初始化；先占位避免半初始化上下文直接 AttributeError
        self.sandbox: Optional[Any] = None

        self.tool_manager = tool_manager
        self.skill_manager = skill_manager
        self.sandbox_skill_manager: Optional[SandboxSkillManager] = None
        self.parent_session_id = parent_session_id
        self._init_runtime_state(context_budget_config=context_budget_config)
        # 注意：init_more 不再在 __init__ 中自动调用，需要调用方显式调用
        self._session_root_space = session_root_space
        self._volume_mounts = volume_mounts

    @property
    def effective_skill_manager(self) -> Optional[Any]:
        """
        Agent 提示词、任务分析、工具建议等使用的技能视图：若沙箱内已成功加载技能，
        则与 load_skill 一致采用 agent workspace/skills 副本；否则回退宿主 SkillProxy / SkillManager。
        """
        if self.sandbox_skill_manager is not None and self.sandbox_skill_manager.list_skills():
            return self.sandbox_skill_manager
        return self.skill_manager

    async def init_more(self, session_root_space: Optional[str] = None):
        """
        初始化 SessionContext（异步方法，需要显式调用）
        
        Args:
            session_root_space: 会话根空间路径（宿主机），用于存储会话数据
        """
        # 使用构造函数中传入的参数作为默认值
        if session_root_space is None:
            session_root_space = getattr(self, '_session_root_space', None)
            
        # 从环境变量获取沙箱模式，默认使用本地沙箱
        sandbox_mode_str = os.environ.get("SAGE_SANDBOX_MODE", "local").lower()
        if sandbox_mode_str == "passthrough":
            sandbox_mode = SandboxType.PASSTHROUGH
        elif sandbox_mode_str == "remote":
            sandbox_mode = SandboxType.REMOTE
        else:
            sandbox_mode = SandboxType.LOCAL
        logger.debug(f"SessionContext: sandbox_mode: {sandbox_mode.value}")
        
        # 解析工作空间路径
        # - session_workspace: 会话数据路径（宿主机）
        self._resolve_workspace_paths(session_root_space)
        
        # 初始化外部路径和上下文
        self._init_external_paths_and_context()
        
        # 初始化沙箱和文件系统
        await self._init_sandbox_and_file_system(sandbox_mode=sandbox_mode)
        
        # 准备工作区引导文件（通过沙箱接口，在沙箱初始化后执行）
        await self._prepare_workspace_bootstrap_files()
        
        # 注册并准备技能
        await self._register_and_prepare_skills()
        
        # 最终化系统上下文
        await self._finalize_system_context()

        # 加载已持久化的消息
        await asyncio.to_thread(self._load_persisted_messages)
        
        # 清理过期的待办任务（异步执行，确保 system_context 正确加载）
        try:
            await self._cleanup_expired_todo_tasks()
        except Exception as e:
            logger.warning(f"SessionContext: 清理过期任务失败: {e}")

    def _init_runtime_state(self, context_budget_config: Optional[Dict[str, Any]] = None):
        # 运行期状态容器（与 I/O、会话生命周期绑定）
        self.llm_requests_logs: List[Dict[str, Any]] = []
        self.thread_id = threading.get_ident()
        self.start_time = time.time()
        self._perf_origin = time.perf_counter()
        self.end_time = None
        self._status = SessionStatus.IDLE
        self.message_manager = MessageManager(context_budget_config=context_budget_config)
        self.workflow_manager = WorkflowManager()
        self.audit_status: Dict[str, Any] = {}
        self.session_memory_manager = create_session_memory_manager()
        self.agent_config: Dict[str, Any] = {}
        self.custom_sub_agents: List[Dict[str, Any]] = []
        self.orchestrator: Optional[Any] = None
        self.child_session_ids: List[str] = []
        self.execution_timeline_events: List[Dict[str, Any]] = []
        self._message_timing: Dict[str, Dict[str, Any]] = {}
        # per-request tokens 累加器（详见 start_request / end_request / add_llm_request）
        self._current_request: Optional[Dict[str, Any]] = None
        self._request_lock = threading.Lock()
        self._llm_request_save_lock = threading.Lock()
        self.record_timing_event(
            "session_start",
            status=self.status.value,
            session_id=self.session_id,
        )

    def _now_perf_ms(self) -> float:
        return (time.perf_counter() - self._perf_origin) * 1000.0

    def record_timing_event(self, event_type: str, **fields: Any) -> None:
        try:
            event = {
                "event_type": event_type,
                "timestamp": time.time(),
                "perf_ms": self._now_perf_ms(),
            }
            event.update(fields)
            self.execution_timeline_events.append(make_serializable(event))
        except Exception as e:
            logger.debug(f"SessionContext: 记录 timing 事件失败 {event_type}: {e}")

    @property
    def status(self) -> SessionStatus:
        return self._status

    @status.setter
    def status(self, value: SessionStatus) -> None:
        self._status = value

    def _record_message_timing(self, message: Union[MessageChunk, Dict[str, Any]]) -> None:
        try:
            if isinstance(message, MessageChunk):
                msg = message.to_dict()
            elif isinstance(message, dict):
                msg = message
            else:
                return

            message_id = str(msg.get("message_id") or "").strip()
            if not message_id:
                return

            now_ts = time.time()
            now_perf_ms = self._now_perf_ms()
            role = msg.get("role")
            message_type = msg.get("message_type") or msg.get("type")

            stat = self._message_timing.get(message_id)
            if not stat:
                stat = {
                    "message_id": message_id,
                    "role": role,
                    "message_type": message_type,
                    "tool_call_id": msg.get("tool_call_id"),
                    "start_ts": now_ts,
                    "start_perf_ms": now_perf_ms,
                    "end_ts": now_ts,
                    "end_perf_ms": now_perf_ms,
                }
                self._message_timing[message_id] = stat
                self.record_timing_event(
                    "message_start",
                    message_id=message_id,
                    role=role,
                    message_type=message_type,
                )
            else:
                stat["end_ts"] = now_ts
                stat["end_perf_ms"] = now_perf_ms
                if not stat.get("role") and role:
                    stat["role"] = role
                if not stat.get("message_type") and message_type:
                    stat["message_type"] = message_type

        except Exception as e:
            logger.debug(f"SessionContext: 记录 message 时序失败: {e}")

    def _build_execution_timing_summary(self) -> Dict[str, Any]:
        messages = list(self._message_timing.values())
        messages.sort(key=lambda item: float(item.get("start_ts") or 0.0))

        message_timings: List[Dict[str, Any]] = []
        for item in messages:
            start_ts = float(item.get("start_ts") or 0.0)
            end_ts = float(item.get("end_ts") or start_ts)
            message_timings.append(
                {
                    "message_id": item.get("message_id"),
                    "role": item.get("role"),
                    "message_type": item.get("message_type"),
                    "tool_call_id": item.get("tool_call_id"),
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "duration_ms": max(0.0, (end_ts - start_ts) * 1000.0),
                    "start_perf_ms": float(item.get("start_perf_ms") or 0.0),
                    "end_perf_ms": float(item.get("end_perf_ms") or 0.0),
                }
            )

        message_intervals: List[Dict[str, Any]] = []
        for i in range(1, len(message_timings)):
            prev_item = message_timings[i - 1]
            cur_item = message_timings[i]
            gap_start_to_start_ms = max(
                0.0,
                (float(cur_item["start_ts"]) - float(prev_item["start_ts"])) * 1000.0,
            )
            gap_prev_end_to_cur_start_ms = max(
                0.0,
                (float(cur_item["start_ts"]) - float(prev_item["end_ts"])) * 1000.0,
            )
            message_intervals.append(
                {
                    "from_message_id": prev_item["message_id"],
                    "to_message_id": cur_item["message_id"],
                    "start_to_start_gap_ms": gap_start_to_start_ms,
                    "prev_end_to_cur_start_gap_ms": gap_prev_end_to_cur_start_ms,
                }
            )

        flow_node_timings = [
            evt
            for evt in self.execution_timeline_events
            if evt.get("event_type") == "flow_node_end"
        ]

        return {
            "session_id": self.session_id,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "generated_at": time.time(),
            "total_timeline_events": len(self.execution_timeline_events),
            "message_count": len(message_timings),
            "message_timings": message_timings,
            "message_intervals": message_intervals,
            "flow_node_timings": flow_node_timings,
        }

    def add_messages(self, messages: Union[MessageChunk, List[MessageChunk], List[Dict[str, Any]]]) -> None:
        """
        Add messages to the message manager with session_id validation.
        
        Args:
            messages: A message chunk or a list of message chunks/dicts.
        """
        if not isinstance(messages, list):
            messages_list = [messages]
        else:
            messages_list = messages
            
        valid_messages = []
        for msg in messages_list:
            msg_session_id = None
            if isinstance(msg, MessageChunk):
                msg_session_id = msg.session_id
            elif isinstance(msg, dict):
                msg_session_id = msg.get('session_id')
                
            if msg_session_id is None or msg_session_id == self.session_id:
                valid_messages.append(msg)

        if valid_messages:
            for msg in valid_messages:
                self._record_message_timing(msg)
            self.message_manager.add_messages(valid_messages)

    def get_messages(self) -> List[MessageChunk]:
        """
        获取会话中的所有消息
        
        Returns:
            List[MessageChunk]: 消息列表
        """
        return self.message_manager.messages

    def _write_default_md_file(self, file_path: str, prompt_key: str, file_label: str):
        """
        写入默认的Markdown文件到指定路径。
        
        Args:
            file_path: 目标文件路径
            prompt_key: 提示模板键名
            file_label: 文件标签，用于日志记录
        """
        try:
            language = self.get_language()
            default_content = prompt_manager.get_prompt(
                prompt_key,
                agent="SessionContext",
                language=language,
            )
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(default_content)
        except Exception as e:
            logger.warning(f"SessionContext: Failed to create {file_label}: {e}")

    def _submit_default_md_file(self, file_path: str, prompt_key: str, file_label: str):
        """
        异步提交创建默认Markdown文件的任务。
        
        Args:
            file_path: 目标文件路径
            prompt_key: 提示模板键名
            file_label: 文件标签，用于日志记录
        """
        try:
            _session_context_file_io_pool.submit(
                self._write_default_md_file,
                file_path,
                prompt_key,
                file_label,
            )
        except Exception as e:
            logger.warning(f"SessionContext: Failed to submit {file_label} creation: {e}")

    def _resolve_workspace_paths(self, session_root_space: str) -> None:
        """
        解析会话空间与工作空间路径。

        路径说明：
        - session_workspace: 会话数据存储路径（消息、上下文等），始终在宿主机
        - volume_mounts: 卷挂载配置
        - sandbox_agent_workspace: Agent 工作区的沙箱内路径

        Args:
            session_root_space: 会话根空间路径（宿主机）
        """
        if not session_root_space or not os.path.exists(session_root_space):
            raise ValueError(f"SessionContext 初始化需要传入有效的 session_root_space: {session_root_space}")

        self.session_root_space = os.path.abspath(session_root_space)

        # 确定 session_workspace（会话数据，始终在宿主机）
        parent_session_id = self.parent_session_id or self.system_context.get("parent_session_id")

        if parent_session_id:
            try:
                from sagents.session_runtime import get_global_session_manager
                manager = get_global_session_manager()
                parent_session = manager.get(parent_session_id)
                if parent_session and parent_session.session_context:
                    self.session_workspace = os.path.join(parent_session.session_context.session_workspace, "sub_sessions", self.session_id)
                else:
                    raise ValueError(f"Parent session {parent_session_id} not found or not initialized.")
            except ImportError:
                 logger.error("SessionContext: Could not import get_global_session_manager.")
                 raise ValueError("Could not resolve parent session workspace due to import error.")
            except Exception as e:
                 logger.error(f"SessionContext: Error resolving parent workspace: {e}")
                 raise ValueError(f"Failed to resolve parent session workspace for {parent_session_id}: {e}")
        else:
            self.session_workspace = os.path.join(self.session_root_space, self.session_id)

        os.makedirs(self.session_workspace, exist_ok=True)

    async def _prepare_workspace_bootstrap_files(self):
        """
        准备工作区引导文件（通过沙箱接口）

        在沙箱初始化后调用，通过沙箱接口创建 AGENT.md, USER.md, SOUL.md, IDENTITY.md, MEMORY.md
        """
        use_claw_mode = os.environ.get("SAGE_USE_CLAW_MODE", "true").lower() == "true"
        if 'use_claw_mode' in self.system_context:
            use_claw_mode = self.system_context.get("use_claw_mode", use_claw_mode)
            if isinstance(use_claw_mode, str):
                use_claw_mode = use_claw_mode.lower() == "true"
        logger.debug(f"SessionContext: use_claw_mode: {use_claw_mode}")

        if not use_claw_mode:
            return

        bootstrap_files = [
            ("AGENT.md", "default_agent_md"),
            ("USER.md", "default_user_md"),
            ("SOUL.md", "default_soul_md"),
            ("IDENTITY.md", "default_identity_md"),
            ("MEMORY.md", "default_memory_md"),
        ]

        for filename, content_key in bootstrap_files:
            file_path = os.path.join(self.sandbox_agent_workspace, filename)
            try:
                exists = await self.sandbox.file_exists(file_path)
                if not exists:
                    content = self._get_default_md_content(content_key, filename)
                    if content:
                        await self.sandbox.write_file(file_path, content)
                        logger.debug(f"创建引导文件: {file_path}")
            except Exception as e:
                logger.warning(f"创建引导文件失败 {file_path}: {e}")

        try:
            memory_dir = os.path.join(self.sandbox_agent_workspace, "memory")
            await self.sandbox.ensure_directory(memory_dir)
        except Exception as e:
            logger.warning(f"创建 memory 目录失败: {e}")

    def _get_default_md_content(self, content_key: str, filename: str) -> str:
        """获取默认的 markdown 文件内容"""
        # 使用 prompt_manager 获取多语言内容，默认使用中文
        # agent="SessionContext" 指定从 session_context_prompts.py 中获取
        try:
            content = prompt_manager.get_prompt(content_key, agent="SessionContext", language=self.get_language())
            return content
        except Exception as e:
            logger.warning(f"获取默认内容失败 {content_key}: {e}")
            return ""

    def _init_external_paths_and_context(self):
        """
        初始化外部路径和系统上下文
        """
        self.external_paths = self.system_context.get('external_paths') or []
        self.system_context.pop("可以访问的其他路径文件夹", None)
        self.system_context.pop("external_paths", None)
        if isinstance(self.external_paths, str):
            self.external_paths = [self.external_paths]
        if len(self.external_paths) > 0:
            self.external_paths = [os.path.abspath(path) for path in self.external_paths]
            self.system_context['external_paths'] = self.external_paths
        now = datetime.datetime.now().astimezone()
        current_time_str = now.strftime('%a, %d %b %Y %H:%M:%S %z')
        if self.system_context.get('current_time') is None:
            self.system_context['current_time'] = current_time_str

    async def _init_sandbox_and_file_system(self, sandbox_mode: SandboxType):
        """
        初始化沙箱环境和文件系统

        Args:
            sandbox_mode: 沙箱模式 (LOCAL, PASSTHROUGH, REMOTE)
        """
        logger.info(f"SessionContext: 开始初始化沙箱环境，模式: {sandbox_mode.value}, "
                   f"volume_mounts_count={len(self.volume_mounts)}")
        t0 = time.time()

        if sandbox_mode == SandboxType.REMOTE:
            if not self.sandbox_agent_workspace:
                self.sandbox_agent_workspace = "/sage-workspace"
            # 远程沙箱配置
            config = SandboxConfig(
                sandbox_id=self.sandbox_id or self.user_id or self.session_id,
                mode=sandbox_mode,
                sandbox_agent_workspace=self.sandbox_agent_workspace,
                volume_mounts=self.volume_mounts,  # 远程沙箱可能支持的挂载
                # 远程沙箱特定的配置
                remote_provider=os.environ.get("SAGE_REMOTE_PROVIDER", "opensandbox"),
                remote_server_url=os.environ.get("OPENSANDBOX_URL"),
                remote_api_key=os.environ.get("OPENSANDBOX_API_KEY"),
                remote_image=os.environ.get("OPENSANDBOX_IMAGE", "opensandbox/code-interpreter:v1.0.2"),
                remote_timeout=int(os.environ.get("OPENSANDBOX_TIMEOUT", "1800")),
                remote_persistent=True,
                remote_sandbox_ttl=3600,
            )
        else:
            # 本地/直通沙箱配置
            # 构建 volume_mounts：包含原有的 volume_mounts 和 external_paths
            volume_mounts = list(self.volume_mounts) if self.volume_mounts else []

            # 将 external_paths 添加到 volume_mounts，映射路径与 host_path 相同
            for path in (self.external_paths or []):
                abs_path = os.path.abspath(path)
                volume_mounts.append(VolumeMount(
                    host_path=abs_path,
                    mount_path=abs_path  # 映射路径与 host_path 相同
                ))

            config = SandboxConfig(
                sandbox_id=self.user_id or self.session_id,
                mode=sandbox_mode,
                sandbox_agent_workspace=self.sandbox_agent_workspace,
                volume_mounts=volume_mounts,  # 传递所有卷挂载配置
                # 本地沙箱特定的配置
                cpu_time_limit=int(os.environ.get("SAGE_LOCAL_CPU_TIME_LIMIT", "300")),
                memory_limit_mb=int(os.environ.get("SAGE_LOCAL_MEMORY_LIMIT_MB", "4096")),
                linux_isolation_mode=os.environ.get("SAGE_LOCAL_LINUX_ISOLATION", "bwrap"),
                macos_isolation_mode=os.environ.get("SAGE_LOCAL_MACOS_ISOLATION", "seatbelt")
            )

        self.sandbox = await SandboxProviderFactory.create(config)
        if sandbox_mode == SandboxType.REMOTE:
            self.sandbox_agent_workspace = self.sandbox.workspace_path

        logger.info(f"SessionContext: 沙箱环境初始化完成，耗时: {time.time() - t0:.3f}s")
        

    async def _register_and_prepare_skills(self):
        """
        注册并准备技能，主要是同步技能到沙箱
        """
        if self.skill_manager and self.skill_manager.list_skills() and self.tool_manager:
            # 确保 load_skill 工具已注册
            if not self.tool_manager.get_tool('load_skill'):
                try:
                    from sagents.skill.skill_tool import SkillTool
                    skill_tool = SkillTool()
                    self.tool_manager.register_tools_from_object(skill_tool)
                    logger.info("SessionContext: Automatically registered load_skill tool from SkillTool instance")
                except Exception as e:
                    logger.error(f"SessionContext: Failed to register load_skill tool: {e}")

        if self.skill_manager and self.skill_manager.list_skills():
            logger.debug(f"SessionContext: 当前可用的技能: {list(self.skill_manager.skills.keys())}, 准备同步技能到沙箱")
            t1 = time.time()
            try:
                # 初始化沙箱技能管理器并同步技能
                await self._init_sandbox_skill_manager()
                logger.debug(f"SessionContext: 技能同步完成，耗时: {time.time() - t1:.3f}s")
            except Exception as e:
                logger.error(f"SessionContext: 技能同步失败: {e}", exc_info=True)
        else:
            logger.warning("SessionContext: SkillManager 未初始化，跳过技能复制")

    async def _init_sandbox_skill_manager(self):
        """
        初始化沙箱技能管理器：按宿主 SkillProxy 给出的名称，仅从沙箱内
        ``<agent_workspace>/skills/<name>/`` 加载（与挂载目录一致），供 load_skill 与提示词使用。
        """
        # 创建沙箱技能管理器
        skills_dir = os.path.join(self.sandbox_agent_workspace, "skills")
        self.sandbox_skill_manager = SandboxSkillManager(self.sandbox, skills_dir)
        await self.sandbox_skill_manager.sync_from_host(self.skill_manager)

    async def _finalize_system_context(self):
        """
        最终化系统上下文，设置私有工作区、用户ID和会话ID
        """
        # 设置私有工作区
        workspace = self.sandbox_agent_workspace
        self.system_context['private_workspace'] = workspace
        # 设置用户ID
        if self.user_id:
            self.system_context['user_id'] = self.user_id
        # 设置会话ID
        self.system_context['session_id'] = self.session_id
        # 设置机器运行环境摘要
        self.system_context['machine_environment'] = detect_machine_environment(
            sandbox=self.sandbox,
            sandbox_agent_workspace=self.sandbox_agent_workspace,
        )
        # 设置文件权限路径  
        permission_paths = [self.system_context['private_workspace']]
        logger.debug(f"self.external_paths: {self.external_paths}")
        if self.external_paths and isinstance(self.external_paths, list):
            permission_paths.extend([str(p) for p in self.external_paths])
        paths_str = ", ".join(permission_paths)
        sandbox_root = workspace
        common_dirs = ["data", "projects", "temp", "logs"]
        for d in common_dirs:
            dir_path = os.path.join(sandbox_root, d)
            if hasattr(self.sandbox, 'ensure_directory'):
                await self.sandbox.ensure_directory(dir_path)
            else:
                # 沙箱不支持 ensure_directory 接口，报错
                raise NotImplementedError(
                    f"沙箱 {type(self.sandbox).__name__} 不支持 ensure_directory 接口，"
                    f"无法创建目录: {dir_path}"
                )
        self.system_context['file_permission'] = (
            f"only allow read and write files in: {paths_str} (Note: {workspace} is your private sandbox). "
            f"Please save files in the pre-created folders: {', '.join(common_dirs)} and use absolute paths; avoid creating extra directories in the root."
        )
        # 设置响应语言
        self.system_context['response_language'] = self.system_context.get('response_language', "en-US")

    def _load_persisted_messages(self):
        """
        加载持久化的消息历史
        """
        # 1. 尝试加载 messages.json
        try:
            messages_path = os.path.join(self.session_workspace, "messages.json")
            if os.path.exists(messages_path):
                with open(messages_path, "r", encoding="utf-8") as f:
                    messages_data = json.load(f)
                    if isinstance(messages_data, list):
                        self.message_manager.messages = [MessageChunk.from_dict(msg) for msg in messages_data]
                        logger.info(f"SessionContext: Loaded {len(self.message_manager.messages)} messages from messages.json")
                        return
        except UnicodeDecodeError:
            logger.warning(f"SessionContext: messages.json decode failed, file may be in legacy encoding, will start with empty messages")
        except Exception as e:
            logger.warning(f"SessionContext: Failed to load messages.json: {e}")

    def _prepare_llm_request_file_path(self, llm_request: Dict[str, Any]) -> str:
        llm_request_folder = os.path.join(self.session_workspace, "llm_request")
        os.makedirs(llm_request_folder, exist_ok=True)

        existing_files = os.listdir(llm_request_folder)
        max_index = -1
        for file in existing_files:
            if file.endswith(".json"):
                try:
                    index = int(file.split("_")[0])
                    max_index = max(max_index, index)
                except ValueError:
                    continue

        file_name = (
            f"{max_index + 1}_{llm_request['request'].get('step_name', 'unknown')}_"
            f"{time.strftime('%Y%m%d%H%M%S', time.localtime(llm_request['timestamp']))}.json"
        )
        return os.path.join(llm_request_folder, file_name)

    def _save_llm_request_sync(self, llm_request: Dict[str, Any]) -> str:
        with self._llm_request_save_lock:
            file_path = self._prepare_llm_request_file_path(llm_request)
            serializable_request = {
                "request": make_serializable(llm_request['request']),
                "response": make_serializable(llm_request['response']),
                "timestamp": llm_request['timestamp']
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(serializable_request, f, ensure_ascii=False, indent=4)
            return file_path

    async def _cleanup_expired_todo_tasks(self):
        try:
            from sagents.tool.impl.todo_tool import ToDoTool
            await ToDoTool().clean_old_tasks(session_id=self.session_id, time_threshold=1800)
        except Exception as e:
            logger.warning(f"SessionContext: 清理过期任务失败: {e}")


    async def load_recent_skill_to_context(self):
        """
        检测历史消息，收集所有使用过的 load_skill skill，或者用户消息中包含 <skill>name</skill>。
        按时间顺序加载所有 skill（新的在后面），总 token 数限制由 tool_manager 处理。
        """
        if not self.skill_manager:
            return

        # 使用有序字典保持 skill 的顺序（去重，新的覆盖旧的）
        found_skills = {}  # skill_name -> arguments
        
        # 正序遍历消息（从早到晚），这样后面的 skill 会覆盖前面的
        for msg in self.message_manager.messages:
            # Check for <skill> tag in user message
            if msg.role == 'user' and msg.content:
                content_str = ""
                if isinstance(msg.content, str):
                    content_str = msg.content
                elif isinstance(msg.content, list):
                    # Handle multimodal content
                    for part in msg.content:
                        if isinstance(part, dict) and part.get('type') == 'text':
                            content_str += part.get('text', '')
                
                # Check for <skill>...</skill> - 支持多个 skill
                matches = re.findall(r"<skill>(.*?)</skill>", content_str, re.DOTALL)
                for match in matches:
                    skill_name = match.strip()
                    if skill_name:
                        found_skills[skill_name] = {"skill_name": skill_name}
                        logger.info(f"SessionContext: Found skill tag: {skill_name}")

            # Check for load_skill tool call
            if msg.role == 'assistant' and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    if tool_call.get('function', {}).get('name') == 'load_skill':
                        arguments = tool_call['function']['arguments']
                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments)
                            except Exception:
                                continue
                        
                        if isinstance(arguments, dict):
                            skill_name = arguments.get('skill_name')
                            if skill_name:
                                found_skills[skill_name] = arguments
                                logger.info(f"SessionContext: Found skill tool call: {skill_name}")
        
        # 加载所有找到的 skill（按时间顺序）
        if found_skills:
            skill_list = list(found_skills.keys())
            logger.info(f"SessionContext: Loading {len(skill_list)} skills: {skill_list}")
            
            for skill_name, arguments in found_skills.items():
                try:
                    logger.info(f"SessionContext: Loading skill '{skill_name}' via ToolManager...")
                    # 移除 arguments 中的 session_id，避免重复传递
                    args = arguments.copy()
                    args.pop('session_id', None)
                    await self.tool_manager.run_tool_async(
                        tool_name='load_skill',
                        session_id=self.session_id,
                        **args
                    )
                except Exception as e:
                    logger.error(f"SessionContext: Failed to load skill '{skill_name}': {e}")

    def restrict_tools_for_mode(self, agent_mode: str):
        """
        根据 agent_mode 限制工具的使用。
        如果不为 'fibre' 模式，屏蔽 Fibre 相关工具。
        """
        if agent_mode == 'fibre':
            return

        fibre_tools = ['sys_spawn_agent', 'sys_delegate_task', 'sys_finish_task']
        
        # 避免循环引用
        from sagents.tool.tool_manager import ToolManager
        from sagents.tool.tool_proxy import ToolProxy
        
        current_manager = self.tool_manager
        if not current_manager:
            return

        # 获取基础管理器和当前可用工具
        base_manager = None
        available_tools = set()

        if isinstance(current_manager, ToolProxy):
            base_manager = current_manager.tool_manager
            # ToolProxy.list_all_tools_name 返回的是当前 proxy 可用的工具名
            available_tools = set(current_manager.list_all_tools_name())
        elif isinstance(current_manager, ToolManager):
            base_manager = current_manager
            available_tools = set(base_manager.list_all_tools_name())
        else:
            logger.warning(f"SessionContext: Unknown tool manager type: {type(current_manager)}")
            return

        # 检查是否包含需要屏蔽的工具
        tools_to_remove = available_tools.intersection(set(fibre_tools))
        
        if tools_to_remove:
            # 过滤掉 fibre tools
            new_available = list(available_tools - tools_to_remove)
            
            # 创建新的 ToolProxy
            self.tool_manager = ToolProxy(base_manager, new_available)
            logger.info(f"SessionContext: Restricted tools for mode '{agent_mode}'. Removed: {tools_to_remove}")




    def set_agent_config(self, model: Optional[str] = None, model_config: Optional[dict] = None, system_prefix: Optional[str] = None,
                         available_tools: Optional[list] = None, available_skills: Optional[list] = None, system_context: Optional[dict] = None,
                         available_workflows: Optional[dict] = None, deep_thinking: Optional[bool] = None,
                         agent_mode: Optional[str] = None, more_suggest: bool = False,
                         max_loop_count: Optional[int] = None, agent_id: Optional[str] = None,
                         memory_backends: Optional[Dict[str, str]] = None):
        """设置agent配置信息

        Args:
            model: 模型名称或OpenAI客户端实例
            model_config: 模型配置
            system_prefix: 系统前缀

            available_tools: 可用工具列表
            available_skills: 可用技能列表
            system_context: 系统上下文
            available_workflows: 可用工作流
            deep_thinking: 深度思考模式
            agent_mode: 智能体运行模式
            more_suggest: 更多建议模式
            max_loop_count: 最大循环次数
            agent_id: Agent ID (Fibre用)
            memory_backends: 记忆后端配置，如 {"session_history": "bm25", "file_memory": "scoped_index"}
        """
        if max_loop_count is None:
            raise ValueError("max_loop_count is required")
        # 生成与preset_running_agent_config.json格式一致的配置
        current_time = datetime.datetime.now().astimezone()

        # 从model_config中提取llmConfig信息
        llm_config = {}
        if model_config:
            llm_config = {
                "model": model_config.get("model", ""),
                "maxTokens": model_config.get("max_tokens", ""),
                "temperature": model_config.get("temperature", "")
            }

        self.agent_config = {
            "id": str(int(time.time() * 1000)),  # 使用时间戳作为ID
            "agent_id": agent_id or self.agent_id,  # Fibre agent ID
            "name": f"Agent Session {self.session_id}",
            "description": f"Agent configuration for session {self.session_id}",
            "system_prefix": system_prefix or "",
            "deep_thinking": deep_thinking if deep_thinking is not None else False,
            "agent_mode": agent_mode,
            "more_suggest": more_suggest,
            "max_loop_count": max_loop_count,
            "llm_config": llm_config,
            "available_tools": available_tools or [],
            "available_skills": available_skills or [],
            "system_context": system_context or {},
            "available_workflows": available_workflows or {},
            "memory_backends": memory_backends or {},
            "exportTime": current_time.strftime('%Y-%m-%d %H:%M:%S'),
            "version": "1.0"
        }
        self.session_memory_manager = create_session_memory_manager(agent_config=self.agent_config)
        logger.debug("SessionContext: 设置agent配置信息完成")

    def set_status(self, status: SessionStatus, cascade: bool = True) -> None:
        raise RuntimeError(f"SessionContext: set_status 已废弃，请通过 Session 操作，session_id={self.session_id}")

    def request_interrupt(self, reason: str = "用户请求中断", cascade: bool = True) -> None:
        raise RuntimeError(f"SessionContext: request_interrupt 已废弃，请通过 Session 操作，session_id={self.session_id}")

    def should_interrupt(self) -> bool:
        raise RuntimeError(f"SessionContext: should_interrupt 已废弃，请通过 Session 操作，session_id={self.session_id}")

    def add_child_session(self, child_session_id: str) -> None:
        raise RuntimeError(f"SessionContext: add_child_session 已废弃，请通过 Session 操作，session_id={self.session_id}")

    def remove_child_session(self, child_session_id: str) -> None:
        raise RuntimeError(f"SessionContext: remove_child_session 已废弃，请通过 Session 操作，session_id={self.session_id}")

    def set_parent_session(self, parent_session_id: str) -> None:
        """设置父会话ID

        Args:
            parent_session_id: 父会话ID
        """
        self.parent_session_id = parent_session_id
        logger.debug(f"SessionContext: Set parent session {parent_session_id} for session {self.session_id}")

    def match_language(self, response_language: str) -> str:
        """根据 response_language 匹配语言"""
        _LANGUAGE_ALIAS_MAP = {
            'zh': ['zh', 'zh-CN'],
            'en': ['en', 'en-US'],
            'pt': ['pt', 'pt-BR'],
        }
        for canonical_lang, aliases in _LANGUAGE_ALIAS_MAP.items():
            for alias in aliases:
                if alias in response_language:
                    return canonical_lang
        return 'en'

    def get_language(self) -> str:
        """获取当前会话的语言设置

        根据system_context中的response_language判断语言类型
        如果包含'zh'或'中文'则返回'zh'，否则返回'en'

        Returns:
            str: 'zh'、'en' 或 'pt'
        """
        response_language = self.system_context.get('response_language')
        return self.match_language(str(response_language or 'en'))

    def _normalize_external_paths(self, external_paths: Any) -> List[str]:
        if external_paths is None:
            return []
        if isinstance(external_paths, str):
            return [external_paths]
        if isinstance(external_paths, list):
            return [str(p) for p in external_paths if p is not None]
        return []

    def _refresh_file_permission(self):
        private_workspace = self.system_context.get('private_workspace') or self.sandbox_agent_workspace
        permission_paths = [private_workspace]
        if self.external_paths and isinstance(self.external_paths, list):
            permission_paths.extend([str(p) for p in self.external_paths])
        paths_str = ", ".join(permission_paths)
        workspace = self.sandbox_agent_workspace
        self.system_context['file_permission'] = f"only allow read and write files in: {paths_str} (Note: {workspace} is your private sandbox), and use absolute path"

    # 注意：自动记忆提取功能已迁移到sagents层面
    # 现在由sagents直接调用MemoryExtractionAgent来处理记忆提取和更新

    def add_and_update_system_context(self, new_system_context: Dict[str, Any]):
        """添加并更新系统上下文"""
        if new_system_context:
            external_paths_value = None
            has_external_paths = False
            if "external_paths" in new_system_context:
                has_external_paths = True
                external_paths_value = new_system_context.get("external_paths")
            self.system_context.update(new_system_context)
            if has_external_paths:
                normalized_external_paths = self._normalize_external_paths(external_paths_value)
                previous_external_paths = list(self.external_paths or [])
                self.external_paths = normalized_external_paths
                self.system_context['external_paths'] = normalized_external_paths
                # 更新沙箱的 allowed_paths
                if self.sandbox:
                    # 使用新的接口方法
                    if previous_external_paths:
                        self.sandbox.remove_allowed_paths(previous_external_paths)
                    self.sandbox.add_allowed_paths(normalized_external_paths)
                self._refresh_file_permission()

    def add_llm_request(self, request: Dict[str, Any], response: Optional[Dict[str, Any]]):
        """添加LLM请求并异步保存到文件。

        若处于 ``start_request`` / ``end_request`` 之间，会同时把本次 LLM 调用
        的 usage / 时延累加到 ``self._current_request``，最终在 ``end_request``
        时序列化到 ``<session_workspace>/tokens_usage/<request_id>.json``。
        """
        logger.debug(f"SessionContext: Adding LLM request to session {self.session_id}, step: {request.get('step_name')}")

        llm_request = {
            "request": request,
            "response": response,
            "timestamp": time.time(),
        }
        self.llm_requests_logs.append(llm_request)
        logger.debug(f"SessionContext: Current llm_requests_logs count for session {self.session_id}: {len(self.llm_requests_logs)}")

        try:
            self._accumulate_request_usage(request, response)
        except Exception as exc:
            logger.warning(f"SessionContext: 累加 per-request usage 失败: {exc}")

        # 异步保存日志，不阻塞主流程
        asyncio.create_task(self._async_save_llm_request(llm_request))

    def start_request(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        """开启一次"用户请求"窗口；返回 request_id。

        线程安全：同一 session 不允许嵌套 request；如已有未关闭的 request
        会先把它结掉（status=interrupted）再开启新的。
        """
        with self._request_lock:
            if self._current_request is not None:
                logger.warning(
                    f"SessionContext: start_request 检测到上一个 request 未结束，自动收尾"
                    f" prev_id={self._current_request.get('request_id')}"
                )
                try:
                    self._finalize_current_request("interrupted")
                except Exception:
                    self._current_request = None

            request_id = "req_" + uuid.uuid4().hex[:12]
            now = time.time()
            self._current_request = {
                "request_id": request_id,
                "session_id": self.session_id,
                "started_at": now,
                "ended_at": None,
                "status": "running",
                "agent_mode": (metadata or {}).get("agent_mode"),
                "model": (metadata or {}).get("model"),
                "metadata": metadata or {},
                "total_usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cached_tokens": 0,
                    "reasoning_tokens": 0,
                },
                "per_call": [],
            }
            return request_id

    def end_request(self, status: str = "completed") -> Optional[str]:
        """结束当前 request 窗口，把累加器序列化到 tokens_usage 目录。

        Returns:
            落盘文件路径；若没有活跃 request 则返回 None。
        """
        with self._request_lock:
            return self._finalize_current_request(status)

    def _finalize_current_request(self, status: str) -> Optional[str]:
        cur = self._current_request
        if cur is None:
            return None
        self._current_request = None
        cur["ended_at"] = time.time()
        cur["duration_sec"] = max(0.0, cur["ended_at"] - cur["started_at"])
        cur["status"] = status
        try:
            target_dir = os.path.join(self.session_workspace, "tokens_usage")
            os.makedirs(target_dir, exist_ok=True)
            file_path = os.path.join(target_dir, f"{cur['request_id']}.json")
            payload = make_serializable(cur)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            logger.info(
                f"SessionContext: tokens_usage saved request_id={cur['request_id']} "
                f"calls={len(cur['per_call'])} total_tokens={cur['total_usage'].get('total_tokens')}"
            )
            return file_path
        except Exception as exc:
            logger.error(f"SessionContext: 落盘 tokens_usage 失败: {exc}")
            return None

    def _accumulate_request_usage(
        self,
        request: Dict[str, Any],
        response: Optional[Dict[str, Any]],
    ) -> None:
        cur = self._current_request
        if cur is None:
            return
        response_dict = make_serializable(response) if response is not None else None
        usage = (response_dict or {}).get("usage") if isinstance(response_dict, dict) else None

        # 提取 cached / reasoning 等子项，便于汇总
        cached_tokens = 0
        reasoning_tokens = 0
        if isinstance(usage, dict):
            prompt_details = usage.get("prompt_tokens_details") or {}
            if isinstance(prompt_details, dict):
                v = prompt_details.get("cached_tokens")
                if isinstance(v, (int, float)):
                    cached_tokens = int(v)
            completion_details = usage.get("completion_tokens_details") or {}
            if isinstance(completion_details, dict):
                v = completion_details.get("reasoning_tokens")
                if isinstance(v, (int, float)):
                    reasoning_tokens = int(v)

        # model 优先级：request["model"] > request["model_config"]["model"] > response.model
        mc = request.get("model_config") if isinstance(request.get("model_config"), dict) else None
        resolved_model = (
            request.get("model")
            or (mc.get("model") if mc else None)
            or (response_dict.get("model") if isinstance(response_dict, dict) else None)
        )
        call_entry = {
            "index": len(cur["per_call"]),
            "step_name": request.get("step_name"),
            "model": resolved_model,
            "started_at": request.get("started_at"),
            "first_token_time": request.get("first_token_time"),
            "ttfb_sec": request.get("ttfb_sec"),
            "duration_sec": request.get("duration_sec"),
            "usage": usage,
            "cached_tokens": cached_tokens,
            "reasoning_tokens": reasoning_tokens,
        }
        cur["per_call"].append(call_entry)

        # 累加 total_usage
        total = cur["total_usage"]
        if isinstance(usage, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                v = usage.get(key)
                if isinstance(v, (int, float)):
                    total[key] = total.get(key, 0) + int(v)
        total["cached_tokens"] = total.get("cached_tokens", 0) + cached_tokens
        total["reasoning_tokens"] = total.get("reasoning_tokens", 0) + reasoning_tokens

        # 同步给前端方便对账：取首个 model 作为 request 的代表 model
        if not cur.get("model") and call_entry.get("model"):
            cur["model"] = call_entry["model"]

    async def _async_save_llm_request(self, llm_request: Dict[str, Any]):
        """异步保存单个LLM请求到文件"""
        try:
            file_path = await asyncio.to_thread(self._save_llm_request_sync, llm_request)

            logger.debug(f"SessionContext: Async saved LLM request to {file_path}")
        except Exception as e:
            logger.error(f"SessionContext: Failed to async save LLM request: {e}")

    def get_tokens_usage_info(self):
        """获取tokens使用信息

        - per_step_info 每条带 ``model`` 字段（来自 request.model > request.model_config.model > response.model）
        - total_info 末尾追加 ``model``（首个非空 model）和 ``models``（去重保序的 model 列表）
        - 没有任何 LLM 调用时也返回稳定结构（``total_info``/``per_step_info``/``models`` 都存在）
        """
        tokens_info = {"total_info": {}, "per_step_info": []}
        models_seen: List[str] = []

        def _resolve_model(req: Dict[str, Any], resp_dict: Optional[Dict[str, Any]]) -> Optional[str]:
            req = req or {}
            mc = req.get("model_config") if isinstance(req.get("model_config"), dict) else None
            return (
                req.get("model")
                or (mc.get("model") if mc else None)
                or ((resp_dict or {}).get("model") if isinstance(resp_dict, dict) else None)
            )

        for i, llm_request in enumerate(self.llm_requests_logs):
            raw_response = llm_request['response']
            if raw_response and hasattr(raw_response, 'usage'):
                logger.debug(f"get_tokens_usage_info: raw_response.usage={raw_response.usage}")

            response_dict = make_serializable(raw_response)
            if not isinstance(response_dict, dict):
                continue

            request_dict = llm_request.get("request") or {}
            step_model = _resolve_model(request_dict, response_dict)
            if step_model and step_model not in models_seen:
                models_seen.append(step_model)

            if 'usage' in response_dict and response_dict['usage']:
                usage = response_dict['usage']
                step_info = {
                    "step_name": request_dict.get("step_name", "unknown"),
                    "model": step_model,
                    "usage": usage,
                }
                tokens_info["per_step_info"].append(step_info)

                # 处理基本 token 字段
                for key, value in usage.items():
                    if isinstance(value, (int, float)):
                        if key not in tokens_info["total_info"]:
                            tokens_info["total_info"][key] = 0
                        tokens_info["total_info"][key] += value

                # 处理 prompt_tokens_details 中的 cached_tokens
                prompt_details = usage.get('prompt_tokens_details')
                if prompt_details and isinstance(prompt_details, dict):
                    cached_tokens = prompt_details.get('cached_tokens')
                    if isinstance(cached_tokens, (int, float)):
                        if 'cached_tokens' not in tokens_info["total_info"]:
                            tokens_info["total_info"]['cached_tokens'] = 0
                        tokens_info["total_info"]['cached_tokens'] += cached_tokens

                    audio_tokens = prompt_details.get('audio_tokens')
                    if isinstance(audio_tokens, (int, float)):
                        if 'prompt_audio_tokens' not in tokens_info["total_info"]:
                            tokens_info["total_info"]['prompt_audio_tokens'] = 0
                        tokens_info["total_info"]['prompt_audio_tokens'] += audio_tokens

                # 处理 completion_tokens_details
                completion_details = usage.get('completion_tokens_details')
                if completion_details and isinstance(completion_details, dict):
                    reasoning_tokens = completion_details.get('reasoning_tokens')
                    if isinstance(reasoning_tokens, (int, float)):
                        if 'reasoning_tokens' not in tokens_info["total_info"]:
                            tokens_info["total_info"]['reasoning_tokens'] = 0
                        tokens_info["total_info"]['reasoning_tokens'] += reasoning_tokens

                    audio_tokens = completion_details.get('audio_tokens')
                    if isinstance(audio_tokens, (int, float)):
                        if 'completion_audio_tokens' not in tokens_info["total_info"]:
                            tokens_info["total_info"]['completion_audio_tokens'] = 0
                        tokens_info["total_info"]['completion_audio_tokens'] += audio_tokens
            else:
                # 流式响应可能没有 usage 字段，记录提示
                logger.info(f"get_tokens_usage_info: no usage in response_dict, keys={response_dict.keys()}")
                step_info = {
                    "step_name": request_dict.get("step_name", "unknown"),
                    "model": step_model,
                    "usage": None,
                    "note": "Stream response does not include token usage"
                }
                tokens_info["per_step_info"].append(step_info)

        # 在 total_info 中追加 model 信息，方便前端/统计直接使用
        tokens_info["models"] = models_seen
        if models_seen:
            tokens_info["total_info"]["model"] = models_seen[0]
            tokens_info["total_info"]["models"] = models_seen
        logger.debug(f"get_tokens_usage_info: final tokens_info={tokens_info}")
        return tokens_info

    def save(
        self,
        session_status: Optional[SessionStatus] = None,
        child_session_ids: Optional[List[str]] = None,
        interrupt_reason: Optional[str] = None,
    ):
        """保存会话上下文（不包含 llm_requests，已在 add 时异步保存）"""
        effective_status = session_status or self._status
        effective_child_session_ids = child_session_ids if child_session_ids is not None else self.child_session_ids
        if interrupt_reason is not None:
            self.audit_status["interrupt_reason"] = interrupt_reason
        # 1. 保存 messages 到 messages.json
        # 始终覆盖，保存完整历史
        try:
            with open(os.path.join(self.session_workspace, "messages.json"), "w", encoding="utf-8") as f:
                serializable_messages = make_serializable(self.message_manager.messages)
                json.dump(serializable_messages, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"SessionContext: Failed to save messages.json: {e}")

        # 3. 保存 session_context.json (仅保存最新状态)
        # 包含 system_context, audit_status, token_usage, 基本元数据
        try:
            context_data = {
                "session_id": self.session_id,
                "user_id": self.user_id,
                "parent_session_id": self.parent_session_id,
                "child_session_ids": effective_child_session_ids,
                "status": effective_status.value if hasattr(effective_status, 'value') else str(effective_status),
                "created_at": self.start_time,
                "updated_at": time.time(),
                "session_root_space": self.session_root_space,
                "session_workspace": self.session_workspace,
                "sandbox_agent_workspace": self.sandbox_agent_workspace,

                # 关键状态
                "system_context": make_serializable(self.system_context),
                "audit_status": make_serializable(self.audit_status),
                "tokens_usage_info": self.get_tokens_usage_info(),

                # Agent 配置
                "agent_config": make_serializable(self.agent_config)
            }
            
            with open(os.path.join(self.session_workspace, "session_context.json"), "w", encoding="utf-8") as f:
                json.dump(context_data, f, ensure_ascii=False, indent=4)
                
        except Exception as e:
            logger.error(f"SessionContext: Failed to save session_context.json: {e}")

        # 基于messages.json 提取里面不同的工具调用的数量统计，并保存到tools_usage.json
        try:
            tools_usage = {}
            for msg in self.message_manager.messages:
                if msg.tool_calls:
                    for tool_call in msg.tool_calls:
                        tool_name = tool_call.get('function', {}).get('name')
                        if tool_name:
                            tools_usage[tool_name] = tools_usage.get(tool_name, 0) + 1
            
            with open(os.path.join(self.session_workspace, "tools_usage.json"), "w", encoding="utf-8") as f:
                json.dump(tools_usage, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"SessionContext: Failed to save tools_usage.json: {e}")

        self.record_timing_event(
            "session_end",
            status=effective_status.value if hasattr(effective_status, "value") else str(effective_status),
        )

    # def _serialize_messages_for_history_memory(self, messages: List[MessageChunk]) -> str:
    #     """序列化消息列表为系统上下文格式的字符串（私有方法）"""
    #     # 获取当前语言设置
    #     language = self.get_language()

    #     # 从PromptManager获取多语言文本
    #     explanation = prompt_manager.get_prompt(
    #         "history_messages_explanation",
    #         agent="SessionContext",
    #         language=language,
    #         default=(
    #             "以下是检索到的相关历史对话上下文，这些消息与当前查询相关，"
    #             "可以帮助你更好地理解对话背景和用户意图。请参考这些历史消息来提供更准确和连贯的回答。\n"
    #             "=== 相关历史对话上下文 ===\n"
    #         )
    #     )

    #     # 获取消息格式模板
    #     message_format_template = prompt_manager.get_prompt(
    #         "history_message_format",
    #         agent="SessionContext",
    #         language=language,
    #         default="[Memory {index}] ({time}): {content}"
    #     )

    #     messages_str_list = []
    #     for idx, msg in enumerate(messages):
    #         content = msg.get_content()
    #         utc_time = datetime.datetime.fromtimestamp(msg.timestamp or time.time(), tz=datetime.timezone.utc)
    #         local_time = utc_time.astimezone()
    #         time_str = local_time.strftime('%Y-%m-%d %H:%M:%S')
    #         messages_str_list.append(message_format_template.format(index=idx + 1, time=time_str, content=content))

    #     messages_content = "\n".join(messages_str_list)
    #     return explanation + messages_content

    # def set_session_history_context(self) -> None:
    #     """准备并设置历史上下文到 system_context

    #     完整流程：计算预算 -> 切分消息 -> 设置索引 -> BM25重排序 -> 序列化 -> 保存到system_context
        
    #     这是 SessionContext 的职责：协调消息检索和上下文保存。
    #     """
    #     t_start = time.time()
    #     # 1. 准备历史上下文
    #     prepare_result = self.message_manager.prepare_history_split(self.agent_config)
    #     t_prepare = time.time()
        
    #     # 2. 检索历史消息
    #     history_messages = self.session_memory_manager.retrieve_history_messages(
    #         messages=prepare_result['split_result']['history_messages'],
    #         query=prepare_result['current_query'],
    #         history_budget=prepare_result['budget_info']['history_budget']
    #     )
    #     t_retrieve = time.time()

    #     if len(history_messages) > 0:
    #         # 4. 序列化为字符串并插入到system_context
    #         history_messages_str = self._serialize_messages_for_history_memory(history_messages)
    #         self.system_context['history_messages'] = history_messages_str

    #     logger.info(
    #         f"SessionContext: 历史上下文准备完成 - "
    #         f"检索历史消息{len(history_messages)}条消息到system_context, "
    #         f"总耗时: {time.time() - t_start:.3f}s (准备: {t_prepare - t_start:.3f}s, 检索: {t_retrieve - t_prepare:.3f}s)"
    #     )

def get_session_run_lock(session_id: str) -> UnifiedLock:
    return lock_manager.get_lock(session_id)


def delete_session_run_lock(session_id: str):
    lock_manager.delete_lock_ref(session_id)
