"""MCP, A2A, and skill ports shared by chat runs and managed packages."""

from __future__ import annotations


def tenant_tools(host, user_id: str, mcp_servers, a2a_agents, *, call_depth: int = 0):
    """Plugins for this tenant's MCP servers and A2A peers, in catalog order."""

    tools = []
    mcp = host.mcp_plugins.get(user_id, mcp_servers)
    if mcp is not None:
        tools.append(mcp)
    peers = host.a2a_plugins.get(user_id, a2a_agents, call_depth=call_depth)
    if peers is not None:
        tools.append(peers)
    return tools


def skill_ports(host, user_id: str, records):
    from app.server_v2.application.skill_runtime import (
        CatalogSkillProvider,
        ReadThroughSkillWorkspace,
    )

    root = host.paths.data_root
    provider = CatalogSkillProvider(records, root)
    workspace = ReadThroughSkillWorkspace(root, user_id, records)
    return provider, workspace
