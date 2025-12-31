"""
状态机图结构与基本算法

职责：
- 维护邻接/前驱关系
- 验证是否为 DAG（无环）
- 提供前驱/后继查询、拓扑排序、以及首个可执行节点选择
"""

from typing import Dict, List, Optional
from .schemas import StateMachineConfig, NodeStatus


class StateGraph:
    def __init__(self, config: StateMachineConfig):
        self.config = config
        # 邻接/前驱表
        self.adj: Dict[str, List[str]] = {nid: [] for nid in config.nodes.keys()}
        self.pred: Dict[str, List[str]] = {nid: [] for nid in config.nodes.keys()}
        for e in config.edges:
            if e.source not in self.adj or e.target not in self.pred:
                raise ValueError(f"Invalid edge: {e.source} -> {e.target}")
            self.adj[e.source].append(e.target)
            self.pred[e.target].append(e.source)
        self._validate_dag()

    def _validate_dag(self):
        """DFS 检测环，确保为 DAG"""
        color: Dict[str, int] = {nid: 0 for nid in self.config.nodes.keys()}  # 0=white,1=gray,2=black

        def dfs(u: str):
            color[u] = 1
            for v in self.adj[u]:
                if color[v] == 1:
                    raise ValueError("Cycle detected in state graph (must be DAG)")
                if color[v] == 0:
                    dfs(v)
            color[u] = 2

        for nid in self.config.nodes.keys():
            if color[nid] == 0:
                dfs(nid)

    def predecessors(self, node_id: str) -> List[str]:
        return self.pred.get(node_id, [])

    def successors(self, node_id: str) -> List[str]:
        return self.adj.get(node_id, [])

    def topo_order(self) -> List[str]:
        """Kahn 算法生成拓扑序"""
        indeg: Dict[str, int] = {nid: len(self.pred[nid]) for nid in self.config.nodes.keys()}
        order: List[str] = []
        queue: List[str] = [nid for nid, d in indeg.items() if d == 0]
        while queue:
            u = queue.pop(0)
            order.append(u)
            for v in self.adj[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    queue.append(v)
        if len(order) != len(self.config.nodes):
            # 正常情况下不会发生（已验证 DAG），此处防御性异常
            raise ValueError("Topological sort failed; graph may not be a DAG")
        return order

    def first_executable(self, status_map: Dict[str, NodeStatus]) -> Optional[str]:
        """选择第一个前驱均完成且自身未完成的节点"""
        for nid in self.topo_order():
            status = status_map.get(nid, NodeStatus.NOT_STARTED)
            if status != NodeStatus.COMPLETED:
                preds = self.predecessors(nid)
                all_done = all(status_map.get(p, NodeStatus.NOT_STARTED) == NodeStatus.COMPLETED for p in preds)
                if all_done:
                    return nid
        return None
