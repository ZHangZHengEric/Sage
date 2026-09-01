"""Decorator-backed V2 questionnaire tools."""

from __future__ import annotations

from typing import Any

from sagents.v2.tool import ToolInvocation, tool
from sagents.v2.tool.official.runtime import OfficialToolRuntime
from sagents.v2.agent.policy import InteractionDraft
from sagents.v2.i18n import normalize_language, tr


def _questions_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["single", "multiple", "text"],
                },
                "title": {"type": "string", "minLength": 1},
                "question": {"type": "string", "minLength": 1},
                "options": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "oneOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string"},
                                    "value": {"type": "string"},
                                },
                                "required": ["label", "value"],
                                "additionalProperties": False,
                            },
                        ]
                    },
                },
                "default": {},
                "placeholder": {"type": "string"},
                "allow_other": {"type": "boolean", "default": False},
            },
            "required": ["type"],
            "additionalProperties": False,
        },
    }


_QUESTIONNAIRE_ASYNC_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": _questions_schema(),
        "title": {"type": "string", "default": ""},
        "session_id": {"type": ["string", "null"], "default": None},
        "questionnaire_kind": {
            "type": "string",
            "enum": ["general", "plan_information", "plan_confirmation"],
            "default": "general",
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}


class InteractionTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    @tool(
        description="Validate a markdown-style questionnaire payload.",
        input_schema=_QUESTIONNAIRE_ASYNC_INPUT_SCHEMA,
    )
    async def questionnaire_async(
        self,
        questions: list[dict[str, Any]],
        title: str = "",
        session_id: str | None = None,
        questionnaire_kind: str = "general",
        invocation: ToolInvocation | None = None,
    ) -> dict[str, Any]:
        del session_id
        language = normalize_language(
            invocation.request_context.language if invocation is not None else "en"
        )
        normalized, errors = _validate_questions(questions, language=language)
        if errors:
            return {
                "success": False,
                "status": "error",
                "validation_passed": False,
                "errors": errors,
            }
        resolved_title = title.strip() or tr("recovery.title", language)
        result = {
            "success": True,
            "status": "questionnaire_ready",
            "validation_passed": True,
            "title": resolved_title,
            "question_count": len(normalized),
            "questions": normalized,
            "questionnaire_kind": questionnaire_kind,
            "should_end": True,
        }
        run_id = invocation.call.owner_run_id if invocation is not None else "unknown"
        self.runtime.set_turn_status(
            run_id,
            {
                "status": "need_user_input",
                "note": resolved_title,
                "interaction": InteractionDraft(
                    interaction_type="questionnaire",
                    allowed_decisions=("submit", "cancel"),
                    payload={
                        "title": resolved_title,
                        "prompt": tr("recovery.input_prompt", language),
                        "guidance": tr("recovery.guidance", language),
                        "questions": normalized,
                        "questionnaire_kind": questionnaire_kind,
                        "language": language,
                        "source": "questionnaire_async",
                    },
                ).model_dump(mode="json"),
            },
        )
        return result


def _validate_questions(
    questions: list[dict[str, Any]],
    *,
    language: str = "en",
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(questions, list) or not questions:
        return [], [tr("questionnaire.invalid_list", language)]
    normalized = []
    errors = []
    allowed = {"single", "multiple", "text"}
    for index, raw in enumerate(questions):
        if not isinstance(raw, dict):
            errors.append(tr("questionnaire.invalid_object", language, index=index + 1))
            continue
        value = dict(raw)
        question_type = value.get("type")
        if question_type not in allowed:
            errors.append(tr("questionnaire.invalid_type", language, index=index + 1))
        title = value.get("title") or value.get("question")
        if not isinstance(title, str) or not title.strip():
            errors.append(tr("questionnaire.missing_title", language, index=index + 1))
        value["id"] = str(value.get("id") or f"q{index + 1}")
        value["title"] = str(title or "").strip()
        if question_type in {"single", "multiple"}:
            options = value.get("options")
            if not isinstance(options, list) or not options:
                errors.append(
                    tr("questionnaire.missing_options", language, index=index + 1)
                )
        normalized.append(value)
    return normalized, errors
