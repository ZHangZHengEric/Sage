"""Sage Voice's text-stream boundary for the vendored voice pipeline."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ToolActivity:
    call_id: str
    name: str
    running: bool
    target: str | None = None


class AgentTurn(Protocol):
    def __aiter__(self) -> AsyncIterator[str | ToolActivity]: ...
    async def aclose(self) -> None: ...


class VoiceAgent(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    def stream(self, prompt: str) -> AgentTurn: ...
