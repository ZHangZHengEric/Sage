"""Standard registrations for application services used by every SDK host."""
from pydantic import Field
from sagents.v2.agent.policy import ApprovalStrategy

from sagents.v2.contracts.common import StrictModel
from .contracts import (
    CapabilityOffer, ExtensionDependency, ExtensionDescriptor, ExtensionRegistration,
    ExtensionScope,
)


class ModelBudgetConfig(StrictModel):
    limit: int = Field(default=8, gt=0)
    max_waiting: int = Field(default=128, ge=0)
    wait_timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)


class ToolPolicyConfig(StrictModel):
    approval_strategy: ApprovalStrategy = ApprovalStrategy.CONFIGURED


def core_registrations():
    from sagents.v2.agent.policy import SessionApprovalMemory, DefaultToolPolicy
    from sagents.v2.model import ModelConcurrencyBudget
    from sagents.v2.runtime.session import InMemoryDerivedStateStore

    def registration(plugin, capability, factory, *, dependencies=(), config_model=None, ownership="owned"):
        return ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id=plugin, name=capability, version="2.0.0",
                description=f"Standard {capability} implementation with declared dependencies and lifecycle.",
                provides=(CapabilityOffer(capability=capability, api_version="2"),),
                dependencies=tuple(ExtensionDependency(capability=key) for key in dependencies),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema=config_model.model_json_schema() if config_model else {
                    "type": "object", "additionalProperties": False,
                }, built_in=True,
            ), factory=factory, config_model=config_model, ownership=ownership,
        )

    def colocated(context, dependencies):
        store = dependencies.require("session.store")
        if not all(callable(getattr(store, method, None)) for method in (
            "get_derived_state", "put_derived_state", "delete_derived_state",
        )):
            raise TypeError("session.store lacks derived state; select an explicit derived-state.store plugin")
        return store

    return (
        registration("sage.agent.tool-policy.default", "agent.tool-policy",
                     lambda context, deps: DefaultToolPolicy(**ToolPolicyConfig.model_validate(context.config).model_dump()),
                     config_model=ToolPolicyConfig),
        registration("sage.derived-state.session", "derived-state.store", colocated,
                     dependencies=("session.store",), ownership="borrowed"),
        registration("sage.derived-state.ephemeral", "derived-state.store",
                     lambda context, deps: InMemoryDerivedStateStore()),
        registration("sage.agent.approval-memory.session", "agent.approval-memory",
                     lambda context, deps: SessionApprovalMemory(deps.require("derived-state.store")),
                     dependencies=("derived-state.store",)),
        registration("sage.model.concurrency-budget", "execution.model-budget",
                     lambda context, deps: ModelConcurrencyBudget(**ModelBudgetConfig.model_validate(context.config).model_dump()),
                     config_model=ModelBudgetConfig),
    )
