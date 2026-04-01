from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """获取 scheduler 实例，如果不存在则创建"""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    return scheduler


def add_doc_build_jobs():
    """注册文档构建任务"""
    from .services.kdb import KdbService

    sched = get_scheduler()
    svc = KdbService()

    sched.add_job(
        svc.build_waiting_doc,
        trigger="interval",
        seconds=5,
        id="build_waiting_doc",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=10,
    )
    sched.add_job(
        svc.build_failed_doc,
        trigger="interval",
        seconds=5,
        id="build_failed_doc",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=10,
    )
