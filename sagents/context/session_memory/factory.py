from __future__ import annotations

import os
from typing import Optional

from .bm25_backend import Bm25SessionMemoryBackend
from .session_memory_manager import SessionMemoryManager


def create_session_memory_manager(backend_name: Optional[str] = None) -> SessionMemoryManager:
    """Build the session-memory manager for the configured backend."""
    resolved = (backend_name or os.environ.get("SAGE_SESSION_MEMORY_BACKEND", "bm25")).strip().lower()

    if resolved == "bm25":
        return SessionMemoryManager(backend=Bm25SessionMemoryBackend())

    raise ValueError(f"Unsupported session memory backend: {resolved}")
