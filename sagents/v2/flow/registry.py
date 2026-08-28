"""Typed registry for Flow node plugins."""

from sagents.v2.flow.contracts import RunnableNode
from sagents.v2.runtime.extensions import ExtensionRegistry, TypedExtensionRegistry


class FlowNodeRegistry(TypedExtensionRegistry[RunnableNode]):
    def __init__(self, registry: ExtensionRegistry | None = None) -> None:
        super().__init__(registry or ExtensionRegistry(), "flow.node")
