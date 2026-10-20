"""Process-local Job runtime plugin."""

from ._shared.runtime import JobRuntimeState
from ._shared.runtime import TERMINAL_JOB_STATES as TERMINAL_JOB_STATES


class InMemoryJobRuntime(JobRuntimeState):
    plugin_id = "sage.job.ephemeral"
    name = "In-memory Job runtime"
    description = "Process-local background Job runtime without restart durability."
