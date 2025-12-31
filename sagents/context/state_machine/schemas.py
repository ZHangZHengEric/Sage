"""
状态机数据结构定义

本文件定义了：
- 节点类型与状态枚举（可选，用于前端展示或路由逻辑）
- 节点配置（精简版，仅保留必要的文字描述等元信息）
- 边与状态机配置的数据结构

注意：应用户要求，本状态机的详细配置与状态均由请求传入，
不进行持久化，仅用于当次请求的计算与日志快照。
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class NodeType(str, Enum):
    """节点类型（最简版）：仅区分起始与普通节点

    - START: 起始节点，作为流程入口（通常无前驱）
    - NODE: 普通节点（非起始），执行具体步骤
    """
    START = "start"
    NODE = "node"


class NodeStatus(str, Enum):
    """节点状态枚举：会话层状态管理"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NEED_USER_INPUT = "need_user_input"


@dataclass
class StateNodeConfig:
    """最简节点配置

    约定：description 即该节点完成的描述/标准，由编排层解释与执行。
    """
    id: str
    name: str
    # 仅区分是否为起始节点；默认非起始 NODE
    type: NodeType = NodeType.NODE
    # 文字描述：用于引导或展示（用户要求保留）
    description: Optional[str] = None
    # 其他元信息：按需透传（非持久化）
    agent: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Edge:
    """有向边：构成 DAG"""
    source: str
    target: str

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "target": self.target}


@dataclass
class StateMachineConfig:
    """状态机配置：节点集合与边集合"""
    nodes: Dict[str, StateNodeConfig]
    edges: List[Edge]
    start_node_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "start_node_id": self.start_node_id,
        }
