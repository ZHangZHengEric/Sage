"""
全局变量管理模块

统一管理系统中的所有全局变量，包括服务实例、配置参数等
"""

import traceback
import os
import json
from typing import Optional, Dict, Any
from sagents.tool.tool_manager import ToolManager
from sagents.utils.logger import logger
from config.settings import StartupConfig
from config.settings import get_startup_config

_GLOBAL_TOOL_MANAGER: Optional[ToolManager] = None  # 工具管理器
_GLOBAL_STARTUP_CONFIG: Optional[StartupConfig] = None  # 服务器启动参数
_GLOBAL_ACTIVE_SESSION: Dict[str, Dict[str, Any]] = {}  # 活跃会话映射


def get_tool_manager():
    """获取工具管理器"""
    global _GLOBAL_TOOL_MANAGER
    return _GLOBAL_TOOL_MANAGER


def set_tool_manager(tm: ToolManager):
    """设置工具管理器"""
    global _GLOBAL_TOOL_MANAGER
    _GLOBAL_TOOL_MANAGER = tm


def get_all_active_sessions_service_map() -> Dict[str, Dict[str, Any]]:
    """获取所有活跃会话服务映射"""
    return _GLOBAL_ACTIVE_SESSION


def set_all_active_sessions_service_map(session_map: Dict[str, Dict[str, Any]]):
    """设置所有活跃会话服务映射"""
    global _GLOBAL_ACTIVE_SESSION
    _GLOBAL_ACTIVE_SESSION = session_map


async def initialize_tool_manager():
    """初始化工具管理器"""
    try:
        tool_manager_instance = ToolManager()
        set_tool_manager(tool_manager_instance)
        return tool_manager_instance
    except Exception as e:
        logger.error(f"工具管理器初始化失败: {e}")
        logger.error(traceback.format_exc())
        return None


async def _should_initialize_data() -> bool:
    cfg = get_startup_config()
    if cfg and cfg.db_type == "memory":
        return True
    from models.mcp_server import MCPServerDao
    from models.agent import AgentConfigDao

    mcp_server_dao = MCPServerDao()
    mcp_servers = await mcp_server_dao.get_all()
    agent_config_dao = AgentConfigDao()
    agent_configs = await agent_config_dao.get_all()
    return len(mcp_servers) == 0 and len(agent_configs) == 0


async def _load_preset_mcp_config(config_path: str):
    if not config_path or not os.path.exists(config_path):
        logger.warning(f"预设MCP配置文件不存在: {config_path}")
        return
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    mcp_servers = config.get("mcpServers", {})
    from models.mcp_server import MCPServerDao

    mcp_server_dao = MCPServerDao()
    for name, server_config in mcp_servers.items():
        await mcp_server_dao.save_mcp_server(name, server_config)
    logger.info(f"已加载 {len(mcp_servers)} 个MCP服务器配置")


async def _load_preset_agent_config(config_path: str):
    if not config_path or not os.path.exists(config_path):
        logger.warning(f"预设Agent配置文件不存在: {config_path}")
        return
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    from models.agent import AgentConfigDao, Agent

    agent_config_dao = AgentConfigDao()
    if "systemPrefix" in config or "systemContext" in config:
        obj = Agent(agent_id="default", name="Default Agent", config=config)
        await agent_config_dao.save(obj)
        logger.info("已加载默认Agent配置（旧格式）")
    else:
        count = 0
        for agent_id, agent_config in config.items():
            if isinstance(agent_config, dict):
                name = agent_config.get("name", f"Agent {agent_id}")
                obj = Agent(agent_id=agent_id, name=name, config=agent_config)
                await agent_config_dao.save(obj)
                count += 1
        logger.info(f"已加载 {count} 个Agent配置")


async def initialize_db_data():
    cfg = get_startup_config()
    if not await _should_initialize_data():
        logger.debug("数据库已存在数据，跳过预加载")
        return
    await _load_preset_mcp_config(cfg.preset_mcp_config)
    await _load_preset_agent_config(cfg.preset_running_config)
    logger.debug("数据库预加载完成")


async def close_tool_manager():
    """关闭工具管理器"""
    tool_manager = get_tool_manager()
    if tool_manager:
        set_tool_manager(None)
