from __future__ import annotations

from typing import Any, Dict, Optional

from sagents.context.memory_backend_registry import MemoryBackendRegistry

from .bm25_backend import Bm25SessionMemoryBackend
from .noop_backend import NoopSessionMemoryBackend
from .session_memory_manager import SessionMemoryManager

_SESSION_MEMORY_REGISTRY = MemoryBackendRegistry(
    kind="session memory",
    env_var="SAGE_SESSION_MEMORY_BACKEND",
    default_name="bm25",
    config_key="session_history",
    legacy_key="session_memory_backend",
)
_SESSION_MEMORY_REGISTRY.register(
    "bm25",
    lambda: SessionMemoryManager(backend=Bm25SessionMemoryBackend()),
)
_SESSION_MEMORY_REGISTRY.register(
    "noop",
    lambda: SessionMemoryManager(backend=NoopSessionMemoryBackend()),
)


def resolve_session_memory_backend_name(
    backend_name: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Resolve the configured session-memory backend.

    Precedence:
    1. Explicit function argument
    2. Agent config (`memory_backends.session_history` or legacy `session_memory_backend`)
    3. Environment variable
    4. Default backend
    """
    return _SESSION_MEMORY_REGISTRY.resolve_name(
        backend_name=backend_name,
        agent_config=agent_config,
    )


def available_session_memory_backend_names() -> tuple[str, ...]:
    return _SESSION_MEMORY_REGISTRY.supported_names()


def create_session_memory_manager(
    backend_name: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
) -> SessionMemoryManager:
    """Build the session-memory manager for the configured backend."""
    return _SESSION_MEMORY_REGISTRY.create(
        backend_name=backend_name,
        agent_config=agent_config,
    )
