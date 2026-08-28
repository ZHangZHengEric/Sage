"""Typed registry for SessionStore plugins."""

from sagents.v2.runtime.extensions import ExtensionRegistry, TypedExtensionRegistry
from sagents.v2.runtime.session.contracts import SessionStore


class SessionStoreRegistry(TypedExtensionRegistry[SessionStore]):
    def __init__(self, registry: ExtensionRegistry | None = None) -> None:
        super().__init__(registry or ExtensionRegistry(), "session.store")
