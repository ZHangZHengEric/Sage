"""Trusted, borrowed Run resources exposed through declared plugin dependencies."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.principals import RequestContext


@dataclass(frozen=True)
class RunExecutionEnvironment:
    """An accepted Run identity and its SDK-owned resources.

    Plugins may use these resources during their Run scope. They must not close
    borrowed sandboxes or issuers. No loop, driver or executor replacement port
    is exposed by this contract.
    """
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
            plugin_id="sage.execution.environment", name="Accepted Run environment", version="2.0.0",
            description="Authenticated identity and borrowed resources of the actual Run.",
            provides=(CapabilityOffer(capability="execution.environment", api_version="2"),),
            supported_scopes=frozenset({ExtensionScope.RUN}), default_scope=ExtensionScope.RUN,
            config_schema={"type": "object", "additionalProperties": False}, built_in=True,
        ), factory=create, ownership="borrowed",
    )


def tool_runtime_registration():
    from sagents.v2.runtime.extensions.contracts import (
        CapabilityOffer, ExtensionDependency, ExtensionDescriptor, ExtensionRegistration, ExtensionScope,
    )
    from sagents.v2.tool.official import OfficialToolRuntime
    from sagents.v2.runtime.artifact.binding import bind_artifact_store
    def create(context, dependencies):
        environment = dependencies.require("execution.environment")
        if environment.sandbox is None or environment.grant_issuer is None:
            raise RuntimeError("official tools require a Run-owned execution.binding sandbox")
        runtime = OfficialToolRuntime(environment.sandbox, environment.grant_issuer,
                                      job_runtime=dependencies.require("execution.job-runtime"))
        runtime.artifact_store = bind_artifact_store(dependencies.require("artifact.store"), environment.run_id)
        runtime.memory_service = environment.memory_service
        runtime.session_memory_service = environment.session_memory_service
        runtime.goal_state_service = environment.goal_state_service
        runtime.tool_selection_policy = dependencies.require("tool.selection-policy")
        runtime.bind_job_runtime(dependencies.require("execution.job-runtime"))
        return runtime
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="sage.execution.tool-runtime", name="Run tool environment", version="2.0.0",
            description="Official tools bound to the accepted Run sandbox and shared services.",
            provides=(CapabilityOffer(capability="execution.tool-runtime", api_version="2"),),
            dependencies=tuple(ExtensionDependency(capability=capability) for capability in (
                "execution.environment", "execution.job-runtime", "artifact.store", "tool.selection-policy")),
            supported_scopes=frozenset({ExtensionScope.RUN}), default_scope=ExtensionScope.RUN,
            config_schema={"type": "object", "additionalProperties": False}, built_in=True,
        ), factory=create,
    )
