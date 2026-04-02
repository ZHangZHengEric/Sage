from typing import Any, Dict, List

from loguru import logger
from sagents.tool.tool_manager import get_tool_manager


def enforce_required_tools(agent_config: Dict[str, Any]) -> Dict[str, Any]:
    """根据 Agent 配置强制添加必要的工具（server / desktop 共享逻辑）。

    - 如果记忆类型选择了 "user"，强制添加 search_memory 工具；
    - 如果 Agent 策略/模式是 fibre，强制添加 sys_spawn_agent/sys_delegate_task/sys_finish_task；
    - 同时保持对 available_tools / availableTools 两种大小写写法的兼容。
    """
    available_tools = agent_config.get("available_tools", []) or agent_config.get(
        "availableTools", []
    )
    if not available_tools:
        available_tools = []

    tools_set = set(available_tools)
    original_tools = tools_set.copy()

    # 记忆类型
    memory_type = agent_config.get("memoryType") or agent_config.get("memory_type")
    if memory_type == "user":
        tools_set.add("search_memory")
        logger.info("Agent 记忆类型为用户，强制添加 search_memory 工具")

    # Agent 策略/模式
    agent_mode = agent_config.get("agentMode") or agent_config.get("agent_mode")
    if agent_mode == "fibre":
        fibre_tools = {"sys_spawn_agent", "sys_delegate_task", "sys_finish_task"}
        tools_set.update(fibre_tools)
        logger.info(f"Agent 策略为 fibre，强制添加 fibre 工具: {fibre_tools}")

    if tools_set != original_tools:
        new_tools = list(tools_set)
        if "available_tools" in agent_config:
            agent_config["available_tools"] = new_tools
        if "availableTools" in agent_config:
            agent_config["availableTools"] = new_tools
        logger.info(f"Agent 工具列表已更新: {original_tools} -> {tools_set}")

    return agent_config


def validate_and_filter_tools(agent_config: Dict[str, Any]) -> Dict[str, Any]:
    """验证并过滤掉不可用的工具（server / desktop 共享逻辑）。

    - 通过 sagents 的 ToolManager 获取当前可用的工具名集合；
    - 过滤 available_tools / availableTools 中不存在的工具，并更新配置；
    """
    tm = get_tool_manager()
    if not tm:
        return agent_config

    available_tools = agent_config.get("available_tools", []) or agent_config.get(
        "availableTools", []
    )
    if not available_tools:
        return agent_config

    valid_tool_names = set(tm.list_all_tools_name())

    filtered_tools = [t for t in available_tools if t in valid_tool_names]
    if len(filtered_tools) != len(available_tools):
        removed_tools = set(available_tools) - set(filtered_tools)
        logger.warning(f"以下工具不可用，已自动移除: {removed_tools}")

        if "available_tools" in agent_config:
            agent_config["available_tools"] = filtered_tools
        if "availableTools" in agent_config:
            agent_config["availableTools"] = filtered_tools

    return agent_config
