import asyncio
import json
from urllib.parse import quote
from typing import List, Dict, Any, Optional

from ..tool_base import tool
from sagents.utils.logger import logger
from sagents.utils.i18n import tool_t
from sagents.tool.error_codes import ToolErrorCode, make_tool_error


class QuestionnaireTool:
    """问卷工具 - 向用户展示问卷表单并收集答案"""

    QUESTIONNAIRE_MARKDOWN_TYPES = {
        "single_choice",
        "multiple_choice",
        "multi_choice",
        "text",
        "free_text",
    }
    QUESTIONNAIRE_ASYNC_SUCCESS_STATUS = "awaiting_user_input"

    def _get_backend_client(self, runtime_session_id: Optional[str] = None):
        """获取后端 API 客户端"""
        if not runtime_session_id:
            return None
        try:
            from sagents.session_runtime import get_global_session_manager

            session_manager = get_global_session_manager()
            session = session_manager.get(runtime_session_id)
            if session and session.session_context:
                return getattr(
                    session.session_context, "backend_client", None
                )
        except Exception as e:
            logger.warning(f"获取 backend_client 失败: {e}")
        return None

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
                        "title": {"type": "string", "description": "问题文本（兼容字段）"},
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
        },
    )
    async def questionnaire_async(
        self,
        questions: List[Dict[str, Any]],
        title: str = "",
        session_id: Optional[str] = None,  # pyright: ignore[reportArgumentType]
    ) -> Dict[str, Any]:
        """
        发起 questionnaire markdown 风格的问卷参数校验与提交状态返回。

        Returns:
            dict: validation payload with passed/failed details.
        """
        logger.info(
            f"QuestionnaireTool: validate title={title!r}, question_count={len(questions) if isinstance(questions, list) else 0}"
        )
        normalized_questions, errors = self._validate_markdown_style_questions(questions)
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
                if "default" in question and default is not None and not isinstance(
                    default, str
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
                                item
                                for item in default
                                if not isinstance(item, str)
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
    def _normalize_question_option(
        raw_option: Any
    ) -> Optional[Dict[str, str]]:
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

    @tool(
        description_i18n={
            "zh": "向用户展示问卷表单并收集答案。支持单选题、多选题和文本问答题。工具会等待用户提交或超时，然后返回答案。",
            "en": "Display a questionnaire form to the user and collect answers. Supports single choice, multiple choice, and text questions. Waits for user submission or timeout, then returns answers.",
        },
        param_description_i18n={
            "title": {"zh": "问卷标题", "en": "Questionnaire title"},
            "questions": {
                "zh": "问题列表，每个问题包含 id, type, title, options, default 等字段",
                "en": "List of questions, each containing id, type, title, options, default, etc.",
            },
            "wait_time": {
                "zh": "等待用户回答的最大时间(秒)，超时自动提交。默认300秒(5分钟)。",
                "en": "Maximum time to wait for user response in seconds. Auto-submit on timeout. Default is 300 seconds (5 minutes).",
            },
            "questionnaire_id": {
                "zh": "问卷ID，用于关联问卷结果。推荐使用该字段。",
                "en": "Questionnaire ID used to associate questionnaire results. Preferred field.",
            },
            "questionnaire_kind": {
                "zh": "问卷类型。planning 阶段建议显式传入，例如 plan_information 或 plan_confirmation。",
                "en": "Questionnaire kind. In planning phase, explicitly pass values such as plan_information or plan_confirmation.",
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
                            "enum": ["single_choice", "multiple_choice", "text"],
                            "description": "问题类型: single_choice(单选), multiple_choice(多选), text(文本)",
                        },
                        "title": {"type": "string", "description": "问题标题"},
                        "options": {
                            "type": "array",
                            "description": "选项列表(单选/多选必填)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": {
                                        "type": "string",
                                        "description": "选项显示文本",
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": "选项值",
                                    },
                                },
                                "required": ["label", "value"],
                            },
                        },
                        "default": {
                            "anyOf": [
                                {
                                    "type": "string",
                                    "description": "单选或文本题的默认值",
                                },
                                {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "多选题的默认值(字符串数组)",
                                },
                            ],
                            "description": "默认值，单选为字符串，多选为字符串数组，文本题为空字符串",
                        },
                        "placeholder": {
                            "type": "string",
                            "description": "文本输入框的占位提示(仅文本题)",
                        },
                        "max_length": {
                            "type": "integer",
                            "description": "最大输入长度(仅文本题)",
                            "default": 1000,
                        },
                    },
                    "required": ["id", "type", "title"],
                },
            },
            "wait_time": {
                "type": "integer",
                "description": "等待时间(秒)",
                "default": 300,
                "minimum": 0,
                "maximum": 3600,
            },
            "questionnaire_id": {"type": "string", "description": "问卷ID"},
            "questionnaire_kind": {
                "type": "string",
                "enum": ["general", "plan_information", "plan_confirmation"],
                "description": "问卷类型",
                "default": "general",
            },
        },
    )
    async def questionnaire(
        self,
        title: str,
        questions: List[Dict[str, Any]],
        questionnaire_id: str,
        session_id: Optional[str] = None,
        wait_time: int = 300,
        questionnaire_kind: str = "general",
    ) -> str:
        """
        向用户展示问卷表单并收集答案。
        工具直接轮询后端检查问卷是否有结果，前端负责展示问卷。

        Args:
            title: 问卷标题
            questions: 问题列表
            questionnaire_id: 问卷ID
            session_id: 系统注入的当前运行时会话ID，仅用于获取 backend client
            wait_time: 等待时间(秒)，默认300秒
            questionnaire_kind: 问卷类型

        Returns:
            JSON 格式的用户答案
        """
        logger.info(
            f"QuestionnaireTool: questionnaire_id={questionnaire_id}, title={title}, "
            f"wait_time={wait_time}, questionnaire_kind={questionnaire_kind}"
        )

        # 验证问题格式
        self._validate_questions(questions)

        # 获取后端客户端
        backend_client = self._get_backend_client(session_id)
        if not backend_client:
            raise ValueError("Backend client not available")

        # 轮询等待用户提交结果（通过 questionnaire_id 关联）
        logger.info(
            f"QuestionnaireTool: 开始轮询等待用户提交. questionnaire_id={questionnaire_id}"
        )
        result = await self._poll_for_result(
            backend_client, questionnaire_id, wait_time
        )

        if result is None:
            # 超时，使用默认值作为答案
            logger.warning(
                f"QuestionnaireTool: 问卷超时，使用默认值. questionnaire_id={questionnaire_id}"
            )
            default_answers = self._get_default_answers(questions)
            return json.dumps(
                {
                    "success": True,
                    "status": "timeout",
                    "message": tool_t("questionnaire.timeout"),
                    "answers": default_answers,
                    "questionnaire_kind": questionnaire_kind,
                },
                ensure_ascii=False,
                indent=2,
            )

        logger.info(
            f"QuestionnaireTool: 成功获取问卷答案. questionnaire_id={questionnaire_id}, is_auto_submit={result.get('is_auto_submit', False)}"
        )
        return json.dumps(
            {
                "success": True,
                "status": "submitted",
                "message": tool_t("questionnaire.submitted"),
                "answers": result.get("answers", {}),
                "questionnaire_id": result.get("questionnaire_id", questionnaire_id),
                "submitted_at": result.get("submitted_at"),
                "is_auto_submit": result.get("is_auto_submit", False),
                "questionnaire_kind": questionnaire_kind,
            },
            ensure_ascii=False,
            indent=2,
        )

    def _validate_questions(self, questions: List[Dict[str, Any]]):
        """验证问题格式"""
        if not questions:
            raise ValueError("Question list cannot be empty")

        for idx, q in enumerate(questions):
            if "id" not in q:
                raise ValueError(f"Question {idx + 1} is missing the id field")
            if "type" not in q:
                raise ValueError(f"Question {idx + 1} is missing the type field")
            if "title" not in q:
                raise ValueError(f"Question {idx + 1} is missing the title field")

            qtype = q["type"]
            if qtype not in ["single_choice", "multiple_choice", "text"]:
                raise ValueError(f"Question {idx + 1} has an invalid type: {qtype}")

            if qtype in ["single_choice", "multiple_choice"]:
                if "options" not in q or not q["options"]:
                    raise ValueError(
                        f"Choice question {idx + 1} is missing the options field"
                    )
                for opt_idx, opt in enumerate(q["options"]):
                    if "label" not in opt:
                        raise ValueError(
                            f"Question {idx + 1} option {opt_idx + 1} is missing the label field"
                        )
                    if "value" not in opt:
                        raise ValueError(
                            f"Question {idx + 1} option {opt_idx + 1} is missing the value field"
                        )

    def _get_default_answers(self, questions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """获取所有问题的默认值"""
        default_answers = {}
        for q in questions:
            qid = q["id"]
            qtype = q["type"]
            default_value = q.get("default")

            if qtype == "multiple_choice":
                # 多选题：默认值为数组或空数组
                default_answers[qid] = (
                    default_value if default_value is not None else []
                )
            else:
                # 单选题或文本题：默认值为字符串或空字符串
                default_answers[qid] = (
                    default_value if default_value is not None else ""
                )

        return default_answers

    async def _poll_for_result(
        self, backend_client, questionnaire_id: str, wait_time: int
    ) -> Optional[Dict[str, Any]]:
        """轮询等待用户提交结果（通过 questionnaire_id）"""
        poll_interval = 1  # 每秒检查一次
        elapsed = 0

        while elapsed < wait_time:
            try:
                # 通过 questionnaire_id 获取问卷结果
                encoded_questionnaire_id = quote(questionnaire_id, safe="")
                response = await backend_client.get(
                    f"/api/questionnaires/{encoded_questionnaire_id}/results"
                )

                if response.status_code == 200:
                    result = response.json()
                    if result.get("status") == "submitted":
                        # 获取成功后，后端会自动删除该问卷结果
                        return result
                elif response.status_code == 404:
                    # 还没有结果，继续等待
                    pass
                else:
                    logger.warning(f"轮询问卷结果失败: {response.status_code}")

            except Exception as e:
                logger.warning(f"轮询问卷结果时出错: {e}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        return None
