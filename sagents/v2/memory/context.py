"""Memory recall projected into ephemeral model context."""

from __future__ import annotations

from sagents.v2.memory.identity import command_memory_scope

from sagents.v2.prompt_i18n import prompt_text, run_prompt_language
from sagents.v2.context.contracts import ContextSegment, ContextStability
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.memory.contracts import MemoryQuery
from sagents.v2.memory.service import MemoryService


class MemoryContextSource:
    """Recall relevant Memory without mutating canonical Session history."""

    def __init__(self, service: MemoryService, *, default_limit: int = 8) -> None:
        self.service = service
        self.default_limit = default_limit

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        scope_data = dict(command.config.metadata.get("memory_scope") or {})
        principal_id = scope_data.get("principal_id")
        if not principal_id:
            return ()
        latest_user = next(
            (item for item in reversed(command.input) if item.role == "user"), None
        )
        if latest_user is None:
            return ()
        query_text = "\n".join(
            block.text for block in latest_user.content if isinstance(block, TextBlock)
        ).strip()
        if not query_text:
            return ()
        hits = await self.service.recall(
            MemoryQuery(
                scope=command_memory_scope(command),
                text=query_text,
                limit=int(scope_data.get("limit") or self.default_limit),
            )
        )
        if not hits:
            return ()
        lines = [f"- [{hit.record.memory_id}] {hit.record.content}" for hit in hits]
        return (
            ContextSegment(
                segment_id="memory_recall",
                content=prompt_text("memory_heading", run_prompt_language(command.config.metadata)) + "\n" + "\n".join(lines),
                stability=ContextStability.VOLATILE,
                priority=-30,
                sensitive=True,
            ),
        )
