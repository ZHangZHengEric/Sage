"""Typed registry for ModelProvider plugins."""

from sagents.v2.model.provider import ModelProvider
from sagents.v2.runtime.extensions import ExtensionRegistry, TypedExtensionRegistry


class ModelProviderRegistry(TypedExtensionRegistry[ModelProvider]):
    def __init__(self, registry: ExtensionRegistry | None = None) -> None:
        super().__init__(registry or ExtensionRegistry(), "model.provider")
