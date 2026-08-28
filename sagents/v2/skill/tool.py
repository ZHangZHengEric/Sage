"""Decorator-backed ``load_skill`` implementation owned by the Skill domain."""

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
from sagents.v2.contracts.items import TextBlock


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
            "Load one enabled skill into this Run. Use the exact skill name "
            "listed in the available-skills context."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Exact name of the enabled skill to load.",
                }
            },
            "required": ["skill_name"],
            "additionalProperties": False,
        },
        strict=True,
        output_schema={
            "type": "object",
            "properties": {
                "skill_name": {"type": "string"},
                "workspace_path": {"type": "string"},
                "content_hash": {"type": "string"},
                "active_skills": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "skill_name",
                "workspace_path",
                "content_hash",
                "active_skills",
            ],
            "additionalProperties": False,
        },
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
    ) -> ToolExecutionResult:
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
        loaded = await self.loader.load(
            skill_name, run_id=invocation.call.owner_run_id
        )
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
