import json
import os

from loguru import logger
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from streamlit import form
from sagents.skill import SkillManager, set_skill_manager
from sagents.tool.tool_manager import ToolManager, set_tool_manager

from .core.client.chat import close_chat_client, init_chat_client
from .core.client.db import close_db_client, init_db_client
from .core.client.embed import close_embed_client, init_embed_client
from .core.client.es import close_es_client, init_es_client
from .core.client.minio import close_minio_client, init_minio_client
from .core.config import StartupConfig
from .scheduler import add_doc_build_jobs, get_scheduler


async def initialize_clients(cfg: StartupConfig):
    try:
        minio_client = await init_minio_client(cfg)
        if minio_client is not None:
            logger.info("MinIO 客户端已初始化")
    except Exception as e:
        logger.error(f"MinIO 初始化失败: {e}")

    try:
        chat_client = await init_chat_client(
            api_key=cfg.default_llm_api_key,
            base_url=cfg.default_llm_api_base_url,
            model_name=cfg.default_llm_model_name,
            extra_configs=cfg.extra_llm_configs,
        )
        if chat_client is not None:
            logger.info("LLM Chat 客户端已初始化")
    except Exception as e:
        logger.error(f"LLM Chat 初始化失败: {e}")

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

    try:
        db_client = await init_db_client(cfg)
        if db_client is not None:
            logger.info(f"数据库客户端已初始化 ({cfg.db_type})")
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


async def _should_initialize_data(cfg: StartupConfig) -> bool:
    if cfg and cfg.db_type == "memory":
        return True
    from . import models

    mcp_server_dao = models.MCPServerDao()
    mcp_servers = await mcp_server_dao.get_list()
    agent_config_dao = models.AgentConfigDao()
    agent_configs = await agent_config_dao.get_list()
    return len(mcp_servers) == 0 and len(agent_configs) == 0


async def _load_preset_mcp_config(config_path: str):
    if not config_path or not os.path.exists(config_path):
        logger.warning(f"预设MCP配置文件不存在: {config_path} , 跳过加载预设MCP")
        return
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)
    mcp_servers = config_data.get("mcpServers", {})
    from . import models

    mcp_server_dao = models.MCPServerDao()
    for name, server_config in mcp_servers.items():
        await mcp_server_dao.save_mcp_server(name, server_config)
    logger.info(f"已加载 {len(mcp_servers)} 个MCP服务器配置")


async def _load_preset_agent_config(config_path: str):
    if not config_path or not os.path.exists(config_path):
        logger.warning(f"预设Agent配置文件不存在: {config_path} , 跳过加载预设Agent")
        return
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)
    from . import models

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


async def initialize_preset_data(cfg: StartupConfig):
    """初始化数据库预设数据"""
    if not await _should_initialize_data(cfg):
        logger.debug("数据库已存在数据，跳过预加载")
        return
    await _load_preset_mcp_config(cfg.preset_mcp_config)
    await _load_preset_agent_config(cfg.preset_running_config)
    logger.debug("数据库预加载完成")


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


async def initialize_observability(cfg: StartupConfig):

    # Check if Trace Provider is already initialized to prevent overwriting
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        logger.info("观测链路上报已初始化")
    else:
        try:
            from .services.trace import SageSpanExporter, TraceService

            resource = Resource(attributes={SERVICE_NAME: "sage-server"})
            provider = TracerProvider(resource=resource)

            # 1. Internal Exporter (for Workflow Panel) - Optional
            processor = BatchSpanProcessor(SageSpanExporter())
            provider.add_span_processor(processor)

            # 2. OTLP Exporter (for Jaeger/external)
            if cfg and cfg.trace_jaeger_endpoint:
                otlp_exporter = OTLPSpanExporter(endpoint=cfg.trace_jaeger_endpoint, insecure=True)
                otlp_processor = BatchSpanProcessor(otlp_exporter)
                provider.add_span_processor(otlp_processor)

            # Set global provider
            trace.set_tracer_provider(provider)

            # Start TraceService worker
            await TraceService.get_instance().start()
            logger.info("观测链路上报已初始化")
        except Exception as e:
            logger.error(f"观测链路上报初始化失败: {e}")


async def close_observability():
    # 1. Shutdown Trace Provider (Flush spans)
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        try:
            provider.shutdown()
            logger.info("观测链路上报已关闭")
        except Exception as e:
            logger.error(f"观测链路上报关闭失败: {e}")

    from .services.trace import TraceService

    # 2. Stop Trace Service (Drain queue to DB)
    try:
        await TraceService.get_instance().stop()
    finally:
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
            await sched.shutdown(wait=False)
        finally:
            logger.info("Scheduler 已关闭")

async def shutdown_clients():
    """关闭所有第三方客户端"""
    # 关闭第三方客户端
    try:
        await close_minio_client()
    finally:
        logger.info("MinIO客户端 已关闭")
    try:
        await close_chat_client()
    finally:
        logger.info("LLM Chat客户端 已关闭")
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


async def ensure_system_init():
    """Ensure system tables and default data exist."""
    from . import models
    from .services.user import _hash_password
    from .utils.id import gen_id
    from .core.client.db import get_global_db

    db = await get_global_db()
    async with db._engine.begin() as conn:
        from . import models

        await conn.run_sync(models.Base.metadata.create_all)
    logger.debug("数据库自动建表完成")

    # Check System Info
    sys_dao = models.SystemInfoDao()
    allow_reg = await sys_dao.get_by_key("allow_registration")
    if allow_reg is None:
        await sys_dao.set_value("allow_registration", "false")
        logger.info("初始化系统配置: 允许自注册=false")

    # Check Admin
    user_dao = models.UserDao()
    users = await user_dao.get_list(limit=1)
    if not users:
        admin_password = "admin"
        hashed = _hash_password(admin_password)
        admin_user = models.User(
            user_id=gen_id(),
            username="admin",
            password_hash=hashed,
            role="admin",
            email="admin@example.com"
        )
        await user_dao.save(admin_user)
        logger.info(f"初始化默认管理员用户. 用户名: admin, 密码: {admin_password}")
