from sagents.context.messages.message import MessageChunk
from sagents.context.session_context import SessionContext


def _make_session(tmp_path):
    return SessionContext(
        session_id="sess_tool_steps",
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
    )


def test_build_tool_step_summary_pairs_tool_call_and_result(tmp_path):
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
            "start_ts": 10.0,
            "end_ts": 10.1,
        },
        "tool-result": {
            "message_id": "tool-result",
            "start_ts": 10.2,
            "end_ts": 10.6,
        },
    }

    steps = ctx._build_tool_step_summary()

    assert len(steps) == 1
    assert steps[0]["step"] == 1
    assert steps[0]["tool_name"] == "read_file"
    assert steps[0]["tool_call_id"] == "call_1"
    assert steps[0]["status"] == "completed"
    assert steps[0]["started_at"] == 10.0
    assert steps[0]["finished_at"] == 10.6
    assert steps[0]["duration_ms"] == 600.0


def test_build_phase_timing_summary_aggregates_segments(tmp_path):
    ctx = _make_session(tmp_path)
    ctx.execution_timeline_events = [
        {
            "event_type": "agent_phase_start",
            "phase_name": "planning",
            "timestamp": 10.0,
            "perf_ms": 100.0,
        },
        {
            "event_type": "agent_phase_end",
            "phase_name": "planning",
            "timestamp": 10.3,
            "perf_ms": 400.0,
        },
        {
            "event_type": "agent_phase_start",
            "phase_name": "tool",
            "timestamp": 10.5,
            "perf_ms": 500.0,
        },
        {
            "event_type": "agent_phase_end",
            "phase_name": "tool",
            "timestamp": 11.0,
            "perf_ms": 1000.0,
        },
        {
            "event_type": "agent_phase_start",
            "phase_name": "assistant_text",
            "timestamp": 11.1,
            "perf_ms": 1100.0,
        },
        {
            "event_type": "agent_phase_end",
            "phase_name": "assistant_text",
            "timestamp": 11.3,
            "perf_ms": 1300.0,
        },
        {
            "event_type": "agent_phase_start",
            "phase_name": "assistant_text",
            "timestamp": 11.4,
            "perf_ms": 1400.0,
        },
        {
            "event_type": "agent_phase_end",
            "phase_name": "assistant_text",
            "timestamp": 11.6,
            "perf_ms": 1600.0,
        },
    ]

    phases = ctx._build_phase_timing_summary()

    assert [item["phase"] for item in phases] == ["planning", "tool", "assistant_text"]
    assert phases[0]["started_at"] == 10.0
    assert phases[0]["finished_at"] == 10.3
    assert phases[0]["duration_ms"] == 300.0
    assert phases[0]["segment_count"] == 1
    assert phases[1]["duration_ms"] == 500.0
    assert phases[2]["started_at"] == 11.1
    assert phases[2]["finished_at"] == 11.6
    assert phases[2]["duration_ms"] == 400.0
    assert phases[2]["segment_count"] == 2
