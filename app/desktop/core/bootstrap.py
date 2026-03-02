
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
        
        # 复制默认 skills 到用户目录
        await copy_default_skills()
        
        # 检查并添加 sage_home/skills 目录
        from pathlib import Path
        user_home = Path.home()
        sage_skills_dir = user_home / ".sage" / "skills"
        sage_skills_dir.mkdir(parents=True, exist_ok=True)
        
        # 添加到 skill manager
        skill_manager_instance.add_skill_dir(str(sage_skills_dir))
        logger.info(f"已添加技能目录: {sage_skills_dir}")
        
        return skill_manager_instance
    except Exception as e:
        logger.error(f"技能管理器初始化失败: {e}")
        return None


async def copy_default_skills():
    """复制默认 skills 到用户目录（如果是首次运行）"""
    try:
        import shutil
        from pathlib import Path
        
        # 用户 skills 目录
        user_home = Path.home()
        user_skills_dir = user_home / ".sage" / "skills"
        user_skills_dir.mkdir(parents=True, exist_ok=True)
        
        # 检查是否已初始化（通过检查标记文件）
        init_marker = user_skills_dir / ".defaults_copied"
        if init_marker.exists():
            logger.debug("默认 skills 已复制，跳过")
            return
        
        # 获取打包的默认 skills 目录
        # 在开发环境中使用相对路径，在生产环境中使用 tauri 资源路径
        default_skills_dir = None
        
        # 尝试从 tauri 资源目录获取
        try:
            import os
            import sys
            
            # 检查是否在 tauri 环境中
            if 'TAURI_RESOURCES_DIR' in os.environ:
                default_skills_dir = Path(os.environ['TAURI_RESOURCES_DIR']) / "skills"
            elif getattr(sys, 'frozen', False):
                # 打包环境：
                # build.sh 将 skills 复制到了 TARGET_MCP_DIR (通常是 _internal)
                # 而代码通常位于 _internal/app/desktop/core/bootstrap.py
                # 因此需要向上 4 级才能找到 _internal 根目录
                current_file = Path(__file__).resolve()
                default_skills_dir = current_file.parent.parent.parent.parent / "skills"
                
                # 如果找不到，尝试相对于可执行文件的位置
                if not default_skills_dir.exists():
                     default_skills_dir = Path(sys.executable).parent / "_internal" / "skills"
            else:
                # 开发环境：使用相对路径
                current_file = Path(__file__).resolve()
                default_skills_dir = current_file.parent.parent.parent / "skills"
        except Exception as e:
            logger.warning(f"无法确定默认 skills 目录: {e}")
            return
        
        if not default_skills_dir or not default_skills_dir.exists():
            logger.warning(f"默认 skills 目录不存在: {default_skills_dir}")
            return
        
        logger.info(f"复制默认 skills 从 {default_skills_dir} 到 {user_skills_dir}")
        
        # 复制每个 skill
        copied_count = 0
        for skill_path in default_skills_dir.iterdir():
            if skill_path.is_dir():
                target_path = user_skills_dir / skill_path.name
                try:
                    if target_path.exists():
                        logger.debug(f"Skill {skill_path.name} 已存在，准备覆盖")
                        if target_path.is_dir():
                            shutil.rmtree(target_path)
                        else:
                            target_path.unlink()

                    shutil.copytree(skill_path, target_path)
                    logger.info(f"已复制 skill: {skill_path.name}")
                    copied_count += 1
                except Exception as e:
                    logger.error(f"复制 skill {skill_path.name} 失败: {e}")
        
        # 创建标记文件
        init_marker.touch()
        logger.info(f"默认 skills 复制完成，共复制 {copied_count} 个")
        
    except Exception as e:
        logger.error(f"复制默认 skills 失败: {e}")


async def close_skill_manager():
    """关闭技能管理器"""
    set_skill_manager(None)


async def initialize_im_service():
    """初始化 IM 服务 - 从数据库加载配置并启动"""
    try:
        from .models import IMChannelConfigDao
        import asyncio
        
        # Desktop app uses fixed user_id
        DESKTOP_USER_ID = "desktop_user"
        
        dao = IMChannelConfigDao()
        config_record = await dao.get_by_user_id(DESKTOP_USER_ID)
        
        if not config_record:
            logger.info("未找到 IM 配置，跳过 IM 服务启动")
            return
        
        config_data = config_record.config
        service_config = config_data.get("service", {})
        
        # 检查是否启用服务
        if not service_config.get("running", False):
            logger.info("IM 服务未启用，跳过启动")
            return
        
        # 检查是否有启用的 provider
        providers = config_data.get("im_providers", {})
        enabled_providers = [k for k, v in providers.items() if v.get("enabled", False)]
        
        if not enabled_providers:
            logger.info("没有启用的 IM provider，跳过服务启动")
            return
        
        logger.info(f"正在启动 IM 服务，启用的 provider: {enabled_providers}")
        
        # 启动 IM 服务
        from mcp_servers.im_server.im_server import initialize_im_server
        asyncio.create_task(initialize_im_server())
        
        logger.info("IM 服务启动任务已创建")
        
    except Exception as e:
        logger.error(f"IM 服务初始化失败: {e}")


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

