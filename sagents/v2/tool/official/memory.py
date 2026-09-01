"""Unified search over long-term Memory and derived Session history."""

from __future__ import annotations

from typing import Any

from sagents.v2.memory import MemoryQuery
from sagents.v2.tool import SideEffectLevel, ToolInvocation, tool
from sagents.v2.tool.official.runtime import OfficialToolRuntime


class MemoryTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    @tool(
        description="Search long-term Memory and omitted Session history.",
        side_effect_level=SideEffectLevel.READ,
    )
    async def search_memory(
        self,
        query: str,
        top_k: int = 5,
        session_id: str | None = None,
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("query cannot be empty")
        memory_service = getattr(self.runtime, "memory_service", None)
        session_memory_service = getattr(self.runtime, "session_memory_service", None)
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
        limit = max(1, min(top_k, 100))
        effective_session_id = session_id or (
            invocation.call.owner_session_id if invocation is not None else None
        )
        long_term_results = []
        if memory_service is not None:
            hits = await memory_service.recall(
                MemoryQuery(
                    scope=memory_service.scope(
                        tenant_id=tenant,
                        principal_id=principal,
                        agent_id=(
                            invocation.call.owner_agent_id
                            if invocation is not None
                            else None
                        ),
                        session_id=effective_session_id,
                    ),
                    text=query,
                    limit=limit,
                )
            )
            long_term_results = [
                {
                    "memory_type": "long_term",
                    "memory_id": hit.record.memory_id,
                    "content": hit.record.content,
                    "kind": hit.record.kind,
                    "score": hit.score,
                    "reason": hit.reason,
                    "source": hit.record.source,
                    "metadata": hit.record.metadata,
                }
                for hit in hits
            ]

        session_results = []
        if (
            session_memory_service is not None
            and invocation is not None
            and effective_session_id is not None
        ):
            session_hits = await session_memory_service.recall(
                run_id=invocation.call.owner_run_id,
                session_id=effective_session_id,
                text=query,
                limit=limit,
                tool_call_id=invocation.call.tool_call_id,
            )
            session_results = [
                {
                    "memory_type": "session",
                    "memory_id": hit.record.record_id,
                    "content": hit.record.content,
                    "kind": f"conversation.{hit.record.role}",
                    "score": hit.score,
                    "reason": hit.reason,
                    "source": hit.record.source,
                    "metadata": {
                        "session_id": hit.record.session_id,
                        "position": hit.record.position,
                    },
                }
                for hit in session_hits
            ]
        combined = sorted(
            (*long_term_results, *session_results),
            key=lambda value: float(value["score"]),
            reverse=True,
        )[:limit]
        return {
            "status": "success",
            "query": query,
            "results": combined,
            "long_term_results": long_term_results,
            "session_results": session_results,
        }
