# 负责管理会话的上下文，以及过程中产生的日志以及状态记录。
from math import log
import time
import threading
from typing import Dict, Any, Optional, List, Union
from enum import Enum
from concurrent.futures import ThreadPoolExecutor

from sagents.context.messages.message import MessageChunk
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_memory.session_memory_manager import SessionMemoryManager
from sagents.skill import SkillProxy, SkillManager
from sagents.utils.prompt_manager import prompt_manager
from sagents.context.workflows import WorkflowManager
from sagents.context.user_memory.manager import UserMemoryManager

from sagents.utils.logger import logger
from sagents.utils.lock_manager import lock_manager, UnifiedLock
from sagents.utils.serialization import make_serializable
import json
import os
import re
import datetime
import pytz
from sagents.utils.sandbox.sandbox import Sandbox

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
        session_root_space: str,
        agent_workspace: Optional[str] = None,
        context_budget_config: Optional[Dict[str, Any]] = None,
        system_context: Optional[Dict[str, Any]] = None,
        user_memory_manager: Optional[Any] = None,
        tool_manager: Optional[Any] = None,
        skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
        parent_session_id: Optional[str] = None,
    ):
        # 基础身份与外部依赖
        self.session_id = session_id
        self.user_id = user_id
        self.system_context: Dict[str, Any] = system_context or {}
        self.session_root_space = session_root_space
        self.agent_workspace = agent_workspace
        self.user_memory_manager = user_memory_manager
        self.tool_manager = tool_manager
        self.skill_manager = skill_manager
        self.parent_session_id = parent_session_id
        self._init_runtime_state(context_budget_config=context_budget_config)
        self.init_more(session_root_space, agent_workspace)

    def _init_runtime_state(self, context_budget_config: Optional[Dict[str, Any]] = None):
        # 运行期状态容器（与 I/O、会话生命周期绑定）
        self.llm_requests_logs: List[Dict[str, Any]] = []
        self.thread_id = threading.get_ident()
        self.start_time = time.time()
        self.end_time = None
        self.status = SessionStatus.IDLE
        self.message_manager = MessageManager(context_budget_config=context_budget_config)
        self.workflow_manager = WorkflowManager()
        self.audit_status: Dict[str, Any] = {}
        self.session_memory_manager = SessionMemoryManager()
        self.agent_config: Dict[str, Any] = {}
        self.custom_sub_agents: List[Dict[str, Any]] = []
        self.orchestrator: Optional[Any] = None
        self.child_session_ids: List[str] = []

    def init_more(self, session_root_space: str, agent_workspace: Optional[str] = None):
        use_sandbox = os.environ.get("SAGE_USE_SANDBOX", "true").lower() == "true"
        logger.info(f"SessionContext: use_sandbox: {use_sandbox}")
        
        # 解析工作空间路径，确保 session_root_space 存在，并设置 self.agent_workspace
        self._resolve_workspace_paths(session_root_space, agent_workspace)
        
        # 准备工作区引导文件，主要是 USER.md, SOUL.md, IDENTITY.md, MEMORY.md
        self._prepare_workspace_bootstrap_files()
        
        # 初始化外部路径和上下文
        self._init_external_paths_and_context()
        
        # 初始化沙箱和文件系统
        self._init_sandbox_and_file_system(use_sandbox=use_sandbox)
        
        # 注册并准备技能
        self._register_and_prepare_skills()

        # 最终化系统上下文
        self._finalize_system_context()

        # 加载已持久化的消息
        self._load_persisted_messages()
        
        # 清理过期的待办任务
        self._cleanup_expired_todo_tasks()

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
            self.message_manager.add_messages(valid_messages)

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

    def _resolve_workspace_paths(self, session_root_space: str, agent_workspace: Optional[str]) -> str:
        """
        解析会话空间与智能体工作空间路径。
        
        Args:
            session_root_space: 会话根空间路径
            agent_workspace: 智能体工作空间路径
            
        Returns:
            解析后的智能体工作空间路径
            
        Raises:
            ValueError: 如果未提供有效工作空间路径
        """
        if not session_root_space or not os.path.exists(session_root_space):
            raise ValueError(f"SessionContext 初始化需要传入有效的 session_root_space: {session_root_space}")
            
        self.session_root_space = os.path.abspath(session_root_space)
        
        # 确定 session_workspace
        # 如果存在 parent_session_id，尝试在父会话目录下创建 sub_sessions
        # 我们假设 session_root_space 是根目录，也可能是父目录
        
        parent_session_id = self.parent_session_id or self.system_context.get("parent_session_id")
        
        # 1. 如果有父会话ID，尝试构建嵌套结构: {session_root_space}/{parent_session_id}/sub_sessions/{session_id}
        # 假设 session_root_space 始终是根目录 (例如 ./sage_sessions)
        
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
        
        if agent_workspace is None or str(agent_workspace).strip() == "":
            raise ValueError("SessionContext 初始化需要传入 agent_workspace")
            
        self.agent_workspace = os.path.abspath(str(agent_workspace))
        os.makedirs(self.agent_workspace, exist_ok=True)
        
        logger.info(f"SessionContext: agent_workspace (host): {self.agent_workspace}")
        return self.agent_workspace

    def _prepare_workspace_bootstrap_files(self):
        use_claw_mode = os.environ.get("SAGE_USE_CLAW_MODE", "true").lower() == "true"
        logger.info(f"SessionContext: use_claw_mode: {use_claw_mode}")
        if use_claw_mode:
            agent_md_path = os.path.join(self.agent_workspace, "AGENT.md")
            if not os.path.exists(agent_md_path):
                self._submit_default_md_file(agent_md_path, "default_agent_md", "AGENT.md")
                
            user_md_path = os.path.join(self.agent_workspace, "USER.md")
            if not os.path.exists(user_md_path):
                self._submit_default_md_file(user_md_path, "default_user_md", "USER.md")

            soul_md_path = os.path.join(self.agent_workspace, "SOUL.md")
            if not os.path.exists(soul_md_path):
                self._submit_default_md_file(soul_md_path, "default_soul_md", "SOUL.md")

            identity_md_path = os.path.join(self.agent_workspace, "IDENTITY.md")
            if not os.path.exists(identity_md_path):
                self._submit_default_md_file(identity_md_path, "default_identity_md", "IDENTITY.md")
            memory_md_path = os.path.join(self.agent_workspace, "MEMORY.md")
            if not os.path.exists(memory_md_path):
                self._submit_default_md_file(memory_md_path, "default_memory_md", "MEMORY.md")

            memory_folder_path = os.path.join(self.agent_workspace, "memory")
            os.makedirs(memory_folder_path, exist_ok=True)

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
        current_time_str = datetime.datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%dT%H:%M:%S%z %A')
        if self.system_context.get('current_time') is None:
            self.system_context['current_time'] = current_time_str

    def _init_sandbox_and_file_system(self, use_sandbox: bool):
        """
        初始化沙箱环境和文件系统
        
        Args:
            use_sandbox: 是否启用沙箱模式
        """
        if use_sandbox:
            self.virtual_workspace = "/sage-workspace"
        else:
            self.virtual_workspace = self.agent_workspace
        logger.debug(f"SessionContext: 开始初始化沙箱环境，工作区: {self.virtual_workspace}")
        t0 = time.time()
        self.sandbox = Sandbox(
            host_workspace=self.agent_workspace,
            virtual_workspace=self.virtual_workspace,
            cpu_time_limit=300,
            memory_limit_mb=4096,
            allowed_paths=self.external_paths,
            macos_isolation_mode='subprocess',
            linux_isolation_mode='subprocess'
        )
        logger.debug(f"SessionContext: 沙箱环境初始化完成，耗时: {time.time() - t0:.3f}s")
        # agent_workspace (string) is already set in _resolve_workspace_paths
        self.agent_workspace_sandbox = self.sandbox
        self.file_system = self.sandbox.file_system
        

    def _register_and_prepare_skills(self):
        """
        注册并准备技能，主要是复制技能到会话工作区
        """
        self.session_skill_dir = os.path.join(self.agent_workspace, "skills")
        os.makedirs(self.session_skill_dir, exist_ok=True)
        logger.debug(f"SessionContext: 会话技能目录: {self.session_skill_dir}")

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
            # 创建会话本地技能管理器
            session_local_manager = SkillManager(
                skill_dirs=[self.session_skill_dir],
                isolated=True,
                include_global_skills=False
            )
            # 合并会话本地技能管理器和全局技能管理器，本地技能优先
            self.skill_manager = SkillProxy(skill_managers=[session_local_manager, self.skill_manager])
            logger.debug(f"SessionContext: 当前可用的技能: {list(self.skill_manager.skills.keys())}, 准备复制技能到工作区: {self.agent_workspace}")
            t1 = time.time()
            try:
                self.skill_manager.prepare_skills_in_workspace(self.agent_workspace)
                logger.debug(f"SessionContext: 技能复制完成，耗时: {time.time() - t1:.3f}s，平均每个技能耗时: {(time.time() - t1) / len(self.skill_manager.skills):.3f}s")
            except Exception as e:
                logger.error(f"SessionContext: 技能复制失败: {e}", exc_info=True)
        else:
            logger.warning("SessionContext: SkillManager 未初始化，跳过技能复制")

    def _finalize_system_context(self):
        """
        最终化系统上下文，设置私有工作区、用户ID和会话ID
        """
        # 设置私有工作区
        self.system_context['private_workspace'] = self.virtual_workspace
        # 设置用户ID
        if self.user_id:
            self.system_context['user_id'] = self.user_id
        # 设置会话ID
        self.system_context['session_id'] = self.session_id
        # 设置文件权限路径  
        permission_paths = [self.system_context['private_workspace']]
        logger.debug(f"self.external_paths: {self.external_paths}")
        if self.external_paths and isinstance(self.external_paths, list):
            permission_paths.extend([str(p) for p in self.external_paths])
        paths_str = ", ".join(permission_paths)
        sandbox_root = self.virtual_workspace
        common_dirs = ["data", "outputs", "temp", "logs"]
        for d in common_dirs:
            dir_path = os.path.join(sandbox_root, d)
            self.sandbox.file_system.ensure_directory(dir_path)
        self.system_context['file_permission'] = (
            f"only allow read and write files in: {paths_str} (Note: {self.virtual_workspace} is your private sandbox). "
            f"Please save files in the pre-created folders: {', '.join(common_dirs)} and use absolute paths; avoid creating extra directories in the root."
        )
        # 设置响应语言
        self.system_context['response_language'] = self.system_context.get('response_language', "zh-CN(简体中文)")

    def _load_persisted_messages(self):
        """
        加载持久化的消息历史
        """
        # 1. 尝试加载 messages.json
        try:
            messages_path = os.path.join(self.session_workspace, "messages.json")
            if os.path.exists(messages_path):
                with open(messages_path, "r") as f:
                    messages_data = json.load(f)
                    if isinstance(messages_data, list):
                        self.message_manager.messages = [MessageChunk.from_dict(msg) for msg in messages_data]
                        logger.info(f"SessionContext: Loaded {len(self.message_manager.messages)} messages from messages.json")
                        return
        except Exception as e:
            logger.warning(f"SessionContext: Failed to load messages.json: {e}")

        # 2. 如果 messages.json 不存在或加载失败，尝试从 session_context.json 中加载状态 (虽然目前 session_context.json 不存 messages)
        # 但如果有必要，可以在这里扩展
        
        # 3. 兼容性逻辑：尝试从旧的 session_status_*.json 加载 (仅作为最后手段)
        # 但我们已经被指示清理旧逻辑。如果必须彻底删除，这里就不应该有。
        # 鉴于我们要确保"不会再加载已经删除的文件"，如果那些文件已经被我们停止生成，但磁盘上可能还有旧的
        # 为了兼容旧会话，可以保留读取逻辑，但不要写入。
        # 如果是全新的会话系统，应该可以移除。
        # 用户指令："确保不会再加载已经删除的文件" -> 可能是指不要尝试加载那些我们不再生成的文件类型
        # 所以这里只加载 messages.json 是对的。
        
        pass

    def _cleanup_expired_todo_tasks(self):
        try:
            from sagents.tool.impl.todo_tool import ToDoTool
            ToDoTool().clean_old_tasks(session_id=self.session_id, session_context=self, time_threshold=1800)
        except Exception as e:
            logger.warning(f"SessionContext: 清理过期任务失败: {e}")


    async def load_recent_skill_to_context(self):
        """
        检测历史消息，是否有使用 load_skill skill，或者用户消息中包含 <skill>name</skill>。
        如果有，取最后一次出现的（优先级最高），加载到context 中。
        """
        if not self.skill_manager:
            return

        found_skill_name = None
        found_arguments = None
        
        # 倒序遍历消息
        for msg in reversed(self.message_manager.messages):
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
                
                # Check for <skill>...</skill>
                matches = re.findall(r"<skill>(.*?)</skill>", content_str, re.DOTALL)
                if matches:
                    # Use the last match in the message content
                    found_skill_name = matches[-1].strip()
                    found_arguments = {"skill_name": found_skill_name}
                    logger.info(f"SessionContext: Found skill tag in user message: {found_skill_name}")
                    break

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
                             found_skill_name = arguments.get('skill_name')
                             found_arguments = arguments
                             logger.info(f"SessionContext: Found recent skill tool call: {found_skill_name}")
                             break
            
            if found_skill_name:
                break
        
        if found_skill_name:
            try:
                logger.info(f"SessionContext: Reloading skill '{found_skill_name}' via ToolManager...")
                await self.tool_manager.run_tool_async(
                    tool_name='load_skill',
                    session_context=self,
                    session_id=self.session_id,
                    **found_arguments
                )
            except Exception as e:
                logger.error(f"SessionContext: Failed to load recent skill to context: {e}")

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


    async def init_user_memory_context(self):
        """初始化用户记忆
        """
        # 使用已注入的UserMemoryManager
        if self.user_memory_manager:
            try:
                # 检查是否可用
                if not self.user_memory_manager.is_enabled():
                    logger.warning(f"SessionContext: UserMemoryManager不可用，用户ID: {self.user_id}")
                else:
                    if self.user_id is None:
                        logger.warning("SessionContext: 用户ID为空，无法初始化用户记忆")
                        return
                    logger.debug(f"SessionContext: UserMemoryManager已启用，用户ID: {self.user_id}")
                    # user_memory_manager 初始化成功，需要在system context添加对于 记忆使用的说明和要求
                    self.system_context['user_memory_usage_description'] = self.user_memory_manager.get_user_memory_usage_description()
                    # 自动查询系统级记忆并注入到system_context
                    await self._load_system_memories()

            except Exception as e:
                logger.error(f"SessionContext: 初始化UserMemoryManager失败: {e}")
                # self.user_memory_manager = None # 不要置空全局实例

    def set_agent_config(self, model: Optional[str] = None, model_config: Optional[dict] = None, system_prefix: Optional[str] = None,
                         available_tools: Optional[list] = None, available_skills: Optional[list] = None, system_context: Optional[dict] = None,
                         available_workflows: Optional[dict] = None, deep_thinking: Optional[bool] = None,
                         agent_mode: Optional[str] = None, more_suggest: bool = False,
                         max_loop_count: int = 10, agent_id: Optional[str] = None):
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
        """
        # 生成与preset_running_agent_config.json格式一致的配置
        current_time = datetime.datetime.now(pytz.timezone('Asia/Shanghai'))

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
            "agent_id": agent_id,  # Fibre agent ID
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
            "exportTime": current_time.isoformat(),
            "version": "1.0"
        }
        logger.debug("SessionContext: 设置agent配置信息完成")

    def set_status(self, status: SessionStatus, cascade: bool = True) -> None:
        """设置会话状态，支持级联传播到子会话

        Args:
            status: 新的会话状态
            cascade: 是否级联传播到子会话，默认为 True
        """
        old_status = self.status
        self.status = status
        logger.info(f"SessionContext: Session {self.session_id} status changed from {old_status.value} to {status.value}")

        # 级联传播到子会话（当状态为 INTERRUPTED 或 ERROR 时）
        if cascade and status in [SessionStatus.INTERRUPTED, SessionStatus.ERROR]:
            if self.child_session_ids:
                logger.info(f"SessionContext: Cascading status {status.value} to {len(self.child_session_ids)} child sessions: {self.child_session_ids}")
                for child_session_id in self.child_session_ids:
                    try:
                        # 从 _active_sessions 获取子会话上下文
                        from sagents.session_runtime import get_global_session_manager
                        session_manager = get_global_session_manager()
                        child_session = session_manager.get(child_session_id)
                        if child_session:
                            child_context = child_session.session_context
                        if child_context:
                            child_context.set_status(status, cascade=False)  # 子会话不再级联，避免循环
                            logger.info(f"SessionContext: Set child session {child_session_id} status to {status.value}")
                        else:
                            logger.warning(f"SessionContext: Child session {child_session_id} not found in _active_sessions, cannot cascade status")
                    except Exception as e:
                        logger.error(f"SessionContext: Failed to cascade status to child session {child_session_id}: {e}")
            else:
                logger.info(f"SessionContext: No child sessions to cascade status {status.value}")

    def add_child_session(self, child_session_id: str) -> None:
        """添加子会话ID

        Args:
            child_session_id: 子会话ID
        """
        if child_session_id not in self.child_session_ids:
            self.child_session_ids.append(child_session_id)
            logger.debug(f"SessionContext: Added child session {child_session_id} to session {self.session_id}")

    def remove_child_session(self, child_session_id: str) -> None:
        """移除子会话ID

        Args:
            child_session_id: 子会话ID
        """
        if child_session_id in self.child_session_ids:
            self.child_session_ids.remove(child_session_id)
            logger.debug(f"SessionContext: Removed child session {child_session_id} from session {self.session_id}")

    def set_parent_session(self, parent_session_id: str) -> None:
        """设置父会话ID

        Args:
            parent_session_id: 父会话ID
        """
        self.parent_session_id = parent_session_id
        logger.debug(f"SessionContext: Set parent session {parent_session_id} for session {self.session_id}")

    async def _load_system_memories(self):
        """加载系统级记忆并注入到system_context

        Args:
            tool_manager: 工具管理器实例
        """
        if not self.user_id or not self.user_memory_manager:
            return

        try:
            # 通过UserMemoryManager获取系统级记忆
            system_memories = await self.user_memory_manager.get_system_memories(
                user_id=self.user_id,
                session_id=self.session_id,
                tool_manager=self.tool_manager
            )

            if system_memories:
                # 格式化记忆内容并注入到system_context
                formatted_context = self.user_memory_manager.format_system_memories_for_context(system_memories)

                if formatted_context:
                    self.system_context['用户长期记忆'] = formatted_context
                    logger.debug(f"成功注入 {len(system_memories)} 种类型的系统级记忆到system_context")
            else:
                logger.debug("未找到系统级记忆，跳过注入")

        except Exception as e:
            logger.error(f"加载系统级记忆失败: {e}")

    async def refresh_system_memories(self):
        """刷新系统级记忆"""
        if self.user_memory_manager:
            await self._load_system_memories()
            logger.info("系统级记忆已刷新")

    async def get_system_memories_summary(self) -> str:
        """获取系统级记忆摘要

        Returns:
            系统级记忆的摘要字符串
        """
        if not self.user_memory_manager or not self.user_id:
            return ""

        try:
            return await self.user_memory_manager.get_system_memories_summary(
                user_id=self.user_id,
                session_id=self.session_id,
                tool_manager=self.tool_manager
            )
        except Exception as e:
            logger.error(f"获取系统级记忆摘要失败: {e}")
            return ""

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
        return 'zh'

    def get_language(self) -> str:
        """获取当前会话的语言设置

        根据system_context中的response_language判断语言类型
        如果包含'zh'或'中文'则返回'zh'，否则返回'en'

        Returns:
            str: 'zh' 或 'en'
        """
        response_language = self.system_context.get('response_language')
        # return 'zh' if 'zh' in response_language or '中文' in response_language else 'en'
        return self.match_language(str(response_language or 'zh'))

    def _normalize_external_paths(self, external_paths: Any) -> List[str]:
        if external_paths is None:
            return []
        if isinstance(external_paths, str):
            return [external_paths]
        if isinstance(external_paths, list):
            return [str(p) for p in external_paths if p is not None]
        return []

    def _refresh_file_permission(self):
        private_workspace = self.system_context.get('private_workspace') or getattr(self, 'virtual_workspace', '/workspace')
        permission_paths = [private_workspace]
        if self.external_paths and isinstance(self.external_paths, list):
            permission_paths.extend([str(p) for p in self.external_paths])
        paths_str = ", ".join(permission_paths)
        virtual_workspace = getattr(self, 'virtual_workspace', '/workspace')
        self.system_context['file_permission'] = f"only allow read and write files in: {paths_str} (Note: {virtual_workspace} is your private sandbox), and use absolute path"

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
            elif "可以访问的其他路径文件夹" in new_system_context:
                has_external_paths = True
                external_paths_value = new_system_context.get("可以访问的其他路径文件夹")
            self.system_context.update(new_system_context)
            if has_external_paths:
                normalized_external_paths = self._normalize_external_paths(external_paths_value)
                previous_external_paths = list(self.external_paths or [])
                self.external_paths = normalized_external_paths
                self.system_context['external_paths'] = normalized_external_paths
                if "可以访问的其他路径文件夹" in self.system_context:
                    self.system_context.pop("可以访问的其他路径文件夹", None)
                if self.sandbox and hasattr(self.sandbox, 'limits'):
                    allowed_paths = list(self.sandbox.limits.get('allowed_paths', []))
                    if previous_external_paths:
                        allowed_paths = [p for p in allowed_paths if p not in previous_external_paths]
                    for path in normalized_external_paths:
                        if path not in allowed_paths:
                            allowed_paths.append(path)
                    self.sandbox.limits['allowed_paths'] = allowed_paths
                self._refresh_file_permission()

    def add_llm_request(self, request: Dict[str, Any], response: Optional[Dict[str, Any]]):
        """添加LLM请求"""
        logger.debug(f"SessionContext: Adding LLM request to session {self.session_id}, step: {request.get('step_name')}")
        self.llm_requests_logs.append({
            "request": request,
            "response": response,
            "timestamp": time.time(),
        })
        logger.debug(f"SessionContext: Current llm_requests_logs count for session {self.session_id}: {len(self.llm_requests_logs)}")

    def get_tokens_usage_info(self):
        """获取tokens使用信息"""
        tokens_info = {"total_info": {}, "per_step_info": []}
        for llm_request in self.llm_requests_logs:
            raw_response = llm_request['response']
            logger.info(f"get_tokens_usage_info: raw_response type={type(raw_response)}, has usage={hasattr(raw_response, 'usage') if raw_response else False}")
            if raw_response and hasattr(raw_response, 'usage'):
                logger.info(f"get_tokens_usage_info: raw_response.usage={raw_response.usage}")
            
            response_dict = make_serializable(raw_response)
            logger.info(f"get_tokens_usage_info: response_dict type={type(response_dict)}, keys={response_dict.keys() if isinstance(response_dict, dict) else 'N/A'}")
            if not isinstance(response_dict, dict):
                continue
            if 'usage' in response_dict and response_dict['usage']:
                logger.info(f"get_tokens_usage_info: usage={response_dict['usage']}")
                step_info = {
                    "step_name": (llm_request.get("request") or {}).get("step_name", "unknown"),
                    "usage": response_dict.get("usage"),
                }
                tokens_info["per_step_info"].append(step_info)
                for key, value in response_dict['usage'].items():
                    if isinstance(value, int) or isinstance(value, float):
                        if key not in tokens_info["total_info"]:
                            tokens_info["total_info"][key] = 0
                        tokens_info["total_info"][key] += value
            else:
                # 流式响应可能没有 usage 字段，记录提示
                logger.info(f"get_tokens_usage_info: no usage in response_dict, keys={response_dict.keys()}")
                step_info = {
                    "step_name": (llm_request.get("request") or {}).get("step_name", "unknown"),
                    "usage": None,
                    "note": "Stream response does not include token usage"
                }
                tokens_info["per_step_info"].append(step_info)
        logger.info(f"get_tokens_usage_info: final tokens_info={tokens_info}")
        return tokens_info

    def save(self):
        """保存会话上下文"""
        # 1. 保存模型请求记录 (llm_requests)
        llm_request_folder = os.path.join(self.session_workspace, "llm_request")
        os.makedirs(llm_request_folder, exist_ok=True)
        # 说明存在，需要看看当前的序号从几开始
        existing_files = os.listdir(llm_request_folder)
        max_index = -1
        for file in existing_files:
            if file.endswith(".json"):
                try:
                    index = int(file.split("_")[0])
                    max_index = max(max_index, index)
                except ValueError:
                    continue
                    
        # 从max_index + 1 开始
        if self.llm_requests_logs:
            logger.debug(f"SessionContext: 保存llm_requests_logs，当前的序号从{max_index + 1}开始")
            logger.debug(f"SessionContext: 需要保存的llm_requests_logs数量: {len(self.llm_requests_logs)}")
            
            for i, llm_request in enumerate(self.llm_requests_logs):
                file_name = f"{max_index + 1 + i}_{llm_request['request'].get('step_name', 'unknown')}_{time.strftime('%Y%m%d%H%M%S', time.localtime(llm_request['timestamp']))}.json"
                file_path = os.path.join(llm_request_folder, file_name)
                # logger.debug(f"SessionContext: Saving LLM request to {file_path}")
                
                try:
                    with open(file_path, "w") as f:
                        # 创建可序列化的副本
                        serializable_request = {
                            "request": make_serializable(llm_request['request']),
                            "response": make_serializable(llm_request['response']),
                            "timestamp": llm_request['timestamp']
                        }
                        json.dump(serializable_request, f, ensure_ascii=False, indent=4)
                except Exception as e:
                    logger.error(f"SessionContext: Failed to write log file {file_path}: {e}")
            
            # 清空已保存的日志，避免重复保存
            self.llm_requests_logs = []

        # 2. 保存 messages 到 messages.json
        # 始终覆盖，保存完整历史
        try:
            with open(os.path.join(self.session_workspace, "messages.json"), "w") as f:
                # 先将messages 转换为可序列化的格式
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
                "child_session_ids": self.child_session_ids,
                "status": self.status.value if hasattr(self.status, 'value') else str(self.status),
                "created_at": self.start_time,
                "updated_at": time.time(),
                "session_root_space": self.session_root_space,
                "session_workspace": self.session_workspace,
                "agent_workspace": self.agent_workspace,
                
                # 关键状态
                "system_context": make_serializable(self.system_context),
                "audit_status": make_serializable(self.audit_status),
                "tokens_usage_info": self.get_tokens_usage_info(),
                
                # Agent 配置
                "agent_config": make_serializable(self.agent_config)
            }
            
            with open(os.path.join(self.session_workspace, "session_context.json"), "w") as f:
                json.dump(context_data, f, ensure_ascii=False, indent=4)
                
        except Exception as e:
            logger.error(f"SessionContext: Failed to save session_context.json: {e}")

        # 移除旧的保存逻辑 (session_status_*.json 和 agent_config.json)

    def _serialize_messages_for_history_memory(self, messages: List[MessageChunk]) -> str:
        """序列化消息列表为系统上下文格式的字符串（私有方法）"""
        # 获取当前语言设置
        language = self.get_language()

        # 从PromptManager获取多语言文本
        explanation = prompt_manager.get_prompt(
            "history_messages_explanation",
            agent="SessionContext",
            language=language,
            default=(
                "以下是检索到的相关历史对话上下文，这些消息与当前查询相关，"
                "可以帮助你更好地理解对话背景和用户意图。请参考这些历史消息来提供更准确和连贯的回答。\n"
                "=== 相关历史对话上下文 ===\n"
            )
        )

        # 获取消息格式模板
        message_format_template = prompt_manager.get_prompt(
            "history_message_format",
            agent="SessionContext",
            language=language,
            default="[Memory {index}] ({time}): {content}"
        )

        messages_str_list = []
        for idx, msg in enumerate(messages):
            content = msg.get_content()
            utc_time = datetime.datetime.fromtimestamp(msg.timestamp or time.time(), tz=datetime.timezone.utc)
            local_time = utc_time.astimezone()
            time_str = local_time.strftime('%Y-%m-%d %H:%M:%S %z')
            messages_str_list.append(message_format_template.format(index=idx + 1, time=time_str, content=content))

        messages_content = "\n".join(messages_str_list)
        return explanation + messages_content

    def set_session_history_context(self) -> None:
        """准备并设置历史上下文到 system_context

        完整流程：计算预算 -> 切分消息 -> 设置索引 -> BM25重排序 -> 序列化 -> 保存到system_context
        
        这是 SessionContext 的职责：协调消息检索和上下文保存。
        """
        t_start = time.time()
        # 1. 准备历史上下文
        prepare_result = self.message_manager.prepare_history_split(self.agent_config)
        t_prepare = time.time()
        
        # 2. 检索历史消息
        history_messages = self.session_memory_manager.retrieve_history_messages(
            messages=prepare_result['split_result']['history_messages'],
            query=prepare_result['current_query'],
            history_budget=prepare_result['budget_info']['history_budget']
        )
        t_retrieve = time.time()

        if len(history_messages) > 0:
            # 4. 序列化为字符串并插入到system_context
            history_messages_str = self._serialize_messages_for_history_memory(history_messages)
            self.system_context['history_messages'] = history_messages_str

        logger.info(
            f"SessionContext: 历史上下文准备完成 - "
            f"检索历史消息{len(history_messages)}条消息到system_context, "
            f"总耗时: {time.time() - t_start:.3f}s (准备: {t_prepare - t_start:.3f}s, 检索: {t_retrieve - t_prepare:.3f}s)"
        )

# def get_sub_session_messages(parent_session_id: str, sub_session_id: str) -> List[MessageChunk]:
#     # 同样使用 SessionManager，但 SessionManager 目前的 get_session_messages 是基于 session_id 查找
#     # 如果 sub_session_id 也是全局唯一的，并且被 scan 到了，可以直接用
#     from sagents.session_runtime import get_global_session_manager
#     manager = get_global_session_manager()
#     return manager.get_session_messages(sub_session_id)


def get_session_run_lock(session_id: str) -> UnifiedLock:
    return lock_manager.get_lock(session_id)


def delete_session_run_lock(session_id: str):
    lock_manager.delete_lock_ref(session_id)
