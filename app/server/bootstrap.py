import json
import os

from loguru import logger

from common.core.config import StartupConfig
from .core.bootstrap_admin import format_bootstrap_admin_log, get_bootstrap_admin_spec


async def init_db_client(cfg: StartupConfig):
    from common.core.client.db import init_db_client as _init_db_client

    return await _init_db_client(cfg)


async def close_db_client():
    from common.core.client.db import close_db_client as _close_db_client

    return await _close_db_client()


async def init_eml_client(cfg: StartupConfig):
    from common.core.client.eml import init_eml_client as _init_eml_client

    return await _init_eml_client(cfg)


async def close_eml_client():
    from common.core.client.eml import close_eml_client as _close_eml_client

    return await _close_eml_client()


async def init_embed_client(*, api_key=None, base_url=None, model_name="", dims=1024):
    from common.core.client.embed import init_embed_client as _init_embed_client

    return await _init_embed_client(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        dims=dims,
    )


async def close_embed_client():
    from common.core.client.embed import close_embed_client as _close_embed_client

    return await _close_embed_client()


async def init_es_client(cfg: StartupConfig):
    from common.core.client.es import init_es_client as _init_es_client

    return await _init_es_client(cfg)


async def close_es_client():
    from common.core.client.es import close_es_client as _close_es_client

    return await _close_es_client()


async def init_s3_client(cfg: StartupConfig):
    from common.core.client.s3 import init_s3_client as _init_s3_client

    return await _init_s3_client(cfg)


async def close_s3_client():
    from common.core.client.s3 import close_s3_client as _close_s3_client

    return await _close_s3_client()


def get_scheduler():
    from .scheduler import get_scheduler as _get_scheduler

    return _get_scheduler()


def add_doc_build_jobs():
    from .scheduler import add_doc_build_jobs as _add_doc_build_jobs

    return _add_doc_build_jobs()


async def initialize_db_connection(cfg: StartupConfig):
    try:
        db_client = await init_db_client(cfg)
        if db_client is not None:
            logger.info(f"数据库客户端已初始化 ({cfg.db_type})")
            await ensure_system_init(cfg)
            return db_client
        raise RuntimeError("数据库客户端初始化失败: init_db_client returned None")
    except Exception as e:
        logger.error(f"数据库客户端初始化失败: {e}")
        raise


async def initialize_global_clients(cfg: StartupConfig):
    try:
        eml_client = await init_eml_client(cfg)
        if eml_client is not None:
            logger.info("邮件客户端已初始化")
    except Exception as e:
        logger.error(f"邮件客户端初始化失败: {e}")

    try:
        s3_client = await init_s3_client(cfg)
        if s3_client is not None:
            logger.info("RustFS 客户端已初始化")
    except Exception as e:
        logger.error(f"RustFS 初始化失败: {e}")
        
    try:
        api_key = cfg.embed_api_key or cfg.default_llm_api_key
        base_url = cfg.embed_base_url or cfg.default_llm_api_base_url
        model = cfg.embed_model or cfg.default_llm_model_name or "text-embedding-3-large"
        dims = int(cfg.embed_dims or 1024)

        embed_client = await init_embed_client(api_key=api_key, base_url=base_url, model_name=model, dims=dims)
        if embed_client is not None:
            logger.info("Embedding 客户端已初始化")
    except Exception as e:
        logger.error(f"Embedding 初始化失败: {e}")

    try:
        es_client = await init_es_client(cfg)
        if es_client is not None:
            logger.info("Elasticsearch 客户端已初始化")
    except Exception as e:
        logger.error(f"Elasticsearch 初始化失败: {e}")


async def initialize_tool_manager():
    """初始化工具管理器"""
    try:
        from sagents.skill.skill_tool import SkillTool
        from sagents.tool.tool_manager import ToolManager

        tool_manager_instance = ToolManager.get_instance()
        return tool_manager_instance
    except Exception as e:
        logger.error(f"工具管理器初始化失败: {e}")
        raise RuntimeError("tool manager initialization failed") from e


async def close_tool_manager():
    """关闭工具管理器"""
    from sagents.tool.tool_manager import set_tool_manager

    set_tool_manager(None)


async def initialize_skill_manager(cfg: StartupConfig):
    """初始化技能管理器

    技能目录结构:
    - skills/ - 系统技能
    - users/{user_id}/skills/ - 用户技能
    - agents/{user_id}/{agent_id}/skills/ - Agent 技能
    """
    try:
        from sagents.skill import SkillManager

        skill_manager_instance = SkillManager.get_instance()

        # 1. 注册系统技能目录 (skills/)
        if os.path.exists(cfg.skill_dir):
            skill_manager_instance.add_skill_dir(cfg.skill_dir)
            logger.info(f"系统技能目录已注册: {cfg.skill_dir}")

        # 2. 用户技能对话时，根据 user_id 注册用户技能目录 (users/{user_id}/skills/)
        # 3. Agent 技能对话时，根据 agent_id 注册 Agent 技能目录 (agents/{user_id}/{agent_id}/skills/)
        
        return skill_manager_instance
    except Exception as e:
        logger.error(f"技能管理器初始化失败: {e}")
        raise RuntimeError("skill manager initialization failed") from e


async def close_skill_manager():
    """关闭技能管理器"""
    from sagents.skill import set_skill_manager

    set_skill_manager(None)


async def initialize_session_manager(cfg: StartupConfig):
    """初始化全局 SessionManager"""
    try:
        from sagents.session_runtime import initialize_global_session_manager
        # 使用 session_dir 作为会话根目录
        session_manager = initialize_global_session_manager(
            session_root_space=cfg.session_dir,
            enable_obs=cfg.trace_jaeger_endpoint is not None
        )
        logger.info(f"全局 SessionManager 已初始化，会话根目录: {cfg.session_dir}")
        return session_manager
    except Exception as e:
        logger.error(f"全局 SessionManager 初始化失败: {e}")
        raise RuntimeError("session manager initialization failed") from e


async def validate_and_disable_mcp_servers():
    """验证数据库中的 MCP 服务器配置并注册到 ToolManager；清理不可用项。

    - 对每个保存的 MCP 服务器尝试注册；
    - 若注册抛出异常或失败，则从数据库中删除该服务器；
    - 若之前有部分注册的工具，尝试从 ToolManager 中移除。
    """
    from common.models.mcp_server import MCPServerDao
    from sagents.tool.tool_manager import ToolManager

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


async def initialize_observability(cfg: StartupConfig):
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OpenTelemetry 未安装，跳过观测链路初始化")
        return None

    # Check if Trace Provider is already initialized to prevent overwriting
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        logger.info("观测链路上报已初始化")
    else:
        try:
            resource = Resource(attributes={SERVICE_NAME: "sage-server"})
            provider = TracerProvider(resource=resource)

            # 2. OTLP Exporter (for Jaeger/external)
            if cfg and cfg.trace_jaeger_endpoint:
                otlp_exporter = OTLPSpanExporter(endpoint=cfg.trace_jaeger_endpoint, insecure=True)
                otlp_processor = BatchSpanProcessor(otlp_exporter)
                provider.add_span_processor(otlp_processor)

            # Set global provider
            trace.set_tracer_provider(provider)

            logger.info("观测链路上报已初始化")
        except Exception as e:
            logger.error(f"观测链路上报初始化失败: {e}")


async def close_observability():
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
    except ImportError:
        logger.info("OpenTelemetry 未安装，跳过观测链路关闭")
        return

    # 1. Shutdown Trace Provider (Flush spans)
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        try:
            provider.shutdown()
            logger.info("观测链路上报已关闭")
        except Exception as e:
            logger.error(f"观测链路上报关闭失败: {e}")

    logger.info("观测链路上报服务已关闭")


async def initialize_scheduler(cfg: StartupConfig):
    """初始化 scheduler（单例）"""
    # 3) 启动调度器（需在 DB 连接后）
    if cfg and cfg.es_url:
        try:
            add_doc_build_jobs()
        except Exception:
            logger.error("文档构建任务初始化失败")
            raise
    else:
        logger.info("未配置 Elasticsearch (es_url)，跳过文档构建任务")

    # 尝试启动调度器（如果有任务）
    """启动 scheduler"""
    sched = get_scheduler()
    if sched and sched.get_jobs():
        if not sched.running:
            sched.start()
            logger.info("Scheduler 已启动")
    else:
        logger.info("Scheduler 无任务，跳过启动")


async def shutdown_scheduler():
    """关闭 scheduler（单例）"""
    sched = get_scheduler()
    if sched and sched.running:
        try:
            sched.shutdown(wait=False)
        finally:
            logger.info("Scheduler 已关闭")

async def shutdown_clients():
    """关闭所有第三方客户端"""
    # 关闭第三方客户端
    try:
        await close_eml_client()
    finally:
        logger.info("邮件客户端 已关闭")
    try:
        await close_s3_client()
    finally:
        logger.info("RustFS客户端 已关闭")
    try:
        await close_embed_client()
    finally:
        logger.info("Embedding客户端 已关闭")
    try:
        await close_es_client()
    finally:
        logger.info("Elasticsearch客户端 已关闭")
    try:
        await close_db_client()
    finally:
        logger.info("数据库客户端 已关闭")


async def ensure_system_init(cfg: StartupConfig):
    """Ensure system tables and default data exist."""
    from common.models.base import Base
    from common.models.llm_provider import LLMProvider, LLMProviderDao
    from common.models.token_usage import TokenUsage  # noqa: F401
    from common.models.system import SystemInfoDao
    from common.models.user import User, UserDao
    from common.services.oauth.helpers import hash_password
    from common.services.oauth.provider import sync_oauth2_clients
    from common.utils.id import gen_id
    from common.core.client.db import get_global_db, sync_database_schema

    db = await get_global_db()
    async with db._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Sync schema: add missing columns to existing tables
        await conn.run_sync(sync_database_schema, Base)
    logger.debug("数据库自动建表完成")

    # Check System Info
    sys_dao = SystemInfoDao()
    allow_reg = await sys_dao.get_by_key("allow_registration")
    if allow_reg is None:
        await sys_dao.set_value("allow_registration", "false")
        logger.info("初始化系统配置: 允许自注册=false")

    # Check Admin
    user_dao = UserDao()
    users = await user_dao.get_list(limit=1)
    if not users:
        bootstrap_admin = get_bootstrap_admin_spec(cfg)
        if not bootstrap_admin:
            logger.warning("未配置 bootstrap admin 凭据，跳过默认管理员初始化")
        else:
            hashed = hash_password(bootstrap_admin.password)
            admin_user = User(
                user_id=gen_id(),
                username=bootstrap_admin.username,
                password_hash=hashed,
                role="admin",
                email="admin@example.com"
            )
            await user_dao.save(admin_user)
            logger.info(format_bootstrap_admin_log(bootstrap_admin))

    await sync_oauth2_clients()
    logger.debug("OAuth2 Clients 配置同步完成")

    dao = LLMProviderDao()
    default_provider = await dao.get_default()
    if not cfg.default_llm_api_key or not cfg.default_llm_api_base_url:
        logger.warning("Environment variables for default LLM provider missing. Skipping default provider creation.")
        return
    api_key = cfg.default_llm_api_key.strip()
    if not api_key:
        logger.warning("Default LLM API key is empty after trimming. Skipping default provider creation.")
        return
    # Models
    model = cfg.default_llm_model_name or "gpt-4o"
    base_url = cfg.default_llm_api_base_url or "https://api.openai.com/v1"
    max_tokens = cfg.default_llm_max_tokens
    temperature = cfg.default_llm_temperature or 0.7
    max_model_len = cfg.default_llm_max_model_len or 64000
    top_p = cfg.default_llm_top_p or 0.9
    presence_penalty = cfg.default_llm_presence_penalty or 0.0
    if not default_provider:
        import uuid
        provider_id = str(uuid.uuid4())
        provider = LLMProvider(
            id=provider_id, 
            name="Default LLM Provider", 
            base_url=base_url, 
            api_keys=[api_key], 
            model=model, 
            is_default=True,
            user_id="",
            temperature=temperature,
            top_p=top_p,
            presence_penalty=presence_penalty,
            max_model_len=max_model_len
        )
        if max_tokens is not None:
            provider.max_tokens = int(max_tokens)
        await dao.save(provider)
        logger.debug("Initialized default LLM Provider from environment variables.")
    else:
        logger.debug("Default LLM Provider already exists. need update.")
        default_provider.base_url = base_url
        default_provider.api_keys = [api_key]
        default_provider.model = model
        default_provider.max_tokens = int(max_tokens) if max_tokens is not None else None
        default_provider.temperature = temperature
        default_provider.top_p = top_p
        default_provider.presence_penalty = presence_penalty
        default_provider.max_model_len = max_model_len
            
        await dao.save(default_provider)
        logger.debug("Default LLM Provider updated.")
