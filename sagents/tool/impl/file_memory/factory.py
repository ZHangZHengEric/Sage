from __future__ import annotations

from typing import Any, Dict, Optional

from sagents.context.memory_backend_registry import MemoryBackendRegistry

from .index_backend import ScopedIndexFileMemoryBackend
from .noop_backend import NoopFileMemoryBackend

_FILE_MEMORY_REGISTRY = MemoryBackendRegistry(
    kind="file memory",
    env_var="SAGE_FILE_MEMORY_BACKEND",
    default_name="scoped_index",
    config_key="file_memory",
    legacy_key="file_memory_backend",
)
_FILE_MEMORY_REGISTRY.register(
    "scoped_index",
    lambda memory_tool: ScopedIndexFileMemoryBackend(memory_tool),
)
_FILE_MEMORY_REGISTRY.register(
    "noop",
    lambda memory_tool: NoopFileMemoryBackend(memory_tool),
)


def resolve_file_memory_backend_name(
    backend_name: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
) -> str:
    """Resolve the configured file-memory backend.

    Precedence:
    1. Explicit function argument
    2. Agent config (`memory_backends.file_memory` or legacy `file_memory_backend`)
    3. Environment variable
    4. Default backend
    """
    return _FILE_MEMORY_REGISTRY.resolve_name(
        backend_name=backend_name,
        agent_config=agent_config,
    )


def available_file_memory_backend_names() -> tuple[str, ...]:
    return _FILE_MEMORY_REGISTRY.supported_names()


def create_file_memory_backend(memory_tool, backend_name: Optional[str] = None, agent_config: Optional[Dict[str, Any]] = None):
    """Build the file-memory backend for the configured implementation."""
    return _FILE_MEMORY_REGISTRY.create(
        backend_name=backend_name,
        agent_config=agent_config,
        memory_tool=memory_tool,
    )
