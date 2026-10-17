"""Standalone compactor example using exact characters and durable references."""

from pydantic import BaseModel, ConfigDict, Field
from sagents.v2.contracts.items import TextBlock
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)


class ReferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimum_characters: int = Field(default=4, gt=0)


class ReferenceCompactor:
    def __init__(self, *, minimum_characters=4):
        self.minimum_characters = minimum_characters

    async def compact(self, messages):
        projected = []
        for message in messages:
            reference = message.metadata.get("context_reference", {})
            uri = reference.get("uri") if isinstance(reference, dict) else None
            if (
                message.role == "tool"
                and uri
                and len(message.model_dump_json()) >= self.minimum_characters
            ):
                projected.append(
                    message.model_copy(
                        update={
                            "content": (TextBlock(text=f"[Stored tool result: {uri}]"),)
                        }
                    )
                )
            else:
                projected.append(message)
        return tuple(projected) if tuple(projected) != messages else None


def compactor_registration() -> ExtensionRegistration:
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="example.context.reference-compactor",
            version="2.0.0",
            name="Example reference compactor",
            provides=(
                CapabilityOffer(capability="context.unit-compactor", api_version="2"),
            ),
            supported_scopes=frozenset({ExtensionScope.AGENT}),
            config_schema=ReferenceConfig.model_json_schema(),
        ),
        config_model=ReferenceConfig,
        factory=lambda context, dependencies: ReferenceCompactor(**context.config),
    )
