from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional


class MemoryBackendRegistry:
    """Shared registry for memory backend selection and construction."""

    def __init__(
        self,
        *,
        kind: str,
        env_var: str,
        default_name: str,
        config_key: str,
        legacy_key: str,
    ):
        self.kind = kind
        self.env_var = env_var
        self.default_name = default_name
        self.config_key = config_key
        self.legacy_key = legacy_key
        self._builders: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, builder: Callable[..., Any]) -> None:
        normalized = str(name).strip().lower()
        if not normalized:
            raise ValueError(f"{self.kind} backend name cannot be empty")
        self._builders[normalized] = builder

    def supported_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._builders.keys()))

    def resolve_name(
        self,
        backend_name: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        if backend_name:
            return backend_name.strip().lower()

        config = agent_config or {}
        memory_backends = config.get("memory_backends") or {}
        configured = (
            memory_backends.get(self.config_key)
            or config.get(self.legacy_key)
            or os.environ.get(self.env_var)
            or self.default_name
        )
        return str(configured).strip().lower()

    def create(
        self,
        *,
        backend_name: Optional[str] = None,
        agent_config: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        resolved = self.resolve_name(
            backend_name=backend_name,
            agent_config=agent_config,
        )
        builder = self._builders.get(resolved)
        if builder is None:
            supported = ", ".join(self.supported_names())
            raise ValueError(
                f"Unsupported {self.kind} backend: {resolved}. "
                f"Supported backends: {supported}"
            )
        return builder(**kwargs)
