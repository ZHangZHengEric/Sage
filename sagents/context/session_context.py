# 负责管理会话的上下文，以及过程中产生的日志以及状态记录。
from math import log
import time
import threading
from typing import Dict, Any, Optional, List
from enum import Enum

from openai import responses
from sagents.context.messages.message import MessageChunk
from sagents.context.messages.message_manager import MessageManager
from sagents.context.tasks.task_manager import TaskManager
from sagents.context.workflows import WorkflowManager
from sagents.utils.logger import logger
import json
import sys,os
import datetime
import pytz


class SessionStatus(Enum):
    """会话状态枚举"""
    IDLE = "idle"                    # 空闲状态
    RUNNING = "running"              # 运行中
    INTERRUPTED = "interrupted"      # 被中断
    COMPLETED = "completed"          # 已完成
    ERROR = "error"                  # 错误状态

class SessionContext:
    def __init__(self, session_id: str, user_id: str = None, workspace_root: str = None, memory_root: str = None):
        self.session_id = session_id      
        self.user_id = user_id
        self.llm_requests_logs = []           # 大模型的请求记录
        self.workspace_root = workspace_root  # agent 的工作空间
        
        # 根据传入的memory_root参数设置环境变量
        if memory_root is not None:
            # 确保是绝对路径
            memory_root = os.path.abspath(memory_root)
            logger.info(f"初始化系统变量MEMORY_ROOT_PATH={memory_root}" )
            os.environ['MEMORY_ROOT_PATH'] = memory_root
            self.memory_root = memory_root
            # 判断路径是否存在
            if not os.path.exists(self.memory_root):
                os.makedirs(self.memory_root)
        else:
            # 如果传入None，则移除环境变量（禁用本地记忆）
            os.environ.pop('MEMORY_ROOT_PATH', None)
            self.memory_root = None
        
        self.session_workspace = None      # agent 该会话的工作空间，保存日志等信息
        self.agent_workspace = None         # agent 该会话的工作空间，保存执行过程中产生的内容
        self.thread_id = threading.get_ident()
        self.start_time = time.time()
        self.end_time = None
        self.status = SessionStatus.IDLE
        self.system_context = {}       # 当前系统的环境变量
        self.message_manager = MessageManager()
        self.task_manager = TaskManager(session_id=self.session_id)
        self.workflow_manager = WorkflowManager()  # 工作流管理器
        self.audit_status = {}  # 主要存储 agent 执行过程中保存的结构化信息
        
        # 初始化UserMemoryManager
        self.user_memory_manager = None
        
        self.init_more()
        
        
    def init_more(self):
        logger.info(f"SessionContext: 后初始化会话上下文，会话ID: {self.session_id}")
        self.session_workspace = os.path.join(self.workspace_root, self.session_id)
        if not os.path.exists(self.session_workspace):
            os.makedirs(self.session_workspace)
            # 创建agent 执行过程中保存内容的文件夹
            self.agent_workspace = os.path.join(self.session_workspace, "agent_workspace")
            if not os.path.exists(self.agent_workspace):
                os.makedirs(self.agent_workspace)

        else:
            self.agent_workspace = os.path.join(self.session_workspace, "agent_workspace")
            if not os.path.exists(self.agent_workspace):
                os.makedirs(self.agent_workspace)
            
            # 加载save的session_status.json
            session_status_path = os.path.join(self.session_workspace, "session_status.json")
            if os.path.exists(session_status_path):
                with open(session_status_path, "r") as f:
                    session_status = json.load(f)
                    self.status = SessionStatus(session_status["status"])
                    self.start_time = session_status["start_time"]
                    self.end_time = session_status["end_time"]
                    self.system_context = session_status["system_context"]

        current_time_str = datetime.datetime.now(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%dT%H:%M:%S%z %A')
        self.system_context['current_time'] = current_time_str
        # file_workspace 去掉 workspace_root的绝对路径的 前置路径
        # self.system_context['file_workspace'] = self.agent_workspace.replace(os.path.abspath(self.workspace_root), "")
        self.system_context['file_workspace'] = self.agent_workspace
        if self.user_id:
            self.system_context['user_id'] = self.user_id
        # if self.system_context['file_workspace'].startswith('/'):
        #     self.system_context['file_workspace'] = self.system_context['file_workspace'][1:]
        self.system_context['session_id'] = self.session_id
        self.system_context['文件权限'] = "只允许在 "+self.system_context['file_workspace']+" 目录下操作文件"

        # 如果有历史的messages.json，则加载messages.json
        messages_path = os.path.join(self.session_workspace, "messages.json")
        if os.path.exists(messages_path):
            with open(messages_path, "r") as f:
                messages = json.load(f)
                for message_item in messages:
                    self.message_manager.add_messages(MessageChunk(**message_item))
                logger.info(f"已经成功加载{len(messages)}条历史消息")

    def init_user_memory_manager(self,tool_manager=None):
        """初始化用户记忆管理器
        
        Args:
            tool_manager: 工具管理器实例
        """
        if self.user_id is None:
            return
        
        # 初始化UserMemoryManager
        if self.user_memory_manager is None:
            try:
                from sagents.context.user_memory import UserMemoryManager
                self.user_memory_manager = UserMemoryManager(self.user_id, tool_manager)
                logger.info(f"SessionContext: 初始化UserMemoryManager成功，用户ID: {self.user_id}")
                if self.user_memory_manager.memory_disabled:
                    logger.info(f"SessionContext: UserMemoryManager已禁用，用户ID: {self.user_id}")
                    self.user_memory_manager = None
                else:
                    # user_memory_manager 初始化成功，需要在system context添加对于 记忆使用的说明和要求
                    self.system_context['长期记忆的要求'] = self.user_memory_manager.get_user_memory_usage_description()
                    # 自动查询系统级记忆并注入到system_context
                    self._load_system_memories(tool_manager)

            except Exception as e:
                logger.error(f"SessionContext: 初始化UserMemoryManager失败: {e}")
                self.user_memory_manager = None
    
    def _load_system_memories(self, tool_manager=None):
        """加载系统级记忆并注入到system_context
        
        Args:
            tool_manager: 工具管理器实例
        """
        if not self.user_id or not self.user_memory_manager:
            return
        
        try:
            # 通过UserMemoryManager获取系统级记忆
            system_memories = self.user_memory_manager.get_system_memories(self.session_id)
            
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
    
    def refresh_system_memories(self):
        """刷新系统级记忆"""
        if self.user_memory_manager:
            self._load_system_memories()
            logger.info("系统级记忆已刷新")
    
    def get_system_memories_summary(self) -> str:
        """获取系统级记忆摘要
        
        Returns:
            系统级记忆的摘要字符串
        """
        if not self.user_memory_manager:
            return "记忆管理器未初始化"
        
        try:
            system_memories = self.user_memory_manager.get_system_memories(self.session_id)
            if system_memories:
                summary = []
                for memory_type, content in system_memories.items():
                    lines = content.split('\n')
                    summary.append(f"{memory_type}: {len(lines)} 条记忆")
                return ", ".join(summary)
            else:
                return "无系统级记忆"
        except Exception as e:
            logger.error(f"获取系统级记忆摘要失败: {e}")
            return "获取记忆摘要失败"
    
    # 注意：自动记忆提取功能已迁移到sagents层面
    # 现在由sagents直接调用MemoryExtractionAgent来处理记忆提取和更新

    def add_and_update_system_context(self,new_system_context:Dict[str,Any]):
        """添加并更新系统上下文"""
        if new_system_context:
            self.system_context.update(new_system_context)

    def add_llm_request(self, request: Dict[str, Any], response: Dict[str, Any]):
        """添加LLM请求"""
        self.llm_requests_logs.append({
            "request": request,
            "response": response,
            "timestamp": time.time(),
        })
    
    def get_tokens_usage_info(self):
        """获取tokens使用信息"""
        tokens_info = {"total_info":{}, "per_step_info":[]}
        for llm_request in self.llm_requests_logs:
            response_dict = self._make_serializable(llm_request['response'])
            if 'usage' in response_dict:
                step_info = {"step_name": llm_request['request']['step_name'], "usage": response_dict['usage']}
                tokens_info["per_step_info"].append(step_info)
                if response_dict['usage']:
                    for key, value in response_dict['usage'].items():
                        if isinstance(value, int) or isinstance(value,float) :
                            if key not in tokens_info["total_info"]:
                                tokens_info["total_info"][key] = 0
                            tokens_info["total_info"][key] += value
        return tokens_info
    def save(self):
        """保存会话上下文"""
        # 先判断该会话的文件夹是否存在
        if not os.path.exists(self.session_workspace):
            os.makedirs(self.session_workspace)

        # 保存模型请求记录
        llm_request_folder = os.path.join(self.session_workspace, "llm_request")
        if not os.path.exists(llm_request_folder):
            os.makedirs(llm_request_folder)
        
        # 说明存在，需要看看当前的序号从几开始
        existing_files = os.listdir(llm_request_folder)
        max_index = -1
        for file in existing_files:
            if file.endswith(".json"):
                index = int(file.split("_")[0])
                max_index = max(max_index, index)
        # 从max_index + 1 开始
        logger.debug(f"SessionContext: 保存llm_requests_logs，当前的序号从{max_index + 1}开始")
        logger.debug(f"SessionContext: 需要保存的llm_requests_logs数量: {len(self.llm_requests_logs)}")
        for i, llm_request in enumerate(self.llm_requests_logs):
            with open(os.path.join(llm_request_folder, f"{max_index + 1 + i}_{llm_request['request']['step_name']}_{time.strftime('%Y%m%d%H%M%S', time.localtime(llm_request['timestamp']))}.json"), "w") as f:
                # 创建可序列化的副本
                serializable_request = {
                    "request": self._make_serializable(llm_request['request']),
                    "response": self._make_serializable(llm_request['response']),
                    "timestamp": llm_request['timestamp']
                }
                json.dump(serializable_request, f,ensure_ascii=False, indent=4)
        # 根据

        # 保存messages 到messages.json
        with open(os.path.join(self.session_workspace, "messages.json"), "w") as f:
            # 先将messages 转换为可序列化的格式
            serializable_messages = self._make_serializable(self.message_manager.messages)
            json.dump(serializable_messages, f,ensure_ascii=False, indent=4)
        
        # 保存task_manager 到tasks.json
        with open(os.path.join(self.session_workspace, "tasks.json"), "w") as f:
            # 先将messages 转换为可序列化的格式
            serializable_tasks = self.task_manager.to_dict()
            json.dump(serializable_tasks, f,ensure_ascii=False, indent=4)

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
                "agent_workspace": self.agent_workspace,
                "tokens_usage_info": self.get_tokens_usage_info(),
            }, f,ensure_ascii=False, indent=4)

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


# 全局会话上下文管理
_active_sessions: Dict[str, SessionContext] = {}

def get_session_context(session_id: str) -> SessionContext:
    """获取会话上下文"""
    if session_id not in _active_sessions:
        raise ValueError(f"Session {session_id} not found")
    return _active_sessions[session_id]

def init_session_context(session_id: str, user_id: str = None, workspace_root: str = None, memory_root: str = None) -> SessionContext:
    """初始化会话上下文"""
    if session_id in _active_sessions:
        return _active_sessions[session_id]
    _active_sessions[session_id] = SessionContext(session_id, user_id, workspace_root, memory_root)
    return _active_sessions[session_id]

def delete_session_context(session_id: str):
    """删除会话上下文"""
    if session_id in _active_sessions:
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