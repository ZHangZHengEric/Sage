import json
import os
from core import config
from sagents.utils.logger import logger
from sagents.tool.tool_manager import ToolManager, set_tool_manager

async def initialize_tool_manager():
    """初始化工具管理器"""
    try:
        tool_manager_instance = ToolManager.get_instance()
        return tool_manager_instance
    except Exception as e:
        logger.error(f"工具管理器初始化失败: {e}")
        return None


async def _should_initialize_data() -> bool:
    cfg = config.get_startup_config()
    if cfg and cfg.db_type == "memory":
        return True
    import models

    mcp_server_dao = models.MCPServerDao()
    mcp_servers = await mcp_server_dao.get_list()
    agent_config_dao = models.AgentConfigDao()
    agent_configs = await agent_config_dao.get_list()
    return len(mcp_servers) == 0 and len(agent_configs) == 0


async def _load_preset_mcp_config(config_path: str):
    if not config_path or not os.path.exists(config_path):
        logger.warning(f"预设MCP配置文件不存在: {config_path}")
        return
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)
    mcp_servers = config_data.get("mcpServers", {})
    import models

    mcp_server_dao = models.MCPServerDao()
    for name, server_config in mcp_servers.items():
        await mcp_server_dao.save_mcp_server(name, server_config)
    logger.info(f"已加载 {len(mcp_servers)} 个MCP服务器配置")


async def _load_preset_agent_config(config_path: str):
    if not config_path or not os.path.exists(config_path):
        logger.warning(f"预设Agent配置文件不存在: {config_path}")
        return
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)
    import models

    agent_config_dao = models.AgentConfigDao()
    if "systemPrefix" in config_data or "systemContext" in config_data:
        obj = models.Agent(agent_id="default", name="Default Agent", config=config_data)
        await agent_config_dao.save(obj)
        logger.info("已加载默认Agent配置（旧格式）")
    else:
        count = 0
        for agent_id, agent_config in config_data.items():
            if isinstance(agent_config, dict):
                name = agent_config.get("name", f"Agent {agent_id}")
                obj = models.Agent(agent_id=agent_id, name=name, config=agent_config)
                await agent_config_dao.save(obj)
                count += 1
        logger.info(f"已加载 {count} 个Agent配置")


async def initialize_db_data():
    """初始化数据库数据"""
    cfg = config.get_startup_config()
    if not await _should_initialize_data():
        logger.debug("数据库已存在数据，跳过预加载")
        return
    await _load_preset_mcp_config(cfg.preset_mcp_config)
    await _load_preset_agent_config(cfg.preset_running_config)
    logger.debug("数据库预加载完成")


async def initialize_db_tables():
    from core.client.db import get_global_db
    db = await get_global_db()
    async with db._engine.begin() as conn:
        import models
        await conn.run_sync(models.Base.metadata.create_all)
    logger.debug("数据库自动建表完成")


async def close_tool_manager():
    """关闭工具管理器"""
    set_tool_manager(None)


async def validate_and_disable_mcp_servers():
    """验证数据库中的 MCP 服务器配置并注册到 ToolManager；清理不可用项。

    - 对每个保存的 MCP 服务器尝试注册；
    - 若注册抛出异常或失败，则从数据库中删除该服务器；
    - 若之前有部分注册的工具，尝试从 ToolManager 中移除。
    """
    import models

    mcp_dao = models.MCPServerDao()
    servers = await mcp_dao.get_list()
    removed_count = 0
    registered_count = 0
    tm = ToolManager.get_instance()
    for srv in servers:
        if srv.config.get("disabled", True):
            logger.info(f"MCP server {srv.name} 已禁用，跳过验证")
            continue
        logger.info(f"开始刷新MCP server: {srv.name}")
        server_config = srv.config
        success = await tm.register_mcp_server(srv.name, srv.config)
        if success:
            logger.info(f"MCP server {srv.name} 刷新成功")
            server_config["disabled"] = False
            await mcp_dao.save_mcp_server(name=srv.name, config=server_config)
            registered_count += 1
        else:
            logger.warning(f"MCP server {srv.name} 刷新失败，将其设置为禁用状态")
            server_config["disabled"] = True
            await mcp_dao.save_mcp_server(name=srv.name, config=server_config)
            removed_count += 1
    logger.info(
        f"MCP 验证完成：成功 {registered_count} 个，禁用 {removed_count} 个不可用服务器"
    )
