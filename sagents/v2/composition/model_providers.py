"""Publish instrumented model providers through their normal plugin lifecycle."""

from dataclasses import replace
from typing import Any
from sagents.v2.runtime.extensions.contracts import CapabilityKey, ExtensionRegistration, ExtensionScopeContext, ProviderSet

from sagents.v2.model import RecordingModelProvider
from sagents.v2.runtime.extensions import ExtensionDependency, ExtensionRegistry
from sagents.v2.runtime.extensions.host import _start_extension
from sagents.v2.runtime.extensions.scope import StartedExtension


def observed_model_registry(
    registry: ExtensionRegistry, *, with_budget: bool
) -> ExtensionRegistry:
    """Keep model dependencies and the loop on the same observed/budgeted port.

    The raw plugin instance retains lifecycle ownership. Its start hook publishes
    the decorated port, so consumers resolve it exactly like every other provider.
    """
    result = ExtensionRegistry()
    for registration in registry.registrations():
        descriptor = registration.descriptor
        if any(offer.capability == "model.provider" for offer in descriptor.provides):
            dependencies = list(descriptor.dependencies)
            for capability in (
                "session.store",
                "observability.provider",
                *(("execution.model-budget",) if with_budget else ()),
            ):
                dependency = ExtensionDependency(capability=capability)
                if dependency not in dependencies:
                    dependencies.append(dependency)

            async def start(instance: Any, context: ExtensionScopeContext, providers: ProviderSet, original: ExtensionRegistration[Any] = registration) -> dict[CapabilityKey, Any]:
                values = await _start_extension(
                    StartedExtension(original, instance), context, providers
                )
                store = providers.require_unique("session.store")

                async def session_id(run_id):
                    return (await store.get_run(run_id)).session_id

                for key, value in values.items():
                    if key.capability != "model.provider":
                        continue
                    if with_budget:
                        value = providers.require_unique("execution.model-budget").wrap(
                            value
                        )
                    values[key] = RecordingModelProvider(
                        value,
                        sink=providers.require_unique("observability.provider").diagnostics,
                        trace_sink=providers.require_unique("observability.provider").traces,
                        log_sink=providers.require_unique("observability.provider").logs,
                        session_id_resolver=session_id,
                        provider_metadata={
                            "agent_id": (context.agent_configuration or {}).get(
                                "execution_agent_id", context.agent_id
                            )
                        },
                    )
                return values

            observed_registration = replace(
                registration,
                start=start,
                descriptor=descriptor.model_copy(
                    update={"dependencies": tuple(dependencies)}
                ),
            )
            result.register(observed_registration)
        else:
            result.register(registration)
    result.trust_builtins(
        item.descriptor.plugin_id
        for item in registry.registrations()
        if registry.is_trusted_builtin(item.descriptor.plugin_id)
    )
    return result
