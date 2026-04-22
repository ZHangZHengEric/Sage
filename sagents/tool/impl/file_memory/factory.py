from __future__ import annotations

import os
from typing import Optional

from .index_backend import ScopedIndexFileMemoryBackend
from .noop_backend import NoopFileMemoryBackend


def create_file_memory_backend(memory_tool, backend_name: Optional[str] = None):
    """Build the file-memory backend for the configured implementation."""
    resolved = (backend_name or os.environ.get("SAGE_FILE_MEMORY_BACKEND", "scoped_index")).strip().lower()

    if resolved == "scoped_index":
        return ScopedIndexFileMemoryBackend(memory_tool)
    if resolved == "noop":
        return NoopFileMemoryBackend(memory_tool)

    raise ValueError(f"Unsupported file memory backend: {resolved}")
