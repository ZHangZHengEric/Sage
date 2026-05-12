import pytest

from sagents.context.messages.message import MessageChunk
from sagents.context.session_context import SessionContext


def _make_session(tmp_path):
    return SessionContext(
        session_id="sess_tool_steps",
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
    )


def test_build_execution_timing_summary_records_tool_call_messages(tmp_path):
    ctx = _make_session(tmp_path)
    assistant = MessageChunk(
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{\"path\":\"a.txt\"}"},
            }
        ],
        message_id="assistant-tool-call",
        message_type="tool_call",
    )
    tool = MessageChunk(
        role="tool",
        content="ok",
        tool_call_id="call_1",
        message_id="tool-result",
        message_type="tool_call_result",
    )
    ctx.message_manager.messages = [assistant, tool]
    ctx._message_timing = {
        "assistant-tool-call": {
            "message_id": "assistant-tool-call",
            "role": "assistant",
            "message_type": "tool_call",
            "start_ts": 10.0,
            "end_ts": 10.1,
        },
        "tool-result": {
            "message_id": "tool-result",
            "role": "tool",
            "message_type": "tool_call_result",
            "tool_call_id": "call_1",
            "start_ts": 10.2,
            "end_ts": 10.6,
        },
    }

    summary = ctx._build_execution_timing_summary()

    assert summary["message_count"] == 2
    assert summary["message_timings"][0]["message_id"] == "assistant-tool-call"
    assert summary["message_timings"][0]["message_type"] == "tool_call"
    assert summary["message_timings"][0]["duration_ms"] == pytest.approx(100.0)
    assert summary["message_timings"][1]["message_id"] == "tool-result"
    assert summary["message_timings"][1]["tool_call_id"] == "call_1"
    assert summary["message_timings"][1]["duration_ms"] == pytest.approx(400.0)
    assert summary["message_intervals"][0]["from_message_id"] == "assistant-tool-call"
    assert summary["message_intervals"][0]["to_message_id"] == "tool-result"
    assert summary["message_intervals"][0]["prev_end_to_cur_start_gap_ms"] == pytest.approx(100.0)


def test_build_execution_timing_summary_includes_flow_node_end_events(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.execution_timeline_events = [
        {
            "event_type": "flow_node_start",
            "node_name": "planning",
            "timestamp": 10.0,
            "perf_ms": 100.0,
        },
        {
            "event_type": "flow_node_end",
            "node_name": "planning",
            "timestamp": 10.3,
            "perf_ms": 400.0,
        },
        {
            "event_type": "flow_node_end",
            "node_name": "tool",
            "timestamp": 10.5,
            "perf_ms": 500.0,
        },
    ]

    summary = ctx._build_execution_timing_summary()

    assert summary["total_timeline_events"] == 3
    assert [item["node_name"] for item in summary["flow_node_timings"]] == [
        "planning",
        "tool",
    ]
