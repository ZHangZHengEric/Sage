"""Decorator-backed Skill operations owned by the ``sage.tool.skill`` plugin."""

from __future__ import annotations

from sagents.v2.skill.provider import SkillLoader
from sagents.v2.tool import (
    CancelSemantics,
    IdempotencyStrategy,
    ResumeStrategy,
    SideEffectLevel,
    ToolExecutionResult,
    ToolInvocation,
    tool,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import JsonBlock, TextBlock


class SkillLoadTool:
    """Implementation owner loaded by ``sage.tool.skill``.

    This class deliberately does not implement Tool Catalog or Executor ports.
    The Tool plugin discovers its decorated method and owns those runtime
    contracts, keeping domain behavior separate from plugin lifecycle.
    """

    def __init__(self, loader: SkillLoader, *, language: str | None = None) -> None:
        self.loader = loader
        self.language = (language or "en").lower()

    @tool(
        name="load_skill",
        description=(
            "Load one enabled skill into the active context. Recent session skills are "
            "restored within the skill context budget. Use the exact skill name "
            "from the available-skills context or search results."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Exact name of the enabled skill to load.",
                },
                "session_id": {"type": ["string", "null"]},
            },
            "required": ["skill_name", "session_id"],
            "additionalProperties": False,
        },
        strict=True,
        side_effect_level=SideEffectLevel.WRITE,
        idempotency_strategy=IdempotencyStrategy.FINGERPRINT,
        cancel_semantics=CancelSemantics.NOT_STARTED_ONLY,
        resume_strategy=ResumeStrategy.REPLAY_RESULT,
        required_scopes=("skill.load",),
    )
    async def execute(
        self,
        skill_name: str,
        invocation: ToolInvocation,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        del session_id
        if not skill_name:
            from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo

            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool.arguments_invalid",
                    category=ErrorCategory.VALIDATION,
                    message="skill_name is required",
                    safe_to_resume=True,
                )
            )
        loaded = await self.loader.load(skill_name, run_id=invocation.call.owner_run_id)
        active = await self.loader.loaded(run_id=invocation.call.owner_run_id)
        active_names = [value.descriptor.name for value in active]
        result = (
            f"技能 {loaded.descriptor.name} 已加载。当前启用：{', '.join(active_names)}。"
            if self.language.startswith("zh")
            else (
                f"Skill {loaded.descriptor.name} loaded. "
                f"Active skills: {', '.join(active_names)}."
            )
        )
        return ToolExecutionResult(
            tool_call_id=invocation.call.tool_call_id,
            operation_id=invocation.call.operation_id,
            content=(TextBlock(text=result),),
            metadata={
                "skill_name": loaded.descriptor.name,
                "workspace_path": loaded.workspace_path,
                "content_hash": loaded.content_hash,
                "active_skills": active_names,
            },
        )


class SkillSearchTool:
    def __init__(self, loader: SkillLoader) -> None:
        self.loader = loader

    @tool(
        name="search_skills",
        description="Find relevant authorized Skills. Pass a result's exact name to load_skill.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": 256},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                "session_id": {"type": ["string", "null"]},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        side_effect_level=SideEffectLevel.READ,
        plan_safe=True,
        required_scopes=("skill.load",),
    )
    async def execute(
        self, query: str, invocation: ToolInvocation, limit: int = 5,
        session_id: str | None = None,
    ) -> ToolExecutionResult:
        from sagents.v2.skill.search import has_search_terms

        del session_id

        values = ()
        if has_search_terms(query):
            values = await self.loader.catalog.search_skills(
                query, run_id=invocation.call.owner_run_id, limit=limit
            )
        return ToolExecutionResult(
            tool_call_id=invocation.call.tool_call_id,
            operation_id=invocation.call.operation_id,
            content=(JsonBlock(value=[
                {"name": value.name, "description": value.description} for value in values
            ]),),
        )


class SkillEditTool:
    """Opt-in editing operation. Requires its own tool grant and scope."""

    def __init__(self, loader: SkillLoader):
        self.loader = loader

    @tool(
        name="edit_skill",
        description=("Prepare the visible Skill working directory for editing. "
                     "With auto-sync, the next load_skill archives local edits and restores manager contents; "
                     "with fixed-copy, local edits remain. Published versions are never changed."),
        input_schema={"type": "object", "properties": {"skill_name": {"type": "string", "minLength": 1}},
                      "required": ["skill_name"], "additionalProperties": False},
        strict=True, side_effect_level=SideEffectLevel.WRITE,
        idempotency_strategy=IdempotencyStrategy.FINGERPRINT,
        cancel_semantics=CancelSemantics.NOT_STARTED_ONLY,
        resume_strategy=ResumeStrategy.REPLAY_RESULT,
        required_scopes=("skill.load", "skill.edit"),
    )
    async def execute(self, skill_name: str, invocation: ToolInvocation) -> ToolExecutionResult:
        loaded = await self.loader.begin_edit(skill_name, run_id=invocation.call.owner_run_id)
        return ToolExecutionResult(
            tool_call_id=invocation.call.tool_call_id, operation_id=invocation.call.operation_id,
            content=(TextBlock(text=f"Skill editing directory: {loaded.workspace_path}"),),
            metadata={"skill_name": skill_name, "workspace_path": loaded.workspace_path,
                      "base_hash": loaded.content_hash},
        )
