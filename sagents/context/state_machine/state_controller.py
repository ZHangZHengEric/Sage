from typing import Dict, Any, Optional, List
import time
import traceback

from sagents.utils.logger import logger
from .schemas import StateMachineConfig, StateNodeConfig, Edge, NodeStatus
from .state_graph import StateGraph
from .session_state import SessionStateRuntime


class SessionStateMachine:
    """
    会话级状态机：管理 DAG 配置、运行时状态，以及当次请求的状态变更。

    设计要点：
    - 不持久化：配置与状态均由请求传入，仅在内存中更新并返回。
    - 可决策目标节点：若未指定目标，选择第一个可执行的未完成节点。
    - 提供 per-request 更新方法：输入配置与现有状态，输出更新后的运行时字典。
    """

    def __init__(self, session_id: str, session_workspace: str):
        self.session_id = session_id
        self.runtime = SessionStateRuntime(session_workspace)
        self.graph_model: Optional[StateGraph] = None
        self.config: Optional[StateMachineConfig] = None

    def apply_config(self, config_dict: Dict[str, Any]):
        """
        接收每次请求传入的配置，更新 DAG 与运行时图结构。
        config_dict 结构示例：
        {
          "nodes": [{"id":"A","name":"Start","description":"..."}, ...],
          "edges": [{"source":"A","target":"B"}, ...],
          "start_node_id": "A"
        }
        """
        try:
            nodes: Dict[str, StateNodeConfig] = {}
            for node in config_dict.get("nodes", []):
                n = StateNodeConfig(
                    id=node["id"],
                    name=node.get("name", node["id"]),
                    type=node.get("type", "node"),
                    description=node.get("description"),
                    agent=node.get("agent"),
                    metadata=node.get("metadata", {}),
                )
                nodes[n.id] = n
            edges: List[Edge] = []
            for e in config_dict.get("edges", []):
                edges.append(Edge(source=e["source"], target=e["target"]))
            start_node_id = config_dict.get("start_node_id")

            self.config = StateMachineConfig(nodes=nodes, edges=edges, start_node_id=start_node_id)
            self.graph_model = StateGraph(self.config)
            # 更新运行时 graph 序列化
            self.runtime.graph = self.config.to_dict()
            logger.info(f"SessionStateMachine: 配置已应用，节点数={len(nodes)}, 边数={len(edges)}")
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"SessionStateMachine: 应用配置失败: {e}\n{tb}")
            self.runtime.tracebacks.append({"time": time.time(), "error": str(e), "traceback": tb})

    def apply_status(self, status_map: Dict[str, Any]):
        """应用外部传入的节点状态映射（不做持久化）。"""
        try:
            if not self.config or not self.config.nodes:
                return
            for nid in self.config.nodes.keys():
                raw = status_map.get(nid, {"status": NodeStatus.NOT_STARTED.value})
                status_value = raw["status"] if isinstance(raw, dict) else raw
                try:
                    status_enum = NodeStatus(status_value)
                except Exception:
                    status_enum = NodeStatus.NOT_STARTED
                extras = raw if isinstance(raw, dict) else {}
                # 避免与位置参数重复
                if isinstance(extras, dict):
                    extras = dict(extras)
                    extras.pop("status", None)
                self.runtime.set_status(nid, status_enum, **extras)
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"SessionStateMachine: 应用状态失败: {e}\n{tb}")
            self.runtime.tracebacks.append({"time": time.time(), "error": str(e), "traceback": tb})

    def set_previous_output(self, output: Optional[Dict[str, Any]]):
        self.runtime.previous_output = output

    def decide_current_target(self, specified: Optional[str] = None) -> Optional[str]:
        """若指定目标则使用，否则选择首个可执行且未完成的节点。"""
        try:
            if specified:
                self.runtime.current_target = specified
                return specified
            if not self.graph_model or not self.config:
                return None
            status_map = {}
            for nid, s in self.runtime.node_status.items():
                try:
                    status_map[nid] = NodeStatus(s.get("status", NodeStatus.NOT_STARTED.value))
                except Exception:
                    status_map[nid] = NodeStatus.NOT_STARTED
            target = self.graph_model.first_executable(status_map)
            self.runtime.current_target = target
            return target
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"SessionStateMachine: 选择目标失败: {e}\n{tb}")
            self.runtime.tracebacks.append({"time": time.time(), "error": str(e), "traceback": tb})
            return None

    def start_node(self, node_id: Optional[str] = None):
        target = node_id or self.runtime.current_target
        if not target:
            return
        self.runtime.set_status(target, NodeStatus.IN_PROGRESS)

    def complete_node(self, output: Dict[str, Any], node_id: Optional[str] = None):
        target = node_id or self.runtime.current_target
        if not target:
            return
        # 校验前驱均已完成
        preds = self.graph_model.predecessors(target) if self.graph_model else []
        all_done = all(self.runtime.node_status.get(p, {}).get("status") == NodeStatus.COMPLETED.value for p in preds)
        if not all_done:
            # 不满足条件，标记需要用户输入或前置未完成
            self.runtime.set_status(target, NodeStatus.NEED_USER_INPUT, reason="predecessors_not_completed")
            return
        self.runtime.set_status(target, NodeStatus.COMPLETED, last_output=output)
        next_target = self.decide_current_target()
        if not next_target:
            self.runtime.current_target = None

    def fail_node(self, error: Exception, node_id: Optional[str] = None):
        target = node_id or self.runtime.current_target
        tb = traceback.format_exc()
        if target:
            self.runtime.set_status(target, NodeStatus.FAILED, error=str(error), traceback=tb)
        self.runtime.tracebacks.append({"time": time.time(), "error": str(error), "traceback": tb})
        logger.error(f"SessionStateMachine: 节点失败: {error}\n{tb}")

    def update_status_for_request(self, config_dict: Dict[str, Any], status_map: Dict[str, Any],
                                  previous_output: Optional[Dict[str, Any]] = None,
                                  target_node_id: Optional[str] = None,
                                  action: str = "decide") -> Dict[str, Any]:
        """
        per-request 主入口：
        - 输入当次请求的状态机配置与现有状态映射
        - 决策/更新目标节点状态（start/complete/fail/decide）
        - 返回更新后的运行时字典（用于日志或前端展示）
        """
        try:
            self.apply_config(config_dict)
            self.apply_status(status_map or {})
            if previous_output is not None:
                self.set_previous_output(previous_output)
            current_target = self.decide_current_target(target_node_id)
            if action == "start" and current_target:
                self.start_node(current_target)
            elif action == "complete" and current_target:
                self.complete_node(previous_output or {}, current_target)
            elif action == "fail" and current_target:
                self.fail_node(Exception("fail_by_request"), current_target)
            # action == "decide" 仅决策，不修改
            return self.runtime.to_dict()
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"SessionStateMachine: 当次请求更新失败: {e}\n{tb}")
            self.runtime.tracebacks.append({"time": time.time(), "error": str(e), "traceback": tb})
            return self.runtime.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        return self.runtime.to_dict()
