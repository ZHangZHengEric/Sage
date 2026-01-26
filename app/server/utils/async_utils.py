import asyncio

from loguru import logger


def create_safe_task(coro, name: str):
    """
    创建一个安全的后台任务，捕获并记录异常，防止 'Task exception was never retrieved'
    """
    async def runner():
        try:
            await coro
        except asyncio.CancelledError:
            logger.info(f"后台任务被取消: {name}")
            raise
        except Exception as e:
            logger.exception(f"后台任务执行失败: {name}, error: {e}")

    return asyncio.create_task(runner(), name=name)
