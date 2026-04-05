from common.core.config import StartupConfig
from common.services import runtime_service

add_doc_build_jobs = runtime_service.add_doc_build_jobs
close_eml_client = runtime_service.close_eml_client
close_embed_client = runtime_service.close_embed_client
close_es_client = runtime_service.close_es_client
close_observability = runtime_service.close_observability
close_s3_client = runtime_service.close_s3_client
close_skill_manager = runtime_service.close_skill_manager
close_tool_manager = runtime_service.close_tool_manager
ensure_system_init = runtime_service.ensure_system_init
get_scheduler = runtime_service.get_scheduler
init_eml_client = runtime_service.init_eml_client
init_embed_client = runtime_service.init_embed_client
init_es_client = runtime_service.init_es_client
init_s3_client = runtime_service.init_s3_client
validate_and_disable_mcp_servers = runtime_service.validate_and_disable_mcp_servers


async def init_db_client(cfg: StartupConfig):
    from common.core.client.db import init_db_client as _init_db_client

    return await _init_db_client(cfg)


async def close_db_client():
    from common.core.client.db import close_db_client as _close_db_client

    return await _close_db_client()


async def initialize_db_connection(cfg: StartupConfig):
    from loguru import logger

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
    return await runtime_service.initialize_global_clients(cfg)


async def initialize_observability(cfg: StartupConfig):
    return await runtime_service.initialize_observability(cfg)


async def initialize_scheduler(cfg: StartupConfig):
    return await runtime_service.initialize_scheduler(cfg)


async def initialize_session_manager(cfg: StartupConfig):
    return await runtime_service.initialize_session_manager(cfg)


async def initialize_skill_manager(cfg: StartupConfig):
    return await runtime_service.initialize_skill_manager(cfg)


async def initialize_tool_manager():
    return await runtime_service.initialize_tool_manager()


async def initialize_server_runtime(cfg: StartupConfig):
    return await runtime_service.initialize_server_runtime(cfg)


def post_initialize_server_runtime_task():
    return runtime_service.post_initialize_server_runtime_task()


async def shutdown_scheduler():
    from loguru import logger

    sched = get_scheduler()
    if sched and sched.running:
        try:
            sched.shutdown(wait=False)
        finally:
            logger.info("Scheduler 已关闭")


async def shutdown_clients():
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
