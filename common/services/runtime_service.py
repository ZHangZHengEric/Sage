import asyncio
import os
import importlib
import pkgutil

from common.core.config import StartupConfig


async def _require_initialized(name: str, initializer_result):
    result = await initializer_result
    if result is None:
        raise RuntimeError(f"{name} initialization failed")
    return result


async def ensure_system_init(cfg: StartupConfig):
    import_shared_model_modules()
    from common.core.client.db import get_global_db, sync_database_schema
    from common.models.base import Base
    from common.models.llm_provider import LLMProvider, LLMProviderDao
    from common.models.system import SystemInfoDao
    from common.models.user import User, UserDao
    from common.services.oauth.helpers import hash_password
    from common.services.oauth.provider import sync_oauth2_clients
    from common.utils.id import gen_id
    from loguru import logger

    db = await get_global_db()
    async with db._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(sync_database_schema, Base)
    logger.debug("数据库自动建表完成")

    sys_dao = SystemInfoDao()
    allow_reg = await sys_dao.get_by_key("allow_registration")
    if allow_reg is None:
        await sys_dao.set_value("allow_registration", "false")
        logger.info("初始化系统配置: 允许自注册=false")

    user_dao = UserDao()
    users = await user_dao.get_list(limit=1)
    if not users:
        username = (getattr(cfg, "bootstrap_admin_username", "") or "").strip()
        password = (getattr(cfg, "bootstrap_admin_password", "") or "").strip()
        if not username or not password:
            logger.warning("未配置 bootstrap admin 凭据，跳过默认管理员初始化")
        else:
            admin_user = User(
                user_id=gen_id(),
                username=username,
                password_hash=hash_password(password),
                role="admin",
                email="admin@example.com",
            )
            await user_dao.save(admin_user)
            logger.info(f"初始化默认管理员用户. 用户名: {username}, 密码: ***")

    await sync_oauth2_clients()
    logger.debug("OAuth2 Clients 配置同步完成")

    dao = LLMProviderDao()
    default_provider = await dao.get_default()
    if not cfg.default_llm_api_key or not cfg.default_llm_api_base_url:
        logger.warning(
            "Environment variables for default LLM provider missing. Skipping default provider creation."
        )
        return
    api_key = cfg.default_llm_api_key.strip()
    if not api_key:
        logger.warning(
            "Default LLM API key is empty after trimming. Skipping default provider creation."
        )
        return

    model = cfg.default_llm_model_name or "gpt-4o"
    base_url = cfg.default_llm_api_base_url or "https://api.openai.com/v1"
    max_tokens = cfg.default_llm_max_tokens or 4096
    temperature = cfg.default_llm_temperature or 0.7
    max_model_len = cfg.default_llm_max_model_len or 54000
    top_p = cfg.default_llm_top_p or 0.9
    presence_penalty = cfg.default_llm_presence_penalty or 0.0

    if not default_provider:
        import uuid

        provider = LLMProvider(
            id=str(uuid.uuid4()),
            name="Default LLM Provider",
            base_url=base_url,
            api_keys=[api_key],
            model=model,
            is_default=True,
            user_id="",
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            presence_penalty=presence_penalty,
            max_model_len=max_model_len,
        )
        await dao.save(provider)
        logger.debug("Initialized default LLM Provider from environment variables.")
    else:
        default_provider.base_url = base_url
        default_provider.api_keys = [api_key]
        default_provider.model = model
        default_provider.max_tokens = max_tokens
        default_provider.temperature = temperature
        default_provider.top_p = top_p
        default_provider.presence_penalty = presence_penalty
        default_provider.max_model_len = max_model_len
        await dao.save(default_provider)
        logger.debug("Default LLM Provider updated.")


def import_shared_model_modules() -> None:
    import common.models

    for module_info in pkgutil.iter_modules(common.models.__path__):
        name = module_info.name
        if name.startswith("_") or name == "base":
            continue
        importlib.import_module(f"common.models.{name}")


async def initialize_db_connection(cfg: StartupConfig):
    from common.core.client.db import init_db_client
    from loguru import logger

    db_client = await init_db_client(cfg)
    if db_client is None:
        raise RuntimeError("数据库客户端初始化失败: init_db_client returned None")
    logger.info(f"数据库客户端已初始化 ({cfg.db_type})")
    await ensure_system_init(cfg)
    return db_client


async def initialize_tool_manager():
    from loguru import logger
    from sagents.skill.skill_tool import SkillTool  # noqa: F401
    from sagents.tool.tool_manager import ToolManager

    try:
        return ToolManager.get_instance()
    except Exception as e:
        logger.error(f"工具管理器初始化失败: {e}")
        raise RuntimeError("tool manager initialization failed") from e


async def close_tool_manager():
    from sagents.tool.tool_manager import set_tool_manager

    set_tool_manager(None)


async def initialize_skill_manager(cfg: StartupConfig):
    from loguru import logger
    from sagents.skill import SkillManager

    try:
        skill_manager_instance = SkillManager.get_instance()
        if os.path.exists(cfg.skill_dir):
            skill_manager_instance.add_skill_dir(cfg.skill_dir)
            logger.info(f"系统技能目录已注册: {cfg.skill_dir}")
        return skill_manager_instance
    except Exception as e:
        logger.error(f"技能管理器初始化失败: {e}")
        raise RuntimeError("skill manager initialization failed") from e


async def close_skill_manager():
    from sagents.skill import set_skill_manager

    set_skill_manager(None)


async def initialize_session_manager(cfg: StartupConfig):
    from loguru import logger
    from sagents.session_runtime import initialize_global_session_manager

    try:
        session_manager = initialize_global_session_manager(
            session_root_space=cfg.session_dir,
            enable_obs=cfg.trace_jaeger_endpoint is not None,
        )
        logger.info(f"全局 SessionManager 已初始化，会话根目录: {cfg.session_dir}")
        return session_manager
    except Exception as e:
        logger.error(f"全局 SessionManager 初始化失败: {e}")
        raise RuntimeError("session manager initialization failed") from e


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
    from app.server.scheduler import get_scheduler as _get_scheduler

    return _get_scheduler()


def add_doc_build_jobs():
    from app.server.scheduler import add_doc_build_jobs as _add_doc_build_jobs

    return _add_doc_build_jobs()


async def initialize_global_clients(cfg: StartupConfig):
    from loguru import logger

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

        embed_client = await init_embed_client(
            api_key=api_key,
            base_url=base_url,
            model_name=model,
            dims=dims,
        )
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


async def validate_and_disable_mcp_servers():
    from common.models.mcp_server import MCPServerDao
    from loguru import logger
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
    from loguru import logger

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
    else:
        try:
            resource = Resource(attributes={SERVICE_NAME: "sage-server"})
            provider = TracerProvider(resource=resource)

            if cfg and cfg.trace_jaeger_endpoint:
                otlp_exporter = OTLPSpanExporter(endpoint=cfg.trace_jaeger_endpoint, insecure=True)
                otlp_processor = BatchSpanProcessor(otlp_exporter)
                provider.add_span_processor(otlp_processor)

            trace.set_tracer_provider(provider)
            logger.info("观测链路上报已初始化")
        except Exception as e:
            logger.error(f"观测链路上报初始化失败: {e}")


async def close_observability():
    from loguru import logger

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

    logger.info("观测链路上报服务已关闭")


async def initialize_scheduler(cfg: StartupConfig):
    from loguru import logger

    if cfg and cfg.es_url:
        try:
            add_doc_build_jobs()
        except Exception:
            logger.error("文档构建任务初始化失败")
            raise
    else:
        logger.info("未配置 Elasticsearch (es_url)，跳过文档构建任务")

    sched = get_scheduler()
    if sched and sched.get_jobs():
        if not sched.running:
            sched.start()
            logger.info("Scheduler 已启动")
    else:
        logger.info("Scheduler 无任务，跳过启动")


async def shutdown_scheduler():
    from loguru import logger

    sched = get_scheduler()
    if sched and sched.running:
        try:
            sched.shutdown(wait=False)
        finally:
            logger.info("Scheduler 已关闭")


async def shutdown_clients():
    from common.core.client.db import close_db_client
    from loguru import logger

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


async def initialize_cli_runtime(cfg: StartupConfig):
    from loguru import logger

    logger.info("Sage CLI 开始初始化")
    await _require_initialized("db connection", initialize_db_connection(cfg))
    previous_disable_builtin_mcp = os.environ.get("SAGE_DISABLE_BUILTIN_MCP_AUTO_DISCOVERY")
    os.environ["SAGE_DISABLE_BUILTIN_MCP_AUTO_DISCOVERY"] = "1"
    try:
        await _require_initialized("tool manager", initialize_tool_manager())
    finally:
        if previous_disable_builtin_mcp is None:
            os.environ.pop("SAGE_DISABLE_BUILTIN_MCP_AUTO_DISCOVERY", None)
        else:
            os.environ["SAGE_DISABLE_BUILTIN_MCP_AUTO_DISCOVERY"] = previous_disable_builtin_mcp
    await _require_initialized("skill manager", initialize_skill_manager(cfg))
    await _require_initialized("session manager", initialize_session_manager(cfg))
    logger.info("Sage CLI 初始化完成")


async def cleanup_cli_runtime():
    from common.core.client.db import close_db_client
    from loguru import logger

    logger.info("Sage CLI 正在清理资源...")
    try:
        await close_skill_manager()
    finally:
        logger.info("Sage CLI 技能管理器 已关闭")
    try:
        await close_tool_manager()
    finally:
        logger.info("Sage CLI 工具管理器 已关闭")
    try:
        await close_db_client()
    finally:
        logger.info("Sage CLI 数据库客户端 已关闭")


async def initialize_server_runtime(cfg: StartupConfig):
    from loguru import logger

    logger.info("Sage开始初始化")
    await _require_initialized("db connection", initialize_db_connection(cfg))
    await initialize_observability(cfg)
    await initialize_global_clients(cfg)
    await _require_initialized("tool manager", initialize_tool_manager())
    await _require_initialized("skill manager", initialize_skill_manager(cfg))
    await _require_initialized("session manager", initialize_session_manager(cfg))
    await initialize_scheduler(cfg)
    logger.info("Sage初始化完成")


def post_initialize_server_runtime_task():
    from common.utils.async_utils import create_safe_task

    return create_safe_task(
        _post_initialize_server_runtime(),
        name="post_initialize",
    )


async def _post_initialize_server_runtime():
    await validate_and_disable_mcp_servers()
    await _start_task_scheduler()


async def _start_task_scheduler():
    from loguru import logger

    try:
        await asyncio.sleep(5)
        from mcp_servers.task_scheduler.task_scheduler_server import ensure_scheduler_started

        started = ensure_scheduler_started()
        logger.info(f"Sage：TaskScheduler {'已启动' if started else '已存在'}")
    except Exception as exc:
        logger.warning(f"Sage：TaskScheduler 启动失败: {exc}")


async def cleanup_server_runtime():
    from loguru import logger

    logger.info("Sage正在清理资源...")
    await shutdown_scheduler()
    await close_observability()
    await shutdown_clients()
    try:
        await close_skill_manager()
    finally:
        logger.info("Sage技能管理器 已关闭")
    try:
        await close_tool_manager()
    finally:
        logger.info("Sage工具管理器 已关闭")
