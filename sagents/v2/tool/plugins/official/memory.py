"""Decorator-backed V2 Memory Tool implementation."""

from __future__ import annotations

from typing import Any

from sagents.v2.memory import MemoryQuery, MemoryScope
from sagents.v2.tool import SideEffectLevel, ToolInvocation, tool
from sagents.v2.tool.plugins.official.runtime import OfficialToolRuntime


class MemoryTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    @tool(description="Search the selected V2 Memory provider.", side_effect_level=SideEffectLevel.READ)
    async def search_memory(
        self,
        query: str,
        top_k: int = 5,
        session_id: str | None = None,
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("query cannot be empty")
        if self.runtime.memory_service is None:
            return {"status": "success", "query": query, "results": []}
        principal = (
            invocation.request_context.actor.principal_id
            if invocation is not None
            else "anonymous"
        )
        tenant = (
            invocation.request_context.actor.tenant_id
            if invocation is not None
            else None
        )
        hits = await self.runtime.memory_service.recall(
            MemoryQuery(
                scope=MemoryScope(
                    tenant_id=tenant,
                    principal_id=principal,
                    session_id=session_id,
                ),
                text=query,
                limit=max(1, min(top_k, 100)),
            )
        )
        return {
            "status": "success",
            "query": query,
            "results": [
                {
                    "memory_id": hit.record.memory_id,
                    "content": hit.record.content,
                    "kind": hit.record.kind,
                    "score": hit.score,
                    "reason": hit.reason,
                    "source": hit.record.source,
                    "metadata": hit.record.metadata,
                }
                for hit in hits
            ],
        }
