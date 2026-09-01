"""Memory recall-query port. Implementations live in plugins/recall_*.py."""

from __future__ import annotations

from typing import Protocol


class MemoryRecallQueryGenerator(Protocol):
    async def generate(self, user_input: str, *, run_id: str) -> str: ...
