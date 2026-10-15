"""Context projection for a Session-scoped multi-Agent roster."""

from __future__ import annotations

from sagents.v2.prompt_i18n import prompt_text, run_prompt_language
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
        del run_id
        language = run_prompt_language(request.config.metadata)
        if not self.allow_delegation:
            return (
                ContextSegment(
                    segment_id="agent_delegation_boundary",
                    content=(
                        "<multi_agent_mode>\n"
                        f"{prompt_text('leaf', language)}\n"
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
                f"{member.description or prompt_text('no_description', language)} ({prompt_text('leaf_label', language)})"
                for member in members
            )
            or "- " + prompt_text("no_agents", language)
        )
        behavior = prompt_text("fibre" if self.mode == AgentMode.FIBRE else "team", language)
        return (
            ContextSegment(
                segment_id="agent_roster",
                content=f"<multi_agent_mode>\n{behavior}\n{roster}\n</multi_agent_mode>",
                stability=ContextStability.SEMI_STABLE,
                priority=-55,
            ),
        )


__all__ = ["AgentRosterContextProvider"]
