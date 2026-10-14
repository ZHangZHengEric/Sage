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
from sagents.v2.model import ModelMessage
from sagents.v2.skill.tags import requested_skills


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
        # This is the discovery catalog: dropping entries makes enabled skills
        # unreachable by name. Keep full metadata; skill bodies load separately.
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
