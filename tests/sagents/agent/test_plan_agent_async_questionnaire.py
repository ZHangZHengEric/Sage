import json

from sagents.agent.plan_agent import PLAN_ALLOWED_TOOLS, PlanAgent
from sagents.context.messages.message import MessageChunk, MessageRole, MessageType


def _tool_result(payload: dict) -> MessageChunk:
    return MessageChunk(
        role=MessageRole.TOOL.value,
        content=json.dumps(payload),
        tool_call_id="questionnaire-call",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )


def test_plan_agent_exposes_only_async_questionnaire_tool():
    assert "questionnaire_async" in PLAN_ALLOWED_TOOLS
    assert "questionnaire" not in PLAN_ALLOWED_TOOLS


def test_plan_agent_pauses_only_after_successful_async_questionnaire():
    assert PlanAgent._contains_successful_async_questionnaire_result(
        [_tool_result({"success": True, "should_end": True})]
    )
    assert not PlanAgent._contains_successful_async_questionnaire_result(
        [_tool_result({"success": False, "status": "error"})]
    )
