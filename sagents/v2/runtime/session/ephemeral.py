"""In-memory SessionStore backend.

The transactional state machine lives in :mod:`sagents.v2.runtime.session.state`
so durable backends can reuse it without depending on this concrete adapter.
"""

from sagents.v2.runtime.session.state import (
    SESSION_AGGREGATE_FORMAT,
    SessionStateStore,
)


class EphemeralSessionStore(SessionStateStore):
    """Process-local SessionStore with no durability hooks."""


__all__ = [
    "EphemeralSessionStore",
    "SESSION_AGGREGATE_FORMAT",
]
