"""Trusted, borrowed Run resources exposed through declared plugin dependencies."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, ClassVar

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.principals import RequestContext


@dataclass(frozen=True)
class RunExecutionEnvironment:
    """An accepted Run identity and its SDK-owned resources.

    Plugins may use these resources during their Run scope. They must not close
    borrowed sandboxes or issuers. No loop, driver or executor replacement port
    is exposed by this contract.
    """

    plugin_id: ClassVar[str] = "sage.execution.environment"
    name: ClassVar[str] = "Accepted Run environment"
    description: ClassVar[str] = "Authenticated identity and borrowed resources of the actual Run."

    run_id: str
    command: StartRun
    context: RequestContext
    sandbox: Any = None
    grant_issuer: Any = None
    workspace_root: str | None = None
    memory_service: Any = None
    session_memory_service: Any = None
    goal_state_service: Any = None


_active_environment = ContextVar[RunExecutionEnvironment | None]("sage_run_environment", default=None)


@contextmanager
def _bind_execution_environment(environment):
    token = _active_environment.set(environment)
    try:
        yield
    finally:
        _active_environment.reset(token)


def run_environment_registration():
    from sagents.v2.runtime.extensions.contracts import (
        CapabilityOffer, ExtensionDescriptor, ExtensionRegistration, ExtensionScope,
    )
    def create(context, dependencies):
        environment = _active_environment.get()
        if environment is None or environment.run_id != context.run_id:
            raise RuntimeError("execution.environment requires the actual SDK Run scope")
        if environment.context.actor.tenant_id != context.tenant_id:
            raise PermissionError("execution.environment belongs to a different tenant")
        return environment
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id=RunExecutionEnvironment.plugin_id, name="Accepted Run environment", version="2.0.0",
            description="Authenticated identity and borrowed resources of the actual Run.",
            provides=(CapabilityOffer(capability="execution.environment", api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.RUN}), default_scope=ExtensionScope.RUN,
            config_schema={"type": "object", "additionalProperties": False}, built_in=True,
        ), factory=create, ownership="borrowed",
    )
