from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .kdb import KdbService


def add_doc_build_jobs(scheduler: AsyncIOScheduler) -> AsyncIOScheduler:
    """注册知识库文档构建相关的定时任务。"""
    svc = KdbService()

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
    return scheduler
