"""Official model budget and protocol provider registrations."""

from __future__ import annotations

from pydantic import Field

from sagents.v2.contracts.common import StrictModel
from sagents.v2.model import ModelConcurrencyBudget
from sagents.v2.model.protocols import (
    create_registered_model_provider,
    model_protocol_descriptors,
    model_protocol_implementation,
)
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.runtime.extensions.contracts import (
    CapabilityOffer,
    ExtensionDependency,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.runtime.extensions.registration import (
    implementation_identity,
    service_registration,
)
from sagents.v2.runtime.extensions.registry import ExtensionRegistry


class ModelBudgetConfig(StrictModel):
    limit: int = Field(default=8, gt=0)
    max_waiting: int = Field(default=128, ge=0)
    wait_timeout_seconds: float = Field(default=60, gt=0, allow_inf_nan=False)


def register_model_plugins(registry: ExtensionRegistry) -> None:
    for descriptor in model_protocol_descriptors():
        implementation = model_protocol_implementation(descriptor.protocol)
        registry.register(
            ExtensionRegistration(
                descriptor=ExtensionDescriptor(
                    **implementation_identity(implementation),
                    dependencies=(
                        ExtensionDependency(capability="credentials.provider"),
                        ExtensionDependency(
                            capability="model.client", name="default", optional=True
                        ),
                    ),
                    version=implementation.plugin_version,
                    provides=(
                        CapabilityOffer(
                            capability="model.provider",
                            api_version="2",
                            name=descriptor.protocol.value,
                        ),
                    ),
                    supported_scopes=frozenset(
                        {ExtensionScope.AGENT, ExtensionScope.RUN}
                    ),
                    config_schema={
                        "type": "object",
                        "properties": {
                            "route": {"type": "object"},
                            "provider_instance_id": {"type": "string"},
                        },
                        "required": ["route"],
                        "additionalProperties": False,
                    },
                    capabilities={"protocol": descriptor.protocol.value},
                    built_in=True,
                ),
                factory=_model_factory,
            )
        )

    registry.register(
        service_registration(
            ModelConcurrencyBudget.plugin_id,
            "execution.model-budget",
            lambda context, deps: ModelConcurrencyBudget(
                **ModelBudgetConfig.model_validate(context.config).model_dump()
            ),
            config_model=ModelBudgetConfig,
        )
    )


async def _model_factory(context, dependencies):
    from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
    from sagents.v2.runtime.credentials.contracts import CredentialRef

    route = ModelRoute.model_validate(context.config["route"])
    credential = None
    if route.credential is not None:
        credential = await dependencies.require_unique("credentials.provider").resolve(
            CredentialRef(credential_id=route.credential, purpose="model.inference"),
            RequestContext(
                actor=ActorRef(
                    principal_id="sagent-builder",
                    principal_type=PrincipalType.SERVICE,
                    tenant_id=context.tenant_id,
                )
            ),
        )
    return create_registered_model_provider(
        route,
        credential,
        client=dependencies.get_provider("model.client"),
        provider_instance_id=context.config.get("provider_instance_id"),
    )
