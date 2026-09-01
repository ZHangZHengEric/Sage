"""Official Memory recall-query plugin: use the current user input verbatim."""

from __future__ import annotations


class DirectMemoryRecallQueryGenerator:
    """Use the current user input verbatim without another model request."""

    plugin_id = "sage.memory.recall-query.direct"

    async def generate(self, user_input: str, *, run_id: str) -> str:
        del run_id
        return user_input.strip()
