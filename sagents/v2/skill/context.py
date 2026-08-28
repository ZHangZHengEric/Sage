"""SAgents V2 module for skill/context.py."""

from __future__ import annotations

from xml.sax.saxutils import escape

from sagents.v2.context import (
    ContextSegment,
    ContextStability,
)
from sagents.v2.skill.contracts import SkillCatalog
from sagents.v2.skill.provider import SkillLoader
from sagents.v2.contracts.commands import StartRun


class AvailableSkillsContextProvider:
    """Projects Level-1 metadata only; it never calls SkillSource.fetch()."""

    def __init__(self, catalog: SkillCatalog) -> None:
        self.catalog = catalog

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        values = await self.catalog.list_skills(
            run_id=run_id or command.idempotency_key
        )
        if not values:
            return ()
        lines = ["<available_skills>"]
        for value in sorted(values, key=lambda item: item.name):
            description = (
                value.description[:50] + "..."
                if len(value.description) > 50
                else value.description
            )
            lines.extend(
                (
                    "<skill>",
                    f"<skill_name>{escape(value.name)}</skill_name>",
                    f"<skill_description>{escape(description)}</skill_description>",
                    "</skill>",
                )
            )
        lines.extend(
            (
                "</available_skills>",
                "<skill_usage>",
                "Call load_skill with the exact skill name before following a Skill.",
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
    """Projects only skills that have already been copied by SkillLoader.load()."""

    def __init__(self, loader: SkillLoader) -> None:
        self.loader = loader

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        values = await self.loader.loaded(run_id=run_id or command.idempotency_key)
        return tuple(
            ContextSegment(
                segment_id=f"active_skill:{value.descriptor.name}",
                content=(
                    "<active_skill>\n"
                    f"<skill_name>{escape(value.descriptor.name)}</skill_name>\n"
                    f"<workspace>{escape(value.workspace_path)}</workspace>\n"
                    f"<skill_content>{escape(value.instructions)}</skill_content>\n"
                    "</active_skill>"
                ),
                stability=ContextStability.SEMI_STABLE,
                priority=index,
            )
            for index, value in enumerate(values)
        )
