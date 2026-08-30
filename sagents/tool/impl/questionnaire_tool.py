from typing import List, Dict, Any, Optional

from ..tool_base import tool
from sagents.utils.logger import logger
from sagents.utils.i18n import tool_t
from sagents.tool.error_codes import ToolErrorCode, make_tool_error


class QuestionnaireTool:
    TOOL_CATEGORY = "interaction"

    """异步问卷工具：校验问卷并把回答交给下一轮用户消息。"""

    QUESTIONNAIRE_MARKDOWN_TYPES = {
        "single_choice",
        "multiple_choice",
        "multi_choice",
        "text",
        "free_text",
    }
    QUESTIONNAIRE_ASYNC_SUCCESS_STATUS = "awaiting_user_input"

    @tool(
        description_i18n={
            "zh": "发起问卷，参数通过后返回“已发起并等待用户回复”。",
            "en": "Start questionnaire invocation, returning pending-user-input status when arguments are valid.",
            "pt": "Inicia o questionário, retornando estado pendente de resposta do usuário quando os argumentos forem válidos.",
        },
        param_description_i18n={
            "title": {
                "zh": "问卷标题（可选）",
                "en": "Questionnaire title (optional)",
                "pt": "Título do questionário (opcional)",
            },
            "questions": {
                "zh": "问题列表。每题需包含 type、text（或 title）等字段；选择题需 options。",
                "en": "Questions list. Each question should include type and text (or title), and options for choice questions.",
                "pt": "Lista de perguntas. Cada pergunta deve incluir type e text (ou title), e options para perguntas de seleção.",
            },
            "session_id": {
                "zh": "会话ID（自动注入）",
                "en": "Session ID (automatically injected)",
                "pt": "ID da sessão (injetado automaticamente)",
            },
            "questionnaire_kind": {
                "zh": "问卷用途类型。规划阶段可使用 plan_information 或 plan_confirmation。",
                "en": "Questionnaire purpose. Planning may use plan_information or plan_confirmation.",
                "pt": "Finalidade do questionário; o planejamento pode usar plan_information ou plan_confirmation.",
            },
        },
        param_schema={
            "title": {"type": "string", "description": "问卷标题"},
            "questions": {
                "type": "array",
                "description": "问题列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "问题唯一标识符"},
                        "type": {
                            "type": "string",
                            "description": "问题类型: single_choice/multiple_choice/text/free_text/multi_choice",
                        },
                        "text": {"type": "string", "description": "问题文本"},
                        "title": {
                            "type": "string",
                            "description": "问题文本（兼容字段）",
                        },
                        "options": {
                            "type": "array",
                            "description": "单选题/多选题选项",
                            "items": {
                                "anyOf": [
                                    {"type": "string"},
                                    {
                                        "type": "object",
                                        "properties": {
                                            "value": {"type": "string"},
                                            "label": {"type": "string"},
                                        },
                                        "required": ["value", "label"],
                                    },
                                ]
                            },
                        },
                        "default": {
                            "description": "默认值（单选/多选/文本题）",
                            "anyOf": [
                                {"type": "string"},
                                {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            ],
                        },
                        "allow_other": {
                            "type": "boolean",
                            "description": "是否允许其他选项",
                        },
                    },
                    "required": ["type"],
                },
            },
            "session_id": {"type": "string", "description": "会话ID"},
            "questionnaire_kind": {
                "type": "string",
                "enum": ["general", "plan_information", "plan_confirmation"],
                "description": "问卷用途类型",
                "default": "general",
            },
        },
    )
    async def questionnaire_async(
        self,
        questions: List[Dict[str, Any]],
        title: str = "",
        session_id: Optional[str] = None,  # pyright: ignore[reportArgumentType]
        questionnaire_kind: str = "general",
    ) -> Dict[str, Any]:
        """
        发起 questionnaire markdown 风格的问卷参数校验与提交状态返回。

        Returns:
            dict: validation payload with passed/failed details.
        """
        logger.info(
            f"QuestionnaireTool: validate title={title!r}, question_count={len(questions) if isinstance(questions, list) else 0}"
        )
        normalized_questions, errors = self._validate_markdown_style_questions(
            questions
        )
        if errors:
            return make_tool_error(
                ToolErrorCode.INVALID_ARGUMENT,
                "Questionnaire parameter validation failed.",
                errors=errors,
                validation_passed=False,
            )

        return {
            "success": True,
            "status": QuestionnaireTool.QUESTIONNAIRE_ASYNC_SUCCESS_STATUS,
            "validation_passed": True,
            "title": (title or "").strip(),
            "question_count": len(normalized_questions),
            "questions": normalized_questions,
            "questionnaire_kind": questionnaire_kind,
            "should_end": True,
            "message": tool_t(
                "questionnaire.start.success",
                params={"count": len(normalized_questions)},
            ),
        }

    @staticmethod
    def _build_validation_error(
        field: str,
        code: str,
        **params: Any,
    ) -> Dict[str, Any]:
        message_params = {"path": field, **params}
        return {
            "code": code,
            "path": field,
            "message": tool_t(code, params=message_params),
            "details": message_params,
        }

    def _validate_markdown_style_questions(
        self, questions: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """校验 markdown 问卷风格的参数，返回（标准化后的题目列表, 错误列表）。"""
        if not isinstance(questions, list):
            return [], [
                self._build_validation_error(
                    "questions", "questionnaire.start.questions_must_be_list"
                )
            ]
        if not questions:
            return [], [
                self._build_validation_error(
                    "questions", "questionnaire.start.questions_empty"
                )
            ]

        normalized_questions: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        used_question_ids = set()

        for idx, question in enumerate(questions, start=1):
            issue_prefix = f"questions[{idx}]"
            if not isinstance(question, dict):
                errors.append(
                    self._build_validation_error(
                        issue_prefix, "questionnaire.start.question_not_object"
                    )
                )
                continue

            raw_question_type = str(question.get("type") or "").strip().lower()
            question_type = self._normalize_questionnaire_type(raw_question_type)
            if question_type not in self.QUESTIONNAIRE_MARKDOWN_TYPES:
                errors.append(
                    self._build_validation_error(
                        issue_prefix,
                        "questionnaire.start.question_type_invalid",
                        value=raw_question_type,
                        allowed="single_choice, multiple_choice, multi_choice, text, free_text",
                    )
                )
                continue

            raw_text = question.get("text")
            if not isinstance(raw_text, str) or not raw_text.strip():
                raw_text = question.get("title")
            if not isinstance(raw_text, str) or not raw_text.strip():
                errors.append(
                    self._build_validation_error(
                        issue_prefix,
                        "questionnaire.start.question_text_required",
                    )
                )
                continue
            question_text = raw_text.strip()

            question_id = str(question.get("id") or f"q{idx}").strip()
            if not question_id:
                question_id = f"q{idx}"
            if question_id in used_question_ids:
                errors.append(
                    self._build_validation_error(
                        issue_prefix,
                        "questionnaire.start.question_id_duplicate",
                        value=question_id,
                    )
                )
            used_question_ids.add(question_id)

            normalized_options: List[Dict[str, str]] = []
            if question_type != "free_text":
                raw_options = question.get("options")
                if not isinstance(raw_options, list) or not raw_options:
                    errors.append(
                        self._build_validation_error(
                            issue_prefix,
                            "questionnaire.start.question_options_required",
                        )
                    )
                    continue

                for opt_idx, raw_option in enumerate(raw_options, start=1):
                    option = self._normalize_question_option(raw_option)
                    if option is None:
                        errors.append(
                            self._build_validation_error(
                                f"{issue_prefix} options[{opt_idx}]",
                                "questionnaire.start.question_option_invalid",
                            )
                        )
                    else:
                        normalized_options.append(option)

                if not normalized_options and question_type != "free_text":
                    continue
            default = question.get("default")
            if question_type == "multi_choice":
                normalized_default: str | List[str] = []
            else:
                normalized_default: str | List[str] = ""

            if question_type == "free_text":
                if (
                    "default" in question
                    and default is not None
                    and not isinstance(default, str)
                ):
                    errors.append(
                        self._build_validation_error(
                            f"{issue_prefix}.default",
                            "questionnaire.start.default_type_invalid",
                            expected="string",
                            actual=type(default).__name__,
                        )
                    )
                else:
                    normalized_default = "" if default is None else str(default)

            if question_type == "single_choice":
                option_values = [opt["value"] for opt in normalized_options]
                if "default" in question:
                    if not isinstance(default, str):
                        errors.append(
                            self._build_validation_error(
                                issue_prefix,
                                "questionnaire.start.default_type_invalid",
                                expected="string",
                                actual=type(default).__name__,
                            )
                        )
                    elif default not in option_values:
                        errors.append(
                            self._build_validation_error(
                                issue_prefix,
                                "questionnaire.start.default_value_not_in_options",
                                value=default,
                            )
                        )
                    else:
                        normalized_default = default

            if question_type == "multi_choice":
                if "default" in question:
                    if not isinstance(default, list) or any(
                        not isinstance(item, str) for item in default
                    ):
                        if not isinstance(default, list):
                            errors.append(
                                self._build_validation_error(
                                    issue_prefix,
                                    "questionnaire.start.default_type_invalid",
                                    expected="string list",
                                    actual=type(default).__name__,
                                )
                            )
                        else:
                            invalid_items = [
                                item for item in default if not isinstance(item, str)
                            ]
                            errors.append(
                                self._build_validation_error(
                                    issue_prefix,
                                    "questionnaire.start.default_list_invalid_items",
                                    invalid_items=", ".join(map(str, invalid_items)),
                                )
                            )
                    else:
                        option_values = [opt["value"] for opt in normalized_options]
                        invalid_defaults = [
                            item for item in default if item not in option_values
                        ]
                        if invalid_defaults:
                            errors.append(
                                self._build_validation_error(
                                    issue_prefix,
                                    "questionnaire.start.default_value_not_in_options",
                                    value=", ".join(map(str, invalid_defaults)),
                                )
                            )
                        else:
                            normalized_default = [str(item) for item in default]

            allow_other = question.get("allow_other")
            if allow_other is not None and not isinstance(allow_other, bool):
                errors.append(
                    self._build_validation_error(
                        issue_prefix,
                        "questionnaire.start.allow_other_type_invalid",
                    )
                )

            normalized_questions.append(
                {
                    "id": question_id,
                    "type": question_type,
                    "text": question_text,
                    "options": normalized_options,
                    "default": normalized_default,
                    "allow_other": bool(allow_other),
                }
            )

        return normalized_questions, errors

    @staticmethod
    def _normalize_questionnaire_type(raw_type: str) -> str:
        """将 markdown 风格和历史风格的 type 转换为标准类型。"""
        if raw_type in ("single_choice", "text", "free_text"):
            if raw_type == "text":
                return "free_text"
            return raw_type
        if raw_type in ("multiple_choice", "multi_choice"):
            return "multi_choice"
        return ""

    @staticmethod
    def _normalize_question_option(raw_option: Any) -> Optional[Dict[str, str]]:
        if isinstance(raw_option, str):
            value = raw_option.strip()
            if not value:
                return None
            return {"value": value, "label": value}

        if not isinstance(raw_option, dict):
            return None

        raw_value = raw_option.get("value")
        raw_label = raw_option.get("label")
        if not isinstance(raw_value, str) or not raw_value.strip():
            raw_value = None
        if not isinstance(raw_label, str) or not raw_label.strip():
            raw_label = None

        if raw_value is None and raw_label is None:
            return None

        normalized_value = (raw_value or raw_label or "").strip()
        normalized_label = (raw_label or raw_value or "").strip()
        if not normalized_value or not normalized_label:
            return None
        return {"value": normalized_value, "label": normalized_label}
