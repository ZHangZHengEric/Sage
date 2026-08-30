"""Explicit lightweight runtime composition for tests and examples."""

from sagents.v2.runtime.kernel import HarnessRuntime
from sagents.v2.runtime.session.ephemeral import EphemeralSessionStore


def ephemeral_runtime(**store_options) -> HarnessRuntime:
    """Create a Runtime backed by an explicitly selected in-memory store."""

    return HarnessRuntime(EphemeralSessionStore(**store_options))


__all__ = ["ephemeral_runtime"]
