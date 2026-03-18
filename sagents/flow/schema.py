from typing import List, Optional, Union, Dict, Any, Literal
from pydantic import BaseModel, Field

class FlowNode(BaseModel):
    """所有流程节点的基类"""
    node_type: str
    description: Optional[str] = None

class AgentNode(FlowNode):
    """执行单个 Agent"""
    node_type: Literal["agent"] = "agent"
    agent_key: str              # Agent的注册Key，如 "task_planner", "simple"
    agent_config: Optional[Dict[str, Any]] = None # 覆盖该节点的特殊配置

class SequenceNode(FlowNode):
    """顺序执行一组节点"""
    node_type: Literal["sequence"] = "sequence"
    steps: List[Union["AgentNode", "SequenceNode", "LoopNode", "IfNode", "SwitchNode", "ParallelNode"]]

class ParallelNode(FlowNode):
    """并行执行一组节点"""
    node_type: Literal["parallel"] = "parallel"
    branches: List[Union["AgentNode", "SequenceNode", "LoopNode", "IfNode", "SwitchNode"]]
    max_concurrency: int = 5    # 最大并发数

class LoopNode(FlowNode):
    """循环执行，直到满足停止条件"""
    node_type: Literal["loop"] = "loop"
    body: Union["AgentNode", "SequenceNode", "LoopNode", "IfNode", "SwitchNode", "ParallelNode"]
    condition: str              # 停止条件 ID，例如 "max_loop_reached" 或 "task_completed"
    max_loops: int = 10         # 安全熔断机制

class IfNode(FlowNode):
    """条件分支"""
    node_type: Literal["if"] = "if"
    condition: str              # 判断条件 ID，例如 "is_deep_thinking"
    true_body: Union["AgentNode", "SequenceNode", "LoopNode", "IfNode", "SwitchNode", "ParallelNode"]
    false_body: Optional[Union["AgentNode", "SequenceNode", "LoopNode", "IfNode", "SwitchNode", "ParallelNode"]] = None

class SwitchNode(FlowNode):
    """多路分支（用于 agent_mode 选择）"""
    node_type: Literal["switch"] = "switch"
    variable: str               # 上下文变量名，例如 "agent_mode"
    cases: Dict[str, Union["AgentNode", "SequenceNode", "LoopNode", "IfNode", "SwitchNode", "ParallelNode"]]  # 映射关系: "fibre" -> FlowNode
    default: Optional[Union["AgentNode", "SequenceNode", "LoopNode", "IfNode", "SwitchNode", "ParallelNode"]] = None

# 顶层 Flow 对象
class AgentFlow(BaseModel):
    name: str
    description: str = ""
    root: Union["AgentNode", "SequenceNode", "LoopNode", "IfNode", "SwitchNode", "ParallelNode"]

# 为了支持递归定义，需要更新前向引用
SequenceNode.update_forward_refs()
ParallelNode.update_forward_refs()
LoopNode.update_forward_refs()
IfNode.update_forward_refs()
SwitchNode.update_forward_refs()
