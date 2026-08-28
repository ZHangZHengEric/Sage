"""Memory recall projected into ephemeral model context."""

from __future__ import annotations

from sagents.v2.context.contracts import ContextSegment, ContextStability
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.memory.contracts import MemoryQuery, MemoryScope
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
                scope=MemoryScope(
                    tenant_id=scope_data.get("tenant_id"),
                    principal_id=principal_id,
                    agent_id=(
                        command.agent_id
                        if scope_data.get("scope") in {"agent", "session"}
                        else None
                    ),
                    session_id=(
                        command.session_id
                        if scope_data.get("scope") == "session"
                        else None
                    ),
                ),
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
                content="Relevant long-term memory:\n" + "\n".join(lines),
                stability=ContextStability.VOLATILE,
                priority=-30,
                sensitive=True,
            ),
        )
