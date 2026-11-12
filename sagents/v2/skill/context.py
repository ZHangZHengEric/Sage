"""SAgents V2 module for skill/context.py."""

from __future__ import annotations

from xml.sax.saxutils import escape

from sagents.v2.prompt_i18n import prompt_text, run_prompt_language
from sagents.v2.context import (
    ContextSegment,
    ContextStability,
)
from sagents.v2.skill.contracts import SkillCatalog
from sagents.v2.skill.provider import SkillLoader, visible_skill_descriptors
from sagents.v2.contracts.commands import StartRun
from sagents.v2.model import ModelMessage
from sagents.v2.skill.tags import requested_skills


class AvailableSkillsContextProvider:
    """Projects Level-1 metadata only; it never calls SkillSource.fetch()."""

    def __init__(
        self, catalog: SkillCatalog, *, default_visible_skills: tuple[str, ...] | None = None,
        search_enabled: bool = False,
    ) -> None:
        self.catalog = catalog
        self.default_visible_skills = default_visible_skills
        self.search_enabled = search_enabled

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        run_id = run_id or command.idempotency_key
        tools = command.config.enabled_tools
        search_enabled = self.search_enabled and (
            tools is None or "search_skills" in tools
        )
        if self.default_visible_skills is not None or search_enabled:
            values = await visible_skill_descriptors(
                self.catalog, dict.fromkeys(self.default_visible_skills or ()), run_id=run_id
            )
        else:
            values = await self.catalog.list_skills(run_id=run_id)
            if not values:
                return ()
        lines = ["<available_skills>"]
        for value in sorted(values, key=lambda item: item.name):
            lines.extend(
                (
                    "<skill>",
                    f"<skill_name>{escape(value.name)}</skill_name>",
                    f"<skill_description>{escape(value.description)}</skill_description>",
                    "</skill>",
                )
            )
        lines.extend(
            (
                "</available_skills>",
                "<skill_usage>",
                prompt_text("skill_search" if search_enabled else "skills", run_prompt_language(command.config.metadata)),
                "</skill_usage>",
            )
        )
        return (
            ContextSegment(
                segment_id="available_skills",
                content="\n".join(lines),
                stability=ContextStability.SEMI_STABLE,
                priority=-50,
            ),
        )


class ActiveSkillsContextProvider:
    """Activate user selectors and project loaded Skill instructions."""

    def __init__(self, loader: SkillLoader) -> None:
        self.loader = loader

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        ledger = tuple(
            ModelMessage(role=item.role, content=item.content, metadata=item.metadata)
            for item in command.input
        )
        return await self.segments_for_ledger(command, ledger, run_id=run_id)

    async def segments_for_ledger(
        self,
        command: StartRun,
        ledger: tuple[ModelMessage, ...],
        *,
        run_id: str | None = None,
    ) -> tuple[ContextSegment, ...]:
        await self.loader.activate_requested(
            requested_skills(ledger), run_id=run_id or command.idempotency_key
        )
        values = await self.loader.loaded(run_id=run_id or command.idempotency_key)
        return tuple(
            ContextSegment(
                segment_id=f"active_skill:{value.descriptor.name}",
                content=self.loader._context_content(value),
                stability=ContextStability.SEMI_STABLE,
                priority=index,
            )
            for index, value in enumerate(values)
        )
