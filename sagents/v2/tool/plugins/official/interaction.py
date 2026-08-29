"""Decorator-backed V2 questionnaire tools."""

from __future__ import annotations

from typing import Any, Literal

from sagents.v2.tool import SideEffectLevel, ToolInvocation, tool
from sagents.v2.tool.plugins.official.runtime import OfficialToolRuntime


class InteractionTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    @tool(description="Validate a markdown-style questionnaire payload.")
    async def questionnaire_async(
        self,
        questions: list[dict[str, Any]],
        title: str = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id
        normalized, errors = _validate_questions(questions, markdown_style=True)
        if errors:
            return {
                "success": False,
                "status": "error",
                "validation_passed": False,
                "errors": errors,
            }
        return {
            "success": True,
            "status": "questionnaire_ready",
            "validation_passed": True,
            "title": title.strip(),
            "question_count": len(normalized),
            "questions": normalized,
            "should_end": True,
        }

    @tool(
        description="Display a questionnaire and collect the user's answers.",
        side_effect_level=SideEffectLevel.WRITE,
    )
    async def questionnaire(
        self,
        title: str,
        questions: list[dict[str, Any]],
        questionnaire_id: str,
        session_id: str | None = None,
        wait_time: int = 300,
        questionnaire_kind: Literal[
            "general", "plan_information", "plan_confirmation"
        ] = "general",
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        del session_id
        normalized, errors = _validate_questions(questions, markdown_style=False)
        if errors:
            return {"success": False, "status": "error", "errors": errors}
        if self.runtime.questionnaire_presenter is None:
            return {
                "success": False,
                "status": "unavailable",
                "message": "the host did not configure a questionnaire presenter",
            }
        run_id = invocation.call.owner_run_id if invocation is not None else "unknown"
        return await self.runtime.questionnaire_presenter(
            title=title,
            questions=normalized,
            questionnaire_id=questionnaire_id,
            wait_time=max(0, min(wait_time, 3600)),
            questionnaire_kind=questionnaire_kind,
            run_id=run_id,
        )


def _validate_questions(
    questions: list[dict[str, Any]], *, markdown_style: bool
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(questions, list) or not questions:
        return [], ["questions must be a non-empty list"]
    normalized = []
    errors = []
    allowed = {"single_choice", "multiple_choice", "text"}
    markdown_allowed = {"single", "multiple", "text"}
    for index, raw in enumerate(questions):
        if not isinstance(raw, dict):
            errors.append(f"question {index} must be an object")
            continue
        value = dict(raw)
        question_type = value.get("type")
        if question_type not in (markdown_allowed if markdown_style else allowed):
            errors.append(f"question {index} has invalid type")
        title = value.get("title") or value.get("question")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"question {index} requires title")
        value["id"] = str(value.get("id") or f"q{index + 1}")
        value["title"] = str(title or "").strip()
        if question_type in {"single", "multiple", "single_choice", "multiple_choice"}:
            options = value.get("options")
            if not isinstance(options, list) or not options:
                errors.append(f"question {index} requires options")
        normalized.append(value)
    return normalized, errors
