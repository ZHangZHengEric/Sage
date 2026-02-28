
from loguru import logger
from sagents.skill import SkillManager, set_skill_manager
from sagents.tool.tool_manager import ToolManager, set_tool_manager

from .core.client.chat import close_chat_client, init_chat_client
from .core.client.db import close_db_client, init_db_client


async def initialize_db_connection():
    try:
        db_client = await init_db_client()
        if db_client is not None:
            logger.info("数据库客户端已初始化")
            from . import models
            async with db_client._engine.begin() as conn:
                from . import models
                await conn.run_sync(models.Base.metadata.create_all)
            logger.debug("数据库自动建表完成")
        try:
            # Load default provider settings first
            from .models.llm_provider import LLMProviderDao
            llm_dao = LLMProviderDao()
            default_provider = await llm_dao.get_default()
            if default_provider: 
                api_key = default_provider.api_keys[0] if default_provider.api_keys else None
                base_url = default_provider.base_url 
                model_name = default_provider.model
                chat_client = await init_chat_client(
                    api_key=api_key,
                    base_url=base_url,
                    model_name=model_name,
                )
                if chat_client is not None:
                    logger.info("LLM Chat 客户端已初始化")
        except Exception as e:
            logger.error(f"LLM Chat 初始化失败: {e}")

    except Exception as e:
        logger.error(f"数据库客户端初始化失败: {e}")



async def initialize_tool_manager():
    """初始化工具管理器"""
    try:
        from sagents.skill.skill_tool import SkillTool
        tool_manager_instance = ToolManager.get_instance()
        return tool_manager_instance
    except Exception as e:
        logger.error(f"工具管理器初始化失败: {e}")
        return None


async def close_tool_manager():
    """关闭工具管理器"""
    set_tool_manager(None)


async def initialize_skill_manager():
    """初始化技能管理器"""
    try:
        skill_manager_instance = SkillManager.get_instance()
        return skill_manager_instance
    except Exception as e:
        logger.error(f"技能管理器初始化失败: {e}")
        return None


async def close_skill_manager():
    """关闭技能管理器"""
    set_skill_manager(None)


async def validate_and_disable_mcp_servers():
    """验证数据库中的 MCP 服务器配置并注册到 ToolManager；清理不可用项。

    - 对每个保存的 MCP 服务器尝试注册；
    - 若注册抛出异常或失败，则从数据库中删除该服务器；
    - 若之前有部分注册的工具，尝试从 ToolManager 中移除。
    """
    from . import models

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
    logger.info(f"MCP 验证完成：成功 {registered_count} 个，禁用 {removed_count} 个不可用服务器")


async def shutdown_clients():
    """关闭所有第三方客户端"""
 
    try:
        await close_chat_client()
    finally:
        logger.info("LLM Chat客户端 已关闭")
    try:
        await close_db_client()
    finally:
        logger.info("数据库客户端 已关闭")

