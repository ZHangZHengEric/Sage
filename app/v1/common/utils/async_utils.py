import asyncio

from loguru import logger


def create_safe_task(coro, name: str):
    """在后台安全执行协程，捕获并记录异常。

    - 统一 server / desktop 对后台任务的处理，防止 'Task exception was never retrieved'
    - 仅负责包装 asyncio.create_task，不做任何框架相关逻辑
    """

    async def runner():
        try:
            await coro
        except asyncio.CancelledError:
            logger.info(f"后台任务被取消: {name}")
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(f"后台任务执行失败: {name}, error: {e}")

    return asyncio.create_task(runner(), name=name)
