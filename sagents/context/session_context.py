# 负责管理会话的上下文，以及过程中产生的日志以及状态记录。
from math import log
import time
import threading
from typing import Dict, Any, Optional, List
from enum import Enum
from sagents.context.messages.message_manager import MessageManager
from sagents.context.tasks.task_manager import TaskManager
from sagents.utils.logger import logger
import json
import sys,os
import datetime

class SessionStatus(Enum):
    """会话状态枚举"""
    IDLE = "idle"                    # 空闲状态
    RUNNING = "running"              # 运行中
    INTERRUPTED = "interrupted"      # 被中断
    COMPLETED = "completed"          # 已完成
    ERROR = "error"                  # 错误状态

class SessionContext:
    def __init__(self, session_id: str, workspace_root: str = None):
        self.session_id = session_id
        self.llm_requests_logs = []
        self.workspace_root = workspace_root
        self.session_workspace = None
        self.agent_workspace = None
        self.thread_id = threading.get_ident()
        self.start_time = time.time()
        self.end_time = None
        self.status = SessionStatus.IDLE
        self.system_context = {}
        self.message_manager = MessageManager()
        self.task_manager = TaskManager(session_id=self.session_id)
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

        current_time_str = datetime.datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')
        self.system_context['current_time'] = current_time_str
        # file_workspace 去掉 workspace_root的绝对路径的 前置路径
        self.system_context['file_workspace'] = self.agent_workspace.replace(os.path.abspath(self.workspace_root), "")
        if self.system_context['file_workspace'].startswith('/'):
            self.system_context['file_workspace'] = self.system_context['file_workspace'][1:]
        self.system_context['session_id'] = self.session_id
        self.system_context['文件权限'] = "只允许在 "+self.system_context['file_workspace']+" 目录下操作文件"

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
        with open(os.path.join(self.session_workspace, "session_status.json"), "w") as f:
            json.dump({
                "status": self.status.value,
                "start_time": self.start_time,
                "end_time": self.end_time,
                "thread_id": self.thread_id,
                "system_context": self.system_context,
                "session_id": self.session_id,
                "session_workspace": self.session_workspace,
                "agent_workspace": self.agent_workspace,
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

def init_session_context(session_id: str, workspace_root: str = None) -> SessionContext:
    if session_id in _active_sessions:
        return _active_sessions[session_id]
    _active_sessions[session_id] = SessionContext(session_id, workspace_root)
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