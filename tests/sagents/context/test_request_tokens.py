"""SessionContext per-request tokens 统计测试。

只验证 start_request / add_llm_request / end_request 三件套的核心流转，
不依赖沙箱与异步初始化。
"""

import json
import os
import asyncio

from sagents.context.session_context import SessionContext
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_schema import ToolSpec


def _make_session(tmp_path):
    ctx = SessionContext(
        session_id="sess_test",
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
    )
    ctx.session_workspace = os.path.join(str(tmp_path), "sess_test")
    os.makedirs(ctx.session_workspace, exist_ok=True)
    return ctx


def _fake_request(step="exec", model="m1", prompt=10, completion=5, cached=0):
    return {
        "step_name": step,
        "model_config": {"model": model},
        "started_at": 1.0,
        "first_token_time": 1.1,
        "ttfb_sec": 0.1,
        "duration_sec": 0.5,
    }, {
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "prompt_tokens_details": {"cached_tokens": cached},
        }
    }


def test_single_request_writes_file_with_total(tmp_path):
    async def _run():
        ctx = _make_session(tmp_path)
        rid = ctx.start_request({"agent_mode": "simple", "model": "m1"})
        assert rid.startswith("req_")

        for _ in range(3):
            req, resp = _fake_request(prompt=10, completion=5, cached=2)
            ctx.add_llm_request(req, resp)

        file_path = ctx.end_request("completed")
        assert file_path and os.path.exists(file_path)

        data = json.loads(open(file_path, "r", encoding="utf-8").read())
        assert data["request_id"] == rid
        assert data["status"] == "completed"
        assert len(data["per_call"]) == 3
        assert data["total_usage"]["prompt_tokens"] == 30
        assert data["total_usage"]["completion_tokens"] == 15
        assert data["total_usage"]["total_tokens"] == 45
        assert data["total_usage"]["cached_tokens"] == 6

    asyncio.run(_run())


def test_multiple_serial_requests_each_have_own_file(tmp_path):
    async def _run():
        ctx = _make_session(tmp_path)
        files = []
        for i in range(2):
            ctx.start_request({"agent_mode": "simple"})
            req, resp = _fake_request(prompt=i + 1, completion=1)
            ctx.add_llm_request(req, resp)
            files.append(ctx.end_request("completed"))

        assert len(files) == 2 and files[0] != files[1]
        for f in files:
            assert os.path.exists(f)

    asyncio.run(_run())


def test_mcp_calls_are_grouped_by_request_file(tmp_path):
    async def _run():
        ctx = _make_session(tmp_path)
        rid = ctx.start_request({"agent_mode": "simple"})

        ctx.add_mcp_call(
            {
                "tool_name": "fetch",
                "server_name": "web",
                "started_at": 1.0,
                "ended_at": 1.2,
                "duration_sec": 0.2,
                "status": "success",
                "arguments": {"url": "https://example.com"},
                "request": {
                    "tool_name": "fetch",
                    "server_name": "web",
                    "payload": {
                        "tool_name": "fetch",
                        "arguments": {"url": "https://example.com"},
                    },
                },
                "response": {"content": "ok"},
            }
        )
        ctx.add_mcp_call(
            {
                "tool_name": "fetch",
                "server_name": "web",
                "started_at": 2.0,
                "ended_at": 2.1,
                "duration_sec": 0.1,
                "status": "error",
                "arguments": {"url": "https://invalid.example"},
                "request": {
                    "tool_name": "fetch",
                    "server_name": "web",
                    "payload": {
                        "tool_name": "fetch",
                        "arguments": {"url": "https://invalid.example"},
                    },
                },
                "error": "failed",
            }
        )

        ctx.end_request("completed")
        file_path = os.path.join(ctx.session_workspace, "mcp_calls", f"{rid}.json")
        assert os.path.exists(file_path)
        assert file_path.endswith(os.path.join("mcp_calls", f"{rid}.json"))

        data = json.loads(open(file_path, "r", encoding="utf-8").read())
        assert data["request_id"] == rid
        assert data["call_count"] == 2
        assert len(data["calls"]) == 2
        assert data["calls"][0]["index"] == 0
        assert data["calls"][0]["request"]["payload"]["arguments"] == {
            "url": "https://example.com"
        }
        assert data["calls"][1]["index"] == 1
        assert data["calls"][1]["status"] == "error"

    asyncio.run(_run())


def test_tool_trace_events_include_arguments(tmp_path):
    ctx = _make_session(tmp_path)
    rid = ctx.start_request({"agent_mode": "simple"})

    ctx.record_timing_event(
        "tool_request_start",
        request_id=rid,
        tool_name="fetch",
        server_name="web",
        arguments={"url": "https://example.com"},
    )
    ctx.record_timing_event(
        "tool_request_end",
        request_id=rid,
        tool_name="fetch",
        server_name="web",
        status="success",
        duration_sec=0.2,
    )

    start_events = [
        event
        for event in ctx.execution_timeline_events
        if event.get("event_type") == "tool_request_start"
    ]
    end_events = [
        event
        for event in ctx.execution_timeline_events
        if event.get("event_type") == "tool_request_end"
    ]

    assert start_events[-1]["request_id"] == rid
    assert start_events[-1]["arguments"] == {"url": "https://example.com"}
    assert end_events[-1]["status"] == "success"
    assert end_events[-1]["duration_sec"] == 0.2


def test_session_context_save_persists_timeline_events(tmp_path):
    ctx = _make_session(tmp_path)
    rid = ctx.start_request({"agent_mode": "simple"})
    ctx.record_timing_event(
        "tool_request_start",
        request_id=rid,
        tool_name="fetch",
        server_name="web",
        arguments={"url": "https://example.com"},
    )

    ctx.save()

    context_path = os.path.join(ctx.session_workspace, "session_context.json")
    data = json.loads(open(context_path, "r", encoding="utf-8").read())
    events = data["execution_timeline_events"]
    mcp_events = [
        event for event in events if event.get("event_type") == "tool_request_start"
    ]

    assert mcp_events
    assert mcp_events[-1]["request_id"] == rid
    assert mcp_events[-1]["arguments"] == {"url": "https://example.com"}
    assert data["execution_timing_summary"]["total_timeline_events"] == len(events)


def test_builtin_tool_calls_are_saved_with_request_payload(tmp_path, monkeypatch):
    async def _run():
        ctx = _make_session(tmp_path)
        rid = ctx.start_request({"agent_mode": "simple"})

        def echo_tool(value: str):
            return {"echo": value}

        manager = ToolManager(is_auto_discover=False, isolated=True)
        manager.register_tool(
            ToolSpec(
                name="echo_tool",
                description="Echo input",
                description_i18n={},
                func=echo_tool,
                parameters={"value": {"type": "string"}},
                required=["value"],
            )
        )

        import sagents.tool.tool_manager as tool_manager_module

        monkeypatch.setattr(
            tool_manager_module,
            "_resolve_session_context",
            lambda session_id: ctx,
        )

        result = await manager.run_tool_async(
            "echo_tool",
            session_id=ctx.session_id,
            tool_call_id="call_echo_1",
            value="hello",
        )
        assert json.loads(result)["content"] == {"echo": "hello"}

        ctx.end_request("completed")
        file_path = os.path.join(ctx.session_workspace, "mcp_calls", f"{rid}.json")
        data = json.loads(open(file_path, "r", encoding="utf-8").read())

        assert data["call_count"] == 1
        call = data["calls"][0]
        assert call["tool_call_id"] == "call_echo_1"
        assert call["tool_name"] == "echo_tool"
        assert call["tool_type"] == "tool"
        assert call["arguments"] == {"value": "hello"}
        assert call["response"] == {"content": {"echo": "hello"}}

        event_types = [event["event_type"] for event in ctx.execution_timeline_events]
        assert "tool_request_start" in event_types
        assert "tool_request_end" in event_types
        tool_events = [
            event
            for event in ctx.execution_timeline_events
            if event["event_type"] in {"tool_request_start", "tool_request_end"}
        ]
        assert all(event["tool_call_id"] == "call_echo_1" for event in tool_events)

    asyncio.run(_run())


def test_nested_start_finalizes_previous_as_interrupted(tmp_path):
    async def _run():
        ctx = _make_session(tmp_path)
        rid1 = ctx.start_request({})
        req, resp = _fake_request()
        ctx.add_llm_request(req, resp)
        rid2 = ctx.start_request({})
        assert rid1 != rid2

        prev_file = os.path.join(ctx.session_workspace, "tokens_usage", f"{rid1}.json")
        assert os.path.exists(prev_file)
        prev = json.loads(open(prev_file, "r", encoding="utf-8").read())
        assert prev["status"] == "interrupted"

        ctx.end_request("completed")

    asyncio.run(_run())


def test_end_without_start_returns_none(tmp_path):
    ctx = _make_session(tmp_path)
    assert ctx.end_request("completed") is None


def test_session_context_save_skips_duplicate_snapshot(tmp_path):
    ctx = _make_session(tmp_path)

    ctx.save()
    ctx.save()

    session_end_events = [
        event
        for event in ctx.execution_timeline_events
        if event.get("event_type") == "session_end"
    ]
    assert len(session_end_events) == 1


def test_session_context_save_runs_when_status_changes(tmp_path):
    ctx = _make_session(tmp_path)

    ctx.save(session_status=ctx.status)
    ctx.save(session_status="interrupted", interrupt_reason="客户端断开连接")  # pyright: ignore[reportArgumentType]

    session_end_events = [
        event
        for event in ctx.execution_timeline_events
        if event.get("event_type") == "session_end"
    ]
    assert len(session_end_events) == 2
