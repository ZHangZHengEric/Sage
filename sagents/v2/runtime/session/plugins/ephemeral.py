"""In-memory SessionStore backend.

The transactional state machine lives in :mod:`sagents.v2.runtime.session.state`
so durable backends can reuse it without depending on this concrete adapter.
"""

from sagents.v2.runtime.session.state import (
    SESSION_AGGREGATE_FORMAT,
    SessionStoreCoordinator,
)


class EphemeralSessionStore:
    """Process-local composed facade over the transactional coordinator."""

    plugin_id = "sage.session.ephemeral"

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("persistence_can_fail", False)
        object.__setattr__(
            self, "_coordinator", SessionStoreCoordinator(*args, **kwargs)
        )

    def __getattr__(self, name):
        return getattr(self._coordinator, name)

    def __setattr__(self, name, value) -> None:
        if name == "_coordinator":
            object.__setattr__(self, name, value)
        else:
            setattr(self._coordinator, name, value)

    async def close(self) -> None:
        """Match durable stores' lifecycle without owning external resources."""


__all__ = [
    "EphemeralSessionStore",
    "SESSION_AGGREGATE_FORMAT",
]
