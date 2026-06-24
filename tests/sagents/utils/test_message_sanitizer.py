from sagents.utils.message_sanitizer import (
    drop_invalid_tool_calls,
    drop_orphan_tool_messages,
    repair_interleaved_tool_messages,
)


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


def test_drop_invalid_tool_calls_removes_interrupted_tool_call_from_request_view():
    assistant = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_broken",
                "type": "function",
                "function": {
                    "name": "calendar_update_event",
                    "arguments": '{"event_id": "evt_123',
                },
            }
        ],
    }
    interrupted_result = {
        "role": "tool",
        "tool_call_id": "call_broken",
        "content": '{"status": "interrupted"}',
        "metadata": {"synthetic_interrupted_tool_result": True},
    }
    user = {"role": "user", "content": "继续"}

    out = drop_orphan_tool_messages(
        drop_invalid_tool_calls([assistant, interrupted_result, user])
    )

    assert out == [user]
    assert (
        assistant["tool_calls"][0]["function"]["arguments"] == '{"event_id": "evt_123'
    )


def test_drop_invalid_tool_calls_preserves_valid_calls_on_same_message():
    valid = _tool_call("call_valid", "todo_write")
    invalid = {
        "id": "call_broken",
        "type": "function",
        "function": {"name": "todo_write", "arguments": '{"items": ['},
    }
    assistant = {"role": "assistant", "tool_calls": [invalid, valid]}
    result_valid = {"role": "tool", "tool_call_id": "call_valid", "content": "ok"}
    result_invalid = {"role": "tool", "tool_call_id": "call_broken", "content": "bad"}

    out = drop_orphan_tool_messages(
        drop_invalid_tool_calls([assistant, result_invalid, result_valid])
    )

    assert out == [
        {"role": "assistant", "tool_calls": [valid]},
        result_valid,
    ]


def test_drop_invalid_tool_calls_keeps_text_when_tool_call_is_invalid():
    assistant = {
        "role": "assistant",
        "content": "我先确认一下。",
        "tool_calls": [
            {
                "id": "call_broken",
                "type": "function",
                "function": {"name": "todo_write", "arguments": "not json"},
            }
        ],
    }

    out = drop_invalid_tool_calls([assistant])

    assert out == [{"role": "assistant", "content": "我先确认一下。"}]
