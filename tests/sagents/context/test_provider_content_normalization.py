import json
import os

from sagents.context.messages.message import MessageChunk, MessageRole, MessageType
from sagents.context.messages.message_manager import MessageManager
from sagents.context.session_context import SessionContext


def test_convert_message_to_dict_for_request_stringifies_dict_content():
    msg = MessageChunk(
        role=MessageRole.TOOL.value,
        content={"status": "success", "query": "x", "results": [1]},
        tool_call_id="call_1",
        message_type=MessageType.TOOL_CALL_RESULT.value,
    )

    request_msg = MessageManager.convert_message_to_dict_for_request(msg)

    assert request_msg is not None
    assert isinstance(request_msg["content"], str)
    assert json.loads(request_msg["content"]) == {
        "status": "success",
        "query": "x",
        "results": [1],
    }


def test_add_messages_normalizes_dict_tool_content_into_ledger(tmp_path):
    ctx = SessionContext(
        session_id="parent-sess",
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
    )
    ctx.session_workspace = os.path.join(str(tmp_path), "parent-sess")
    os.makedirs(ctx.session_workspace, exist_ok=True)

    ctx.add_messages(
        MessageChunk(
            role=MessageRole.TOOL.value,
            content={"status": "success", "summary": "done"},
            tool_call_id="call_1",
            message_type=MessageType.TOOL_CALL_RESULT.value,
            session_id=f"{ctx.session_id}_sub_0",
        )
    )

    stored = ctx.message_manager.messages[-1]
    assert isinstance(stored.content, str)
    assert json.loads(stored.content) == {"status": "success", "summary": "done"}
