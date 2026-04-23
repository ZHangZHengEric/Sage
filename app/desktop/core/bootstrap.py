
from loguru import logger
from sagents.skill import SkillManager, set_skill_manager
from sagents.tool.tool_manager import ToolManager, set_tool_manager
from sagents.session_runtime import initialize_global_session_manager

from common.core.client.chat import close_chat_client, init_chat_client
from common.core.client.db import close_db_client, init_db_client
from common.core.config import get_startup_config
from .migrations import migrate_desktop_default_user_id
from .user_context import DEFAULT_DESKTOP_USER_ID


async def initialize_db_connection():
    try:
        db_client = await init_db_client(get_startup_config())
        if db_client is not None:
            logger.info("数据库客户端已初始化")
            from common.models.base import Base
            from common.models.token_usage import TokenUsage  # noqa: F401
            async with db_client._engine.begin() as conn:
                # Create all tables
                await conn.run_sync(Base.metadata.create_all)
                # Check and update schema for existing tables
                from .db_schema import sync_database_schema
                await conn.run_sync(sync_database_schema)

            await migrate_desktop_default_user_id()
                
            logger.debug("数据库自动建表完成")
        try:
            # Load default provider settings first
            from common.models.llm_provider import LLMProviderDao
            llm_dao = LLMProviderDao()
            default_provider = await llm_dao.get_default(user_id=DEFAULT_DESKTOP_USER_ID)
            if not default_provider:
                providers = await llm_dao.get_list(user_id=DEFAULT_DESKTOP_USER_ID)
                default_provider = providers[0] if providers else None
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
        from .services.browser_tools import BrowserBridgeTool

        tool_manager_instance = ToolManager.get_instance()
        tool_manager_instance.register_tools_from_object(BrowserBridgeTool())
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
        
        # 添加到 skill manager（内置/同步至 ~/.sage/skills，与 cfg.skill_dir 一致）
        skill_manager_instance.add_skill_dir(str(sage_skills_dir))
        logger.info(f"已添加技能目录: {sage_skills_dir}")

        # 用户导入的技能目录（与 server 的 user_dir/<userId>/skills 一致，便于 list_skills 区分「我的」）
        cfg = get_startup_config()
        if cfg:
            user_skills_dir = Path(cfg.user_dir) / DEFAULT_DESKTOP_USER_ID / "skills"
            user_skills_dir.mkdir(parents=True, exist_ok=True)
            skill_manager_instance.add_skill_dir(str(user_skills_dir))
            logger.info(f"已添加用户技能目录: {user_skills_dir}")
        
        return skill_manager_instance
    except Exception as e:
        logger.error(f"技能管理器初始化失败: {e}")
        return None


def get_session_root_space() -> str:
    """获取会话根目录，与 service.py 保持一致"""
    from pathlib import Path
    import os
    
    if os.environ.get("SAGE_SESSIONS_PATH"):
        sessions_root = Path(os.environ.get("SAGE_SESSIONS_PATH"))
    else:
        user_home = Path.home()
        sage_home = user_home / ".sage"
        sessions_root = sage_home / "sessions"
    
    sessions_root.mkdir(parents=True, exist_ok=True)
    return str(sessions_root)


async def initialize_session_manager():
    """初始化全局 SessionManager"""
    try:
        from sagents.session_runtime import initialize_global_session_manager
        # 使用与 service.py 相同的路径配置
        session_root_space = get_session_root_space()
        session_manager = initialize_global_session_manager(
            session_root_space=session_root_space,
            enable_obs=True
        )
        logger.info(f"全局 SessionManager 已初始化，会话根目录: {session_root_space}")
        return session_manager
    except Exception as e:
        logger.error(f"全局 SessionManager 初始化失败: {e}")
        return None


async def initialize_observability():
    """初始化 OpenTelemetry 观测链路（desktop）"""
    cfg = get_startup_config()
    if not cfg:
        logger.warning("Startup config 不可用，跳过观测链路初始化")
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OpenTelemetry 未安装，跳过观测链路初始化")
        return None

    if isinstance(trace.get_tracer_provider(), TracerProvider):
        logger.info("观测链路上报已初始化")
        return None

    try:
        resource = Resource(attributes={SERVICE_NAME: "sage-desktop"})
        provider = TracerProvider(resource=resource)
        if cfg.trace_jaeger_endpoint:
            otlp_exporter = OTLPSpanExporter(endpoint=cfg.trace_jaeger_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        trace.set_tracer_provider(provider)
        logger.info("观测链路上报已初始化")
    except Exception as e:
        logger.error(f"观测链路上报初始化失败: {e}")


async def close_observability():
    """关闭 OpenTelemetry 观测链路（desktop）"""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError:
        logger.info("OpenTelemetry 未安装，跳过观测链路关闭")
        return

    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        try:
            provider.shutdown()
            logger.info("观测链路上报已关闭")
        except Exception as e:
            logger.error(f"观测链路上报关闭失败: {e}")

async def copy_default_skills():
    """复制默认 skills 到用户目录（每次启动都检查并同步）"""
    try:
        import shutil
        from pathlib import Path

        def has_valid_skills(path: Path | None) -> bool:
            if not path or not path.exists() or not path.is_dir():
                return False
            try:
                for skill_path in path.iterdir():
                    if not skill_path.is_dir():
                        continue
                    if any(
                        child.is_file() and child.name.lower() == "skill.md"
                        for child in skill_path.iterdir()
                    ):
                        return True
            except Exception as scan_error:
                logger.warning(f"检查默认 skills 目录失败 {path}: {scan_error}")
            return False
        
        # 用户 skills 目录
        user_home = Path.home()
        user_skills_dir = user_home / ".sage" / "skills"
        user_skills_dir.mkdir(parents=True, exist_ok=True)
        
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
                # 打包环境：使用 _MEIPASS 临时目录
                if hasattr(sys, '_MEIPASS'):
                    default_skills_dir = Path(sys._MEIPASS) / "skills"
                else:
                    # 备用方案：向上查找
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
        
        if not has_valid_skills(default_skills_dir):
            current_file = Path(__file__).resolve()
            fallback_candidates = [
                current_file.parent.parent.parent / "skills",
                current_file.parent.parent.parent.parent / "skills",
            ]
            fallback_dir = next((path for path in fallback_candidates if has_valid_skills(path)), None)
            if fallback_dir:
                logger.warning(
                    f"默认 skills 目录不可用或为空: {default_skills_dir}，回退到 {fallback_dir}"
                )
                default_skills_dir = fallback_dir

        if not has_valid_skills(default_skills_dir):
            logger.warning(f"默认 skills 目录不存在或不包含有效技能: {default_skills_dir}")
            return
        
        logger.info(f"同步内置 skills 从 {default_skills_dir} 到 {user_skills_dir}")
        
        # 复制每个 skill（只复制不存在的，已存在的跳过）
        copied_count = 0
        skipped_count = 0
        for skill_path in default_skills_dir.iterdir():
            if skill_path.is_dir():
                target_path = user_skills_dir / skill_path.name
                try:
                    if target_path.exists():
                        logger.debug(f"Skill {skill_path.name} 已存在，跳过")
                        skipped_count += 1
                        continue

                    shutil.copytree(skill_path, target_path)
                    logger.info(f"已复制 skill: {skill_path.name}")
                    copied_count += 1
                except Exception as e:
                    logger.error(f"复制 skill {skill_path.name} 失败: {e}")
        
        logger.info(f"内置 skills 同步完成，新增 {copied_count} 个，跳过 {skipped_count} 个已存在")
        
    except Exception as e:
        logger.error(f"同步内置 skills 失败: {e}")


async def copy_wiki_docs():
    """复制 wiki 文档到用户目录（每次启动都检查并同步）"""
    try:
        import shutil
        from pathlib import Path

        def has_markdown_docs(path: Path | None) -> bool:
            if not path or not path.exists() or not path.is_dir():
                return False
            try:
                return any(path.rglob("*.md"))
            except Exception as scan_error:
                logger.warning(f"检查 wiki 文档目录失败 {path}: {scan_error}")
                return False
        
        # 用户 sage 使用说明文档目录
        user_home = Path.home()
        user_docs_dir = user_home / ".sage" / "sage-usage-docs"
        user_docs_dir.mkdir(parents=True, exist_ok=True)
        
        # 获取打包的 wiki 文档目录
        wiki_docs_dir = None
        
        # 尝试从 tauri 资源目录获取
        try:
            import os
            import sys
            
            # 检查是否在 tauri 环境中
            if 'TAURI_RESOURCES_DIR' in os.environ:
                tauri_resources_dir = Path(os.environ['TAURI_RESOURCES_DIR'])
                resource_candidates = [
                    tauri_resources_dir / "wiki",
                    tauri_resources_dir / "docs",
                ]
                wiki_docs_dir = next(
                    (candidate for candidate in resource_candidates if candidate.exists()),
                    resource_candidates[0],
                )
            elif getattr(sys, 'frozen', False):
                # 打包环境：使用 _MEIPASS 临时目录
                if hasattr(sys, '_MEIPASS'):
                    meipass_dir = Path(sys._MEIPASS)
                    resource_candidates = [
                        meipass_dir / "wiki",
                        meipass_dir / "docs",
                    ]
                    wiki_docs_dir = next(
                        (candidate for candidate in resource_candidates if candidate.exists()),
                        resource_candidates[0],
                    )
                else:
                    # 备用方案：向上查找
                    current_file = Path(__file__).resolve()
                    wiki_docs_dir = current_file.parent.parent.parent.parent / "wiki"
                
                # 如果找不到，尝试相对于可执行文件的位置（PyInstaller 打包环境）
                if not wiki_docs_dir.exists():
                    wiki_docs_dir = Path(sys.executable).parent / "_internal" / "wiki"
            else:
                # 开发环境：使用相对路径
                current_file = Path(__file__).resolve()
                # wiki 在 app/wiki 目录下
                # bootstrap.py 在 app/desktop/core/bootstrap.py
                # 向上三级到 app/ 目录
                wiki_docs_dir = current_file.parent.parent.parent / "wiki"
        except Exception as e:
            logger.warning(f"无法确定 wiki 文档目录: {e}")
            return
        
        if not has_markdown_docs(wiki_docs_dir):
            current_file = Path(__file__).resolve()
            fallback_candidates = [
                current_file.parent.parent.parent / "wiki",
                current_file.parent.parent.parent.parent / "wiki",
            ]
            fallback_dir = next((path for path in fallback_candidates if has_markdown_docs(path)), None)
            if fallback_dir:
                logger.warning(
                    f"Wiki 文档目录不可用或为空: {wiki_docs_dir}，回退到 {fallback_dir}"
                )
                wiki_docs_dir = fallback_dir

        if not has_markdown_docs(wiki_docs_dir):
            logger.warning(f"Wiki 文档目录不存在或不包含 markdown: {wiki_docs_dir}")
            return
        
        logger.info(f"同步 wiki 文档从 {wiki_docs_dir} 到 {user_docs_dir}")
        
        # 复制所有 markdown 文件（覆盖已存在的）
        copied_count = 0
        updated_count = 0
        
        for md_file in wiki_docs_dir.rglob("*.md"):
            try:
                # 计算相对路径
                rel_path = md_file.relative_to(wiki_docs_dir)
                target_path = user_docs_dir / rel_path
                
                # 创建目标目录
                target_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 检查文件是否需要更新
                if target_path.exists():
                    # 比较文件修改时间或内容
                    import hashlib
                    
                    def file_hash(path):
                        with open(path, 'rb') as f:
                            return hashlib.md5(f.read()).hexdigest()
                    
                    if file_hash(md_file) != file_hash(target_path):
                        shutil.copy2(md_file, target_path)
                        logger.info(f"已更新 wiki 文档: {rel_path}")
                        updated_count += 1
                    else:
                        logger.debug(f"Wiki 文档未变化: {rel_path}")
                else:
                    shutil.copy2(md_file, target_path)
                    logger.info(f"已复制 wiki 文档: {rel_path}")
                    copied_count += 1
                    
            except Exception as e:
                logger.error(f"复制 wiki 文档 {md_file.name} 失败: {e}")
        
        logger.info(f"Wiki 文档同步完成，新增 {copied_count} 个，更新 {updated_count} 个")
        
    except Exception as e:
        logger.error(f"同步 wiki 文档失败: {e}")


async def close_skill_manager():
    """关闭技能管理器"""
    set_skill_manager(None)


async def initialize_im_service():
    """初始化 IM 服务 - 从数据库加载配置并启动"""
    try:
        from common.models.im_channel import IMChannelConfigDao
        import asyncio
        
        dao = IMChannelConfigDao()
        
        # 先打印所有用户的所有配置（调试用）
        all_users_configs = await dao.get_all_configs_all_users()
        logger.info(f"[IM] 数据库中所有配置 (共 {len(all_users_configs)} 条):")
        for config in all_users_configs:
            logger.info(f"[IM]   - user={config.sage_user_id}, provider={config.provider}, enabled={config.enabled}")
        
        all_configs = await dao.get_all_configs()
        
        logger.info(f"[IM] 当前用户配置: {all_configs}")
        
        # 检查是否有启用的 provider (legacy 配置)
        enabled_providers = []
        if all_configs:
            for provider_type, config in all_configs.items():
                is_enabled = config.get("enabled", False)
                logger.info(f"[IM] Provider {provider_type}: enabled={is_enabled}, config={config}")
                if is_enabled:
                    enabled_providers.append(provider_type)
        
        # Also check Agent-level configs
        has_agent_configs = False
        try:
            from mcp_servers.im_server.agent_config import list_all_agents, get_agent_im_config
            agents = list_all_agents()
            logger.info(f"[IM] Found {len(agents)} agents with IM config files")
            for agent_id in agents:
                try:
                    agent_config = get_agent_im_config(agent_id)
                    channels = agent_config.get_all_channels()
                    for provider, data in channels.items():
                        if data.get('enabled'):
                            has_agent_configs = True
                            logger.info(f"[IM] Agent {agent_id} has enabled {provider}")
                            if provider not in enabled_providers:
                                enabled_providers.append(provider)
                except Exception as e:
                    logger.warning(f"[IM] Failed to check agent {agent_id}: {e}")
        except Exception as e:
            logger.warning(f"[IM] Failed to check agent configs: {e}")
        
        if not enabled_providers and not has_agent_configs:
            logger.info(f"[IM] 没有启用的 IM provider（全局或Agent级），跳过服务启动")
            return
        
        logger.info(f"[IM] 正在启动 IM 服务，启用的 provider: {enabled_providers}")
        
        # 启动 IM 服务 - 使用延迟启动避免事件循环冲突
        from mcp_servers.im_server.im_server import initialize_im_server
        
        # 延迟启动 IM 服务，确保主事件循环已完全初始化
        async def delayed_im_start():
            try:
                # 等待 5 秒，确保 FastAPI 完全启动
                await asyncio.sleep(5)
                logger.info("[IM] 开始延迟启动 IM 服务...")
                await initialize_im_server()
                logger.info("[IM] IM 服务启动完成")
            except Exception as e:
                logger.error(f"[IM] IM 服务启动失败: {e}", exc_info=True)
        
        # 创建后台任务，不阻塞主流程
        asyncio.create_task(delayed_im_start())
        
        logger.info("[IM] IM 服务延迟启动任务已创建")
        
    except Exception as e:
        logger.error(f"[IM] IM 服务初始化失败: {e}", exc_info=True)


async def validate_and_disable_mcp_servers():
    """验证数据库中的 MCP 服务器配置并注册到 ToolManager；清理不可用项。

    - 对每个保存的 MCP 服务器尝试注册；
    - 若注册抛出异常或失败，则从数据库中删除该服务器；
    - 若之前有部分注册的工具，尝试从 ToolManager 中移除。
    """
    from common.models.mcp_server import MCPServerDao

    mcp_dao = MCPServerDao()
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
