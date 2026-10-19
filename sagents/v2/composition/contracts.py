"""Typed assembly results, independent of the Builder and Application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol



class ApplicationResource(Protocol):
    """Async lifecycle resource owned exclusively by the application root."""

    async def close(self) -> None: ...


@dataclass(frozen=True, order=True)
class ResolvedProviderBinding:
    """One inspectable capability binding with no secret configuration."""

    capability: str
    name: str
    api_version: str
    plugin_id: str | None
    scope: str
    source: str
    plugin_version: str = ""
    source_digest: str = ""


@dataclass(frozen=True)
class ResolvedApplicationPlan:
    """Frozen final composition identity exposed by an application root."""

    package_id: str
    manifest_hash: str
    entrypoint_agent_id: str
    providers: tuple[ResolvedProviderBinding, ...]
    dependencies: tuple[tuple[str, str], ...]
    composition_hash: str
