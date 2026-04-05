from common.core.config import StartupConfig
from common.services.runtime_service import cleanup_server_runtime, post_initialize_server_runtime_task


async def initialize_db_connection(cfg: StartupConfig):
    from common.services.runtime_service import initialize_db_connection as _initialize_db_connection

    return await _initialize_db_connection(cfg)


async def initialize_observability(cfg: StartupConfig):
    from common.services.runtime_service import initialize_observability as _initialize_observability

    return await _initialize_observability(cfg)


async def initialize_global_clients(cfg: StartupConfig):
    from common.services.runtime_service import initialize_global_clients as _initialize_global_clients

    return await _initialize_global_clients(cfg)


async def initialize_tool_manager():
    from common.services.runtime_service import initialize_tool_manager as _initialize_tool_manager

    return await _initialize_tool_manager()


async def initialize_skill_manager(cfg: StartupConfig):
    from common.services.runtime_service import initialize_skill_manager as _initialize_skill_manager

    return await _initialize_skill_manager(cfg)


async def initialize_session_manager(cfg: StartupConfig):
    from common.services.runtime_service import initialize_session_manager as _initialize_session_manager

    return await _initialize_session_manager(cfg)


async def initialize_scheduler(cfg: StartupConfig):
    from common.services.runtime_service import initialize_scheduler as _initialize_scheduler

    return await _initialize_scheduler(cfg)


async def initialize_system(cfg: StartupConfig):
    await initialize_db_connection(cfg)
    await initialize_observability(cfg)
    await initialize_global_clients(cfg)
    await _require_initialized("tool manager", initialize_tool_manager())
    await _require_initialized("skill manager", initialize_skill_manager(cfg))
    await _require_initialized("session manager", initialize_session_manager(cfg))
    await initialize_scheduler(cfg)


async def _require_initialized(name: str, initializer_result):
    result = await initializer_result
    if result is None:
        raise RuntimeError(f"{name} initialization failed")
    return result


def post_initialize_task():
    return post_initialize_server_runtime_task()


async def cleanup_system():
    await cleanup_server_runtime()
