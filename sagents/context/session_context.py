# 负责管理会话的上下文，以及过程中产生的日志以及状态记录。
import time
import threading
from typing import Dict, Any, Optional, List, Union
from enum import Enum

from sagents.context.messages.message import MessageChunk
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_memory.session_memory_manager import SessionMemoryManager
from sagents.skill import SkillProxy, SkillManager
from sagents.utils.prompt_manager import prompt_manager
from sagents.context.workflows import WorkflowManager
from sagents.context.user_memory.manager import UserMemoryManager

from sagents.utils.logger import logger
from sagents.utils.lock_manager import lock_manager, UnifiedLock
import json
import os
import datetime
import pytz
from sagents.utils.sandbox.sandbox import Sandbox


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
        user_id: Optional[str] = None,
        workspace_root: str = "",
        context_budget_config: Optional[Dict[str, Any]] = None,
        user_memory_manager: Optional[UserMemoryManager] = None,
        tool_manager: Optional[Any] = None,
        skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
    ):
        self.session_id = session_id
        self.user_id = user_id
        self.llm_requests_logs: List[Dict[str, Any]] = []           # 大模型的请求记录
        self.thread_id = threading.get_ident()
        self.start_time = time.time()
        self.end_time = None
        self.status = SessionStatus.IDLE
        self.system_context: Dict[str, Any] = {}       # 当前系统的环境变量
        self.message_manager = MessageManager(context_budget_config=context_budget_config)
        from sagents.context.tasks.task_manager import TaskManager
        self.task_manager = TaskManager(session_id=self.session_id)
        self.workflow_manager = WorkflowManager()  # 工作流管理器
        self.audit_status: Dict[str, Any] = {}  # 主要存储 agent 执行过程中保存的结构化信息
        self.session_memory_manager = SessionMemoryManager()
        # Agent配置信息存储
        self.agent_config: Dict[str, Any] = {}  # 存储agent的配置信息，包括模型配置、系统前缀等

        self.user_memory_manager = user_memory_manager
        self.tool_manager = tool_manager # 存储工具管理器
        self.skill_manager = skill_manager

        self.init_more(workspace_root)

    def init_more(self, workspace_root: str):
        logger.info(f"SessionContext: 后初始化会话上下文，会话ID: {self.session_id}")
        self.session_workspace = os.path.join(workspace_root, self.session_id)
        
        # 定义虚拟工作空间路径 / Define virtual workspace path
        self.virtual_workspace = "/workspace"
        
        # 临时变量存储宿主机路径
        _agent_workspace_host_path = os.path.join(self.session_workspace, "agent_workspace")

        if not os.path.exists(self.session_workspace):
            os.makedirs(self.session_workspace)
            # 创建agent 执行过程中保存内容的文件夹
            if not os.path.exists(_agent_workspace_host_path):
                os.makedirs(_agent_workspace_host_path)

        else:
            # 只有当 agent_workspace 不存在且我们期望它存在时才创建
            # 对于子会话，如果它被配置为共享父会话的 agent_workspace，它可能会在稍后被覆盖
            # 但 SessionContext 初始化时，我们默认创建它自己的
            if not os.path.exists(_agent_workspace_host_path):
                os.makedirs(_agent_workspace_host_path)

            # 加载save的session_status.json
            session_status_path = os.path.join(self.session_workspace, "session_status.json")
            if os.path.exists(session_status_path):
                with open(session_status_path, "r") as f:
                    session_status = json.load(f)
                    self.status = SessionStatus(session_status["status"])
                    self.start_time = session_status["start_time"]
                    self.end_time = session_status["end_time"]
                    self.system_context = session_status["system_context"]
        
        # 确保 llm_request 目录存在，用于存放请求日志
        self.llm_request_dir = os.path.join(self.session_workspace, "llm_request")
        if not os.path.exists(self.llm_request_dir):
            os.makedirs(self.llm_request_dir)

        current_time_str = datetime.datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%dT%H:%M:%S%z %A')
        self.system_context['current_time'] = current_time_str
        logger.debug(f"SessionContext: 开始初始化沙箱环境，工作区: {_agent_workspace_host_path}")
        t0 = time.time()
        # 初始化沙箱环境 / Initialize sandbox environment
        # 沙箱内部会自动管理 SandboxFileSystem
        self.sandbox = Sandbox(
            host_workspace=_agent_workspace_host_path,
            virtual_workspace=self.virtual_workspace
        )
        logger.debug(f"SessionContext: 沙箱环境初始化完成，耗时: {time.time() - t0:.3f}s")
        
        # 将 agent_workspace 设置为 SandboxFileSystem 对象，而不是原始路径字符串
        # 这样如果在 Prompt 中直接打印它，会显示 __str__ (即虚拟路径)
        # 如果代码需要宿主机路径，可以使用 self.agent_workspace.host_path
        self.agent_workspace = self.sandbox.file_system
        
        # 为了兼容性，保留 file_system 引用
        self.file_system = self.sandbox.file_system
        
        # Copy skills to workspace if skill manager is available
        if self.skill_manager:
            logger.info(f"SessionContext: 准备复制技能到工作区: {self.agent_workspace.host_path}")
            t1 = time.time()
            logger.info(f"SessionContext: 当前可用的技能: {list(self.skill_manager.skills.keys())}")
            try:
                self.skill_manager.prepare_skills_in_workspace(self.agent_workspace.host_path)
                logger.info(f"SessionContext: 技能复制完成，耗时: {time.time() - t1:.3f}s")
            except Exception as e:
                logger.error(f"SessionContext: 技能复制失败: {e}", exc_info=True)
        else:
            logger.warning("SessionContext: SkillManager 未初始化，跳过技能复制")
        
        # file_workspace 使用虚拟路径，避免暴露宿主机绝对路径
        self.system_context['file_workspace'] = self.virtual_workspace
        if self.user_id:
            self.system_context['user_id'] = self.user_id
        # if self.system_context['file_workspace'].startswith('/'):
        #     self.system_context['file_workspace'] = self.system_context['file_workspace'][1:]
        self.system_context['session_id'] = self.session_id
        # self.system_context['文件权限'] = "只允许在 "+self.system_context['file_workspace']+" 目录下操作读写文件，并且使用绝对路径"
        self.system_context['file_permission'] = "only allow read and write files in the "+self.system_context['file_workspace']+" directory, and use absolute path"
        self.system_context['response_language'] = "zh-CN(简体中文)"

        # 如果有历史的messages.json，则加载messages.json
        messages_path = os.path.join(self.session_workspace, "messages.json")
        if os.path.exists(messages_path):
            t2 = time.time()
            with open(messages_path, "r") as f:
                messages = json.load(f)
                for message_item in messages:
                    self.message_manager.add_messages(MessageChunk(**message_item))
                logger.info(f"已经成功加载{len(messages)}条历史消息，耗时: {time.time() - t2:.3f}s")

    async def init_user_memory_context(self):
        """初始化用户记忆
        """
        if self.user_id is None:
            logger.info("SessionContext: 用户ID为空，无法初始化用户记忆")
            return

        # 使用已注入的UserMemoryManager
        if self.user_memory_manager:
            try:
                # 检查是否可用
                if not self.user_memory_manager.is_enabled():
                    logger.info(f"SessionContext: UserMemoryManager不可用，用户ID: {self.user_id}")
                else:
                    logger.info(f"SessionContext: UserMemoryManager已启用，用户ID: {self.user_id}")
                    # user_memory_manager 初始化成功，需要在system context添加对于 记忆使用的说明和要求
                    self.system_context['长期记忆的要求'] = self.user_memory_manager.get_user_memory_usage_description()
                    # 自动查询系统级记忆并注入到system_context
                    await self._load_system_memories()

            except Exception as e:
                logger.error(f"SessionContext: 初始化UserMemoryManager失败: {e}")
                # self.user_memory_manager = None # 不要置空全局实例

    def set_agent_config(self, model: Optional[str] = None, model_config: Optional[dict] = None, system_prefix: Optional[str] = None,
                         available_tools: Optional[list] = None, system_context: Optional[dict] = None,
                         available_workflows: Optional[dict] = None, deep_thinking: Optional[bool] = None,
                         multi_agent: Optional[bool] = None, more_suggest: bool = False,
                         max_loop_count: int = 10):
        """设置agent配置信息

        Args:
            model: 模型名称或OpenAI客户端实例
            model_config: 模型配置
            system_prefix: 系统前缀

            available_tools: 可用工具列表
            system_context: 系统上下文
            available_workflows: 可用工作流
            deep_thinking: 深度思考模式
            multi_agent: 多智能体模式
            more_suggest: 更多建议模式
            max_loop_count: 最大循环次数
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
            "name": f"Agent Session {self.session_id}",
            "description": f"Agent configuration for session {self.session_id}",
            "systemPrefix": system_prefix or "",
            "deepThinking": deep_thinking if deep_thinking is not None else False,
            "multiAgent": multi_agent if multi_agent is not None else False,
            "moreSupport": more_suggest,
            "maxLoopCount": max_loop_count,
            "llmConfig": llm_config,
            "availableTools": available_tools or [],
            "systemContext": system_context or {},
            "availableWorkflows": available_workflows or {},
            "exportTime": current_time.isoformat(),
            "version": "1.0"
        }
        logger.debug("SessionContext: 设置agent配置信息完成")

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
                    logger.info(f"成功注入 {len(system_memories)} 种类型的系统级记忆到system_context")
            else:
                logger.info("未找到系统级记忆，跳过注入")

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

    # 注意：自动记忆提取功能已迁移到sagents层面
    # 现在由sagents直接调用MemoryExtractionAgent来处理记忆提取和更新

    def add_and_update_system_context(self, new_system_context: Dict[str, Any]):
        """添加并更新系统上下文"""
        if new_system_context:
            self.system_context.update(new_system_context)

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
            response_dict = self._make_serializable(llm_request['response'])
            if not isinstance(response_dict, dict):
                continue
            if 'usage' in response_dict:
                step_info = {
                    "step_name": (llm_request.get("request") or {}).get("step_name", "unknown"),
                    "usage": response_dict.get("usage"),
                }
                tokens_info["per_step_info"].append(step_info)
                if response_dict.get('usage'):
                    for key, value in response_dict['usage'].items():
                        if isinstance(value, int) or isinstance(value, float):
                            if key not in tokens_info["total_info"]:
                                tokens_info["total_info"][key] = 0
                            tokens_info["total_info"][key] += value
        return tokens_info

    def save(self):
        """保存会话上下文"""
        logger.debug(f"SessionContext: Saving session context for {self.session_id}")
        # 先判断该会话的文件夹是否存在
        if not os.path.exists(self.session_workspace):
            os.makedirs(self.session_workspace)
            logger.debug(f"SessionContext: Created session workspace: {self.session_workspace}")

        # 保存模型请求记录
        llm_request_folder = os.path.join(self.session_workspace, "llm_request")
        if not os.path.exists(llm_request_folder):
            os.makedirs(llm_request_folder)
            logger.debug(f"SessionContext: Created llm_request folder: {llm_request_folder}")

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
        logger.debug(f"SessionContext: 保存llm_requests_logs，当前的序号从{max_index + 1}开始")
        logger.debug(f"SessionContext: 需要保存的llm_requests_logs数量: {len(self.llm_requests_logs)}")
        
        for i, llm_request in enumerate(self.llm_requests_logs):
            file_name = f"{max_index + 1 + i}_{llm_request['request'].get('step_name', 'unknown')}_{time.strftime('%Y%m%d%H%M%S', time.localtime(llm_request['timestamp']))}.json"
            file_path = os.path.join(llm_request_folder, file_name)
            logger.debug(f"SessionContext: Saving LLM request to {file_path}")
            
            try:
                with open(file_path, "w") as f:
                    # 创建可序列化的副本
                    serializable_request = {
                        "request": self._make_serializable(llm_request['request']),
                        "response": self._make_serializable(llm_request['response']),
                        "timestamp": llm_request['timestamp']
                    }
                    json.dump(serializable_request, f, ensure_ascii=False, indent=4)
            except Exception as e:
                logger.error(f"SessionContext: Failed to write log file {file_path}: {e}")
        # 根据

        # 保存messages 到messages.json
        with open(os.path.join(self.session_workspace, "messages.json"), "w") as f:
            # 先将messages 转换为可序列化的格式
            serializable_messages = self._make_serializable(self.message_manager.messages)
            json.dump(serializable_messages, f, ensure_ascii=False, indent=4)

        # 保存task_manager 到tasks.json
        with open(os.path.join(self.session_workspace, "tasks.json"), "w") as f:
            # 先将messages 转换为可序列化的格式
            serializable_tasks = self.task_manager.to_dict()
            json.dump(serializable_tasks, f, ensure_ascii=False, indent=4)

        # 保存其他的状态和变量,方便进行恢复
        # 先查看有多少个 session_status_*.json 文件
        existing_files = os.listdir(self.session_workspace)
        max_index = -1
        for file in existing_files:
            if file.startswith("session_status_") and file.endswith(".json"):
                index = int(file.split("_")[2].split(".")[0])
                max_index = max(max_index, index)
        # 从max_index + 1 开始
        session_status_index = max_index + 1
        # 保存到 session_status_index.json
        with open(os.path.join(self.session_workspace, f"session_status_{session_status_index}.json"), "w") as f:
            json.dump({
                "status": self.status.value,
                "start_time": self.start_time,
                "end_time": self.end_time,
                "thread_id": self.thread_id,
                "system_context": self.system_context,
                "session_id": self.session_id,
                "session_workspace": self.session_workspace,
                "agent_workspace": self.agent_workspace.host_path,
                "tokens_usage_info": self.get_tokens_usage_info(),
                "audit_status": self.audit_status,
                # 已移除 SessionStateMachine 相关持久化
            }, f, ensure_ascii=False, indent=4)

        # 保存agent配置文件
        if self.agent_config:
            agent_config_path = os.path.join(self.session_workspace, "agent_config.json")
            with open(agent_config_path, "w") as f:
                # 创建可序列化的agent配置副本
                serializable_config = self._make_serializable(self.agent_config)
                json.dump(serializable_config, f, ensure_ascii=False, indent=4)
            logger.debug(f"SessionContext: 保存agent配置文件到 {agent_config_path}")

    def _make_serializable(self, obj):
        """将对象转换为可序列化的格式"""
        if isinstance(obj, list):
            # 处理列表，递归处理每个元素
            return [self._make_serializable(item) for item in obj]
        elif isinstance(obj, dict):
            # 处理字典，递归处理每个值
            return {key: self._make_serializable(value) for key, value in obj.items()}
        elif hasattr(obj, 'model_dump'):
            # Pydantic 对象
            return obj.model_dump()
        elif hasattr(obj, '__dict__'):
            # 普通对象，转换为字典
            result = {}
            for key, value in obj.__dict__.items():
                try:
                    json.dumps(value)  # 测试是否可序列化
                    result[key] = self._make_serializable(value)
                except (TypeError, ValueError):
                    # 不可序列化的值，转换为字符串
                    result[key] = str(value)
            return result
        else:
            # 基本类型或其他类型
            try:
                json.dumps(obj)  # 测试是否可序列化
                return obj
            except (TypeError, ValueError):
                # 不可序列化的值，转换为字符串
                return str(obj)

    def _serialize_messages_for_context(self, messages: List[MessageChunk]) -> str:
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

    def set_history_context(self) -> None:
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
            history_messages_str = self._serialize_messages_for_context(history_messages)
            self.system_context['history_messages'] = history_messages_str

        logger.info(
            f"SessionContext: 历史上下文准备完成 - "
            f"检索历史消息{len(history_messages)}条消息到system_context, "
            f"总耗时: {time.time() - t_start:.3f}s (准备: {t_prepare - t_start:.3f}s, 检索: {t_retrieve - t_prepare:.3f}s)"
        )


# 全局会话上下文管理
_active_sessions: Dict[str, SessionContext] = {}


def get_session_context(session_id: str) -> Optional[SessionContext]:
    """获取会话上下文"""
    if session_id not in _active_sessions:
        # 避免递归调用 logger
        # logger.debug(f"SessionContext: 会话 {session_id} 不存在")
        return None
    return _active_sessions[session_id]


def _get_workspace_root() -> str:
    workspace_root = (
        os.environ.get("SAGE_WORKSPACE_PATH")
        or os.environ.get("PREFIX_FILE_WORKSPACE")
        or os.path.abspath("agent_workspace")
    )
    return os.path.abspath(workspace_root)


def get_session_messages(session_id: str) -> List[MessageChunk]:
    workspace_root = _get_workspace_root()
    messages_path = os.path.join(workspace_root, session_id, "messages.json")
    if not os.path.exists(messages_path):
        return []
    try:
        with open(messages_path, "r", encoding="utf-8") as f:
            raw_messages = json.load(f)
    except Exception as e:
        logger.error(f"SessionContext: 读取 messages.json 失败: {e}")
        return []

    if not isinstance(raw_messages, list):
        return []

    messages: List[MessageChunk] = []
    for msg in raw_messages:
        if isinstance(msg, MessageChunk):
            messages.append(msg)
            continue
        if isinstance(msg, dict):
            try:
                messages.append(MessageChunk.from_dict(msg))
            except Exception:
                continue
    return messages


def init_session_context(
    session_id: str,
    workspace_root: str,
    user_id: Optional[str] = None,
    context_budget_config: Optional[Dict[str, Any]] = None,
    user_memory_manager: Optional[Any] = None,
    tool_manager: Optional[Any] = None,
    skill_manager: Optional[Union[SkillManager, SkillProxy]] = None,
) -> SessionContext:
    """初始化会话上下文"""
    if session_id in _active_sessions:
        # 如果提供了tool_manager，更新现有会话的tool_manager
        if tool_manager:
            _active_sessions[session_id].tool_manager = tool_manager
        # 如果提供了skill_manager，更新现有会话的skill_manager
        if skill_manager:
            _active_sessions[session_id].skill_manager = skill_manager
        return _active_sessions[session_id]
    _active_sessions[session_id] = SessionContext(
        session_id,
        user_id,
        workspace_root,
        context_budget_config=context_budget_config,
        user_memory_manager=user_memory_manager,
        tool_manager=tool_manager,
        skill_manager=skill_manager,
    )
    return _active_sessions[session_id]


def get_session_run_lock(session_id: str) -> UnifiedLock:
    return lock_manager.get_lock(session_id)


def delete_session_run_lock(session_id: str):
    lock_manager.delete_lock_ref(session_id)


def delete_session_context(session_id: str):
    """删除会话上下文"""
    if session_id in _active_sessions:
        # 清理session专用的日志资源
        try:
            logger.cleanup_session_logger(session_id)
        except Exception as e:
            logger.warning(f"清理session {session_id} 日志资源时出错: {e}")

        del _active_sessions[session_id]


def list_active_sessions() -> List[Dict[str, Any]]:
    """
    列出所有活跃会话

    Returns:
        List[Dict[str, Any]]: 会话信息列表
    """
    return [
        {
            "session_id": session_id,
            "status": session.status.value,
            "start_time": session.start_time,
        }
        for session_id, session in _active_sessions.items()
    ]
