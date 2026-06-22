from sagents.utils.message_sanitizer import repair_interleaved_tool_messages


def _tool_call(call_id: str, name: str = "todo_write") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


def test_repair_interleaved_tool_messages_moves_result_before_guidance():
    assistant = {
        "role": "assistant",
        "tool_calls": [_tool_call("call_1")],
    }
    guidance = {"role": "user", "content": "而且我需要60秒左右的视频"}
    tool_result = {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "ok",
    }
    next_assistant = {"role": "assistant", "content": "继续处理"}

    out = repair_interleaved_tool_messages(
        [assistant, guidance, tool_result, next_assistant]
    )

    assert out == [assistant, tool_result, guidance, next_assistant]


def test_repair_interleaved_tool_messages_preserves_multi_call_order():
    assistant = {
        "role": "assistant",
        "tool_calls": [_tool_call("call_a", "grep"), _tool_call("call_b", "read")],
    }
    user = {"role": "user", "content": "补充一句"}
    result_b = {"role": "tool", "tool_call_id": "call_b", "content": "b"}
    result_a = {"role": "tool", "tool_call_id": "call_a", "content": "a"}

    out = repair_interleaved_tool_messages([assistant, user, result_b, result_a])

    assert out == [assistant, result_a, result_b, user]
