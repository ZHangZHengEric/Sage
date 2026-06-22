from sagents.agent.fibre.orchestrator import FibreOrchestrator
from sagents.context.messages.message import MessageRole


def test_coerce_child_stream_dict_preserves_tool_fields_and_session_id():
    chunk = FibreOrchestrator._coerce_child_stream_chunk(
        {
            "role": MessageRole.TOOL.value,
            "content": "{}",
            "tool_call_id": "call_memory",
            "tool_calls": [
                {
                    "id": "call_memory",
                    "type": "function",
                    "function": {"name": "search_memory", "arguments": "{}"},
                }
            ],
            "message_id": "msg-child",
            "message_type": "tool_call_result",
            "session_id": "child-session",
        }
    )

    assert chunk.role == MessageRole.TOOL.value
    assert chunk.session_id == "child-session"
    assert chunk.tool_call_id == "call_memory"
    assert chunk.tool_calls[0]["function"]["name"] == "search_memory"


def test_coerce_child_stream_event_preserves_tool_progress_fields():
    chunk = FibreOrchestrator._coerce_child_stream_chunk(
        {
            "type": "tool_progress",
            "tool_call_id": "call_memory",
            "text": "searching",
            "stream": "stdout",
            "closed": False,
            "session_id": "child-session",
        }
    )

    assert chunk.type == "tool_progress"
    assert chunk.session_id == "child-session"
    assert chunk.tool_call_id == "call_memory"
    assert chunk.metadata["raw_stream_payload"]["text"] == "searching"
