"""Process-local Scheduler plugin using the shared queue rules."""

from ._shared.queue import SchedulerQueue
from ._shared.queue import SchedulerQuotaGroup as SchedulerQuotaGroup
from ._shared.queue import SchedulerStateStore as SchedulerStateStore


class InMemoryScheduler(SchedulerQueue):
    plugin_id = "sage.scheduler.ephemeral"
    name = "In-memory scheduler"
    description = "Process-local scheduler without restart durability."
