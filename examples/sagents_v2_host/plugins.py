"""A standalone third-party plugin: no imports from built-in implementations."""

import math

from pydantic import BaseModel, ConfigDict, Field

from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)


class EstimatorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bytes_per_token: float = Field(default=4.0, gt=0)


class ByteEstimator:
    """Example heuristic, not a vendor tokenizer or a production recommendation."""

    estimator_id = "example-byte-estimator"

    def __init__(self, *, bytes_per_token=4.0):
        self.bytes_per_token = bytes_per_token

    def estimate(self, messages):
        return sum(
            math.ceil(len(message.model_dump_json().encode()) / self.bytes_per_token)
            for message in messages
        )


def estimator_registration() -> ExtensionRegistration:
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="example.context.byte-estimator",
            version="2.0.0",
            name="Example byte estimator",
            provides=(
                CapabilityOffer(capability="context.token-estimator", api_version="2"),
            ),
            supported_scopes=frozenset({ExtensionScope.AGENT}),
            config_schema=EstimatorConfig.model_json_schema(),
        ),
        config_model=EstimatorConfig,
        factory=lambda context, dependencies: ByteEstimator(**context.config),
    )
