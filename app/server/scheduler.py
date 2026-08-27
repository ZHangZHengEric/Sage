from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    """获取 scheduler 实例，如果不存在则创建"""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    return scheduler


def add_session_log_cleanup_job(sessions_root: str) -> None:
    from common.services.session_log_cleanup import cleanup_old_llm_request_logs

    sched = get_scheduler()
    sched.add_job(
        cleanup_old_llm_request_logs,
        trigger=CronTrigger(hour=0, minute=0),
        args=[sessions_root],
        kwargs={"retention_days": 7, "proactive_eval_retention_days": 3},
        id="cleanup_old_llm_request_logs",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
