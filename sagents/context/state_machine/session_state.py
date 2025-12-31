"""
运行时状态容器（不持久化版本）

应用户要求：状态机的配置与状态均由每次请求传入，
此运行时仅在进程内存中使用，不读写持久化文件。
"""

import time
from typing import Dict, Any, Optional, List
from .schemas import NodeStatus


class SessionStateRuntime:
    """会话状态机的内存态：保存图、节点状态、当前目标等。"""
    def __init__(self, session_workspace: str):
        # session_workspace 仅用于日志定位（不做文件读写）
        self.session_workspace = session_workspace
        self.graph: Optional[Dict[str, Any]] = None
        self.node_status: Dict[str, Dict[str, Any]] = {}
        self.current_target: Optional[str] = None
        self.previous_output: Optional[Dict[str, Any]] = None
        self.tracebacks: List[Dict[str, Any]] = []

    def set_status(self, node_id: str, status: NodeStatus, **kwargs):
        item = self.node_status.get(node_id, {"status": NodeStatus.NOT_STARTED.value})
        item["status"] = status.value
        now = time.time()
        if status == NodeStatus.IN_PROGRESS:
            item["started_at"] = now
        if status in (NodeStatus.COMPLETED, NodeStatus.FAILED):
            item["completed_at"] = now
        for k, v in kwargs.items():
            item[k] = v
        self.node_status[node_id] = item

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph": self.graph,
            "node_status": self.node_status,
            "current_target": self.current_target,
            "previous_output": self.previous_output,
            "tracebacks": self.tracebacks,
        }
