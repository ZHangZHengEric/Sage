from common.core.config import StartupConfig
from common.services.runtime_service import (
    cleanup_server_runtime,
    initialize_server_runtime,
    post_initialize_server_runtime_task,
)


async def initialize_system(cfg: StartupConfig):
    await initialize_server_runtime(cfg)


def post_initialize_task():
    return post_initialize_server_runtime_task()


async def cleanup_system():
    await cleanup_server_runtime()
