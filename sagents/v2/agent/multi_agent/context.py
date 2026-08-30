"""Context projection for a Session-scoped multi-Agent roster."""

from __future__ import annotations

from sagents.v2.agent.multi_agent.contracts import AgentMode
from sagents.v2.agent.multi_agent.registry import AgentRegistry
from sagents.v2.context.contracts import ContextSegment, ContextStability


class AgentRosterContextProvider:
    def __init__(
        self,
        registry: AgentRegistry,
        mode: AgentMode,
        *,
        allow_delegation: bool = True,
    ) -> None:
        self.registry = registry
        self.mode = mode
        self.allow_delegation = allow_delegation

    async def segments(self, request, *, run_id: str):
        del request, run_id
        if not self.allow_delegation:
            return (
                ContextSegment(
                    segment_id="agent_delegation_boundary",
                    content=(
                        "<multi_agent_mode>\n"
                        "You are executing a delegated task as a leaf agent. "
                        "Do not create, spawn, or delegate to other agents; "
                        "complete the assigned task directly with your available "
                        "non-delegation tools.\n"
                        "</multi_agent_mode>"
                    ),
                    stability=ContextStability.STABLE,
                    priority=-55,
                ),
            )
        if self.mode not in {AgentMode.FIBRE, AgentMode.TEAM}:
            return ()
        members = await self.registry.list()
        roster = (
            "\n".join(
                f"- {member.agent_id}: {member.name} — "
                f"{member.description or 'no description'} (leaf execution)"
                for member in members
            )
            or "- No existing agents are registered."
        )
        behavior = (
            "Fibre may create Session-scoped agents and delegate work."
            if self.mode == AgentMode.FIBRE
            else "Team has a fixed roster and cannot create agents."
        )
        return (
            ContextSegment(
                segment_id="agent_roster",
                content=f"<multi_agent_mode>\n{behavior}\n{roster}\n</multi_agent_mode>",
                stability=ContextStability.SEMI_STABLE,
                priority=-55,
            ),
        )


__all__ = ["AgentRosterContextProvider"]
