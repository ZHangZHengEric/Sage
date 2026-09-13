"""Conservative static reachability: retain all conditional and parallel paths."""

from __future__ import annotations


def reachable_nodes(flows, entrypoint):
    visited = set()
    pending = [(entrypoint, flows[entrypoint].start)]
    result = []
    indexes = {}
    while pending:
        flow_id, node_id = pending.pop()
        key = (flow_id, node_id)
        if key in visited:
            continue
        visited.add(key)
        if flow_id not in indexes:
            flow = flows[flow_id]
            outgoing = {}
            for edge in flow.edges:
                outgoing.setdefault(edge.source, []).append(edge.target)
            indexes[flow_id] = ({node.id: node for node in flow.nodes}, outgoing)
        nodes, outgoing = indexes[flow_id]
        node = nodes[node_id]
        result.append((flow_id, node))
        if node.type == "subflow":
            pending.append((node.flow, flows[node.flow].start))
        if node.type == "parallel":
            pending.extend(
                (flow_id, branch) for branch in node.config.get("branches", ())
            )
        if node.type != "end":
            pending.extend((flow_id, target) for target in outgoing.get(node_id, ()))
    return tuple(result)


def reachable_agents(agents, nodes, selected_agent):
    selected = {selected_agent}
    pending = [node.agent for _, node in nodes if node.type == "agent"]
    while pending:
        agent_id = pending.pop()
        if agent_id in selected:
            continue
        selected.add(agent_id)
        pending.extend(agents[agent_id].subagents)
    return tuple(
        agent_id
        for agent_id in agents
        if agent_id in selected and agent_id != selected_agent
    )
