"""Context projection for a Session-scoped multi-Agent roster."""

from __future__ import annotations

import json

from sagents.v2.prompt_i18n import prompt_text, run_prompt_language
from sagents.v2.agent.multi_agent.contracts import AgentMode
from sagents.v2.agent.multi_agent.registry import AgentRegistry
from sagents.v2.context.contracts import ContextSegment, ContextStability
from sagents.v2.runtime.session.contracts import SessionStore


class AgentRosterContextProvider:
    def __init__(
        self,
        registry: AgentRegistry,
        mode: AgentMode,
        *,
        allow_delegation: bool = True,
        session_store: SessionStore | None = None,
    ) -> None:
        self.registry = registry
        self.mode = mode
        self.allow_delegation = allow_delegation
        self.session_store = session_store

    async def segments(self, command, *, run_id: str | None = None):
        language = run_prompt_language(command.config.metadata)
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
        roster = "\n".join(
            f"- {self.registry.display_id(member.agent_id)}: {member.name} — "
            f"{member.description or prompt_text('no_description', language)} ({member.mode.value if member.is_declared_team else prompt_text('leaf_label', language)})"
            for member in members
        ) or "- " + prompt_text("no_agents", language)
        behavior = prompt_text(
            "fibre" if self.mode == AgentMode.FIBRE else "team", language
        )
        segments = (
            ContextSegment(
                segment_id="agent_roster",
                content=f"<multi_agent_mode>\n{behavior}\n{roster}\n</multi_agent_mode>",
                stability=ContextStability.SEMI_STABLE,
                priority=-55,
            ),
        )
        if self.session_store is None or run_id is None:
            return segments
        # Resolve through the admitted Run: StartRun.session_id can be absent
        # on the first turn. All relationships below are canonical store facts,
        # available as soon as child creation commits, before a tool returns.
        children = await self.session_store.managed_session_heads(run_id)
        rows = []
        for child in children:
            origin = child.first
            # Forks and Flow children are not delegated member conversations.
            if origin.invocation_mode != "delegation":
                continue
            latest = child.latest
            title = " ".join(
                str(latest.task_name or "").split()
            )[:20]
            rows.append(
                {
                    "agent_id": self.registry.display_id(origin.admitted_agent_id),
                    "session_id": origin.session_id,
                    "state": latest.state.value,
                    "task": title,
                }
            )
        if not rows:
            return segments
        return (
            *segments,
            ContextSegment(
                segment_id="managed_sessions",
                content=(
                    "<managed_sessions>\n"
                    f"{prompt_text('managed_sessions', language)}\n"
                    + json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
                    + "\n</managed_sessions>"
                ),
                stability=ContextStability.SEMI_STABLE,
                priority=-54,
            ),
        )


__all__ = ["AgentRosterContextProvider"]
