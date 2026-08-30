import pytest

from sagents.tool.error_codes import ToolErrorCode
from sagents.tool.impl.questionnaire_tool import QuestionnaireTool
from sagents.utils.i18n import tool_language


@pytest.mark.asyncio
async def test_questionnaire_async_free_text_default_type_error_is_structured():
    tool = QuestionnaireTool()
    with tool_language("zh"):
        result = await tool.questionnaire_async(
            questions=[{"type": "free_text", "text": "请回答", "default": 123}],
            title="测试问卷",
            session_id="session-1",
        )

    assert result["success"] is False
    assert result["status"] == "error"
    assert result["error_code"] == ToolErrorCode.INVALID_ARGUMENT
    errors = result.get("errors")
    assert isinstance(errors, list) and len(errors) == 1

    error = errors[0]
    assert isinstance(error, dict)
    assert error["code"] == "questionnaire.start.default_type_invalid"
    assert error["path"] == "questions[1].default"
    assert error["details"] == {
        "path": "questions[1].default",
        "expected": "string",
        "actual": "int",
    }
    assert "default 类型不合法" in error["message"]


@pytest.mark.asyncio
async def test_questionnaire_async_success_returns_waiting_state_and_should_end():
    tool = QuestionnaireTool()
    with tool_language("en"):
        result = await tool.questionnaire_async(
            questions=[{"type": "text", "text": "Your name", "default": ""}],
            title="Profile",
            session_id="session-1",
            questionnaire_kind="plan_information",
        )

    assert result["success"] is True
    assert result["status"] == QuestionnaireTool.QUESTIONNAIRE_ASYNC_SUCCESS_STATUS
    assert result["should_end"] is True
    assert result["validation_passed"] is True
    assert result["questionnaire_kind"] == "plan_information"
