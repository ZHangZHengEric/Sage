"""Typed registry for MemoryProvider plugins."""

from sagents.v2.memory.contracts import MemoryProvider
from sagents.v2.runtime.extensions import ExtensionRegistry, TypedExtensionRegistry


class MemoryProviderRegistry(TypedExtensionRegistry[MemoryProvider]):
    def __init__(self, registry: ExtensionRegistry | None = None) -> None:
        super().__init__(registry or ExtensionRegistry(), "memory.provider")
