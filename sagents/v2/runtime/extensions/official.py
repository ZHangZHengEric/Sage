"""Inventory of first-party plugins; domains own their registration details."""

from __future__ import annotations

from sagents.v2.agent.policy.registrations import register_policy_plugins
from sagents.v2.context.registrations import register_context_plugins
from sagents.v2.flow.registrations import register_flow_plugins
from sagents.v2.interfaces.protocols.registrations import register_protocol_plugins
from sagents.v2.memory.registrations import register_memory_plugins
from sagents.v2.model.registrations import register_model_plugins
from sagents.v2.package.registry.registrations import register_package_registry_plugins
from sagents.v2.runtime.artifact.registrations import register_artifact_plugins
from sagents.v2.runtime.credentials.registrations import register_credential_plugins
from sagents.v2.runtime.execution.environment import run_environment_registration
from sagents.v2.runtime.execution.jobs.registrations import register_job_plugins
from sagents.v2.runtime.execution.plugins.ephemeral_binding import (
    ephemeral_execution_binding_registration,
)
from sagents.v2.runtime.execution.plugins.local_binding.registration import (
    local_execution_binding_registration,
)
from sagents.v2.runtime.execution.sandbox.registrations import register_sandbox_plugins
from sagents.v2.runtime.execution.scheduler.registrations import (
    register_scheduler_plugins,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry
from sagents.v2.runtime.observability.registrations import (
    register_observability_plugins,
)
from sagents.v2.runtime.session.registrations import register_session_plugins
from sagents.v2.session_memory.registrations import register_session_memory_plugins
from sagents.v2.skill.registrations import register_skill_plugins
from sagents.v2.tool.registrations import register_tool_plugins
from sagents.v2.workspace.registrations import register_workspace_plugins


def builtin_extension_registry() -> ExtensionRegistry:
    """Return a fresh inventory backed by real factories."""
    registry = ExtensionRegistry()
    register_official_plugins(registry)
    return registry


def register_official_plugins(registry: ExtensionRegistry) -> None:
    """Aggregate domain registrations and mark the new built-ins as trusted."""
    existing = {value.descriptor.plugin_id for value in registry.registrations()}
    registry.register(local_execution_binding_registration())
    registry.register(ephemeral_execution_binding_registration())
    registry.register(run_environment_registration())
    register_policy_plugins(registry)
    register_session_plugins(registry)
    register_memory_plugins(registry)
    register_scheduler_plugins(registry)
    register_skill_plugins(registry)
    register_flow_plugins(registry)
    register_tool_plugins(registry)
    register_session_memory_plugins(registry)
    register_context_plugins(registry)
    register_job_plugins(registry)
    register_sandbox_plugins(registry)
    register_credential_plugins(registry)
    register_workspace_plugins(registry)
    register_artifact_plugins(registry)
    register_package_registry_plugins(registry)
    register_protocol_plugins(registry)
    register_model_plugins(registry)
    register_observability_plugins(registry)
    added = {
        value.descriptor.plugin_id for value in registry.registrations()
    } - existing
    registry.trust_builtins(added)
