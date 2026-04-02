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
    from common.services.knowledge_base import add_doc_build_jobs as _add_doc_build_jobs

    sched = get_scheduler()
    _add_doc_build_jobs(sched)
