from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from ..service.kdb import KdbService

scheduler: AsyncIOScheduler | None = None

def init_scheduler():
    """初始化 scheduler（单例）"""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    svc = KdbService()
    """注册所有定时任务"""
    scheduler.add_job(
        svc.build_waiting_doc,
        trigger="interval",
        seconds=5,
        id="build_waiting_doc",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=10,
    )
    scheduler.add_job(
        svc.build_failed_doc,
        trigger="interval",
        seconds=5,
        id="build_failed_doc",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=10,
    )
    scheduler.start()
    logger.info("定时任务 Scheduler 已启动")


async def shutdown_scheduler():
    global scheduler
    if scheduler:
        try:
            scheduler.shutdown(wait=False)
            logger.info("定时任务 Scheduler 已关闭")
        except Exception as e:
            logger.error(f"关闭 scheduler 失败: {e}")
