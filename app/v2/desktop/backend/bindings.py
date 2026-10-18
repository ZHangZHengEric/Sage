"""Desktop compatibility name for the SDK's local workspace binding provider."""

from sagents.v2.runtime.execution.local_binding import (
    DEFAULT_ALLOWED_ENV_NAMES as DEFAULT_ALLOWED_ENV_NAMES,
    DEFAULT_ALLOWED_EXECUTABLES as DEFAULT_ALLOWED_EXECUTABLES,
    LocalWorkspaceExecutionBindingProvider,
)


class DesktopExecutionBindingProvider(LocalWorkspaceExecutionBindingProvider):
    """Keep Desktop configuration/API stable while using SDK execution leases."""
