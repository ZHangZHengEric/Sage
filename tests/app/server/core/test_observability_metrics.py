import asyncio
import hashlib

from app.server.core.middleware import (
    _is_whitelisted,
    _should_record_prometheus_http_metrics,
)
from app.server.routers.observability import prometheus_metrics
from app.server.services.prometheus_metrics import (
    _reset_prometheus_metrics_state,
    finish_http_request,
    finish_operation,
    record_sse_stream_failure,
    render_prometheus_metrics,
    start_http_request,
    start_operation,
)
from sagents.observability.prometheus_handler import (
    PrometheusTraceHandler,
    record_agent_first_token,
    render_prometheus_trace_metrics,
    reset_prometheus_trace_metrics,
)


def test_prometheus_metrics_renderer_exposes_process_metrics():
    body = render_prometheus_metrics()
    assert "# TYPE sage_server_process_cpu_seconds_total counter" in body
    assert "sage_server_process_resident_memory_bytes " in body
    assert "sage_server_system_memory_total_bytes " in body
    assert "sage_server_python_gc_collections_total" in body


def test_prometheus_metrics_route_returns_text_response():
    response = asyncio.run(prometheus_metrics())

    assert response.status_code == 200
    assert response.media_type.startswith("text/plain")  # pyright: ignore[reportOptionalMemberAccess]
    assert "sage_server_process_cpu_seconds_total " in response.body.decode()


def test_prometheus_metrics_endpoint_is_auth_whitelisted():
    assert _is_whitelisted("/api/observability/metrics")


def test_prometheus_http_metrics_skip_health_checks():
    assert not _should_record_prometheus_http_metrics("/")
    assert not _should_record_prometheus_http_metrics("/active")
    assert not _should_record_prometheus_http_metrics("/api/health")
    assert not _should_record_prometheus_http_metrics("/api/observability/metrics")
    assert _should_record_prometheus_http_metrics("/api/chat")


def test_prometheus_metrics_records_http_request_counts_and_duration():
    _reset_prometheus_metrics_state()
    started_at, method, path = start_http_request("GET", "/api/chat")
    finish_http_request(started_at, method, path, 200)

    body = render_prometheus_metrics()

    assert (
        'sage_server_http_requests_total{method="GET",path="/api/chat",status="200"} 1.000000'
        in body
    )
    assert (
        'sage_server_http_request_duration_seconds_count{method="GET",path="/api/chat"} 1.000000'
        in body
    )
    assert (
        'sage_server_http_requests_in_progress{method="GET",path="/api/chat"} 0.000000'
        in body
    )


def test_prometheus_metrics_normalizes_dynamic_path_segments():
    _reset_prometheus_metrics_state()
    started_at, method, path = start_http_request("GET", "/api/user/123")
    finish_http_request(started_at, method, path, 200)

    body = render_prometheus_metrics()

    assert 'path="/api/user/{id}"' in body


def test_prometheus_metrics_records_stream_operations():
    _reset_prometheus_metrics_state()
    stream_started, category, name = start_operation("stream", "api_chat")
    finish_operation(stream_started, category, name, "completed")

    body = render_prometheus_metrics()

    assert (
        'sage_server_operations_total{category="stream",name="api_chat",status="completed"} 1.000000'
        in body
    )
    assert (
        'sage_server_operations_active{category="stream",name="api_chat"} 0.000000'
        in body
    )


def test_prometheus_trace_handler_records_agent_and_tool_metrics():
    reset_prometheus_trace_metrics()
    handler = PrometheusTraceHandler()

    handler.on_agent_start("session-1", "SimpleAgent", agent_id="agent-demo")
    active_body = render_prometheus_trace_metrics()
    assert 'sagents_agent_starts_total{agent_id="agent-demo"} 1.000000' in active_body
    assert (
        'sagents_agent_runs_active{agent_id="agent-demo",session_id="session-1"} 1.000000'
        in active_body
    )

    handler.on_agent_end({"status": "finished"})
    record_agent_first_token("agent-demo", "session-1", 0.2)
    handler.on_tool_start("session-1", "search", {})
    handler.on_tool_error(Exception("boom"))
    handler.on_tool_start(
        "session-2", "query", {}, tool_type="mcp", server_name="AnyTool"
    )
    handler.on_tool_end({"content": "ok"})

    body = render_prometheus_trace_metrics()
    trace_id = hashlib.md5(b"session-1").hexdigest()

    assert (
        'sagents_agent_runs_total{agent_id="agent-demo",status="success"} 1.000000'
        in body
    )
    assert (
        'sagents_agent_runs_active{agent_id="agent-demo",session_id="session-1"}'
        not in body
    )
    assert (
        'sagents_agent_run_duration_seconds_count{agent_id="agent-demo",status="success"} 1.000000'
        in body
    )
    assert (
        'sagents_first_token_seconds_count{agent_id="agent-demo",session_id="session-1"} 1.000000'
        in body
    )
    assert (
        'sagents_first_token_seconds_sum{agent_id="agent-demo",session_id="session-1"} 0.200000'
        in body
    )
    assert (
        'sagents_tool_calls_total{tool_name="search",status="error"} 1.000000' in body
    )
    assert (
        'sagents_tool_calls_total{tool_name="query",status="success"} 1.000000' in body
    )
    assert (
        'sagents_tool_call_duration_seconds_count{tool_name="search"} 1.000000' in body
    )
    assert (
        'sagents_tool_call_failures_total{tool_name="search",'
        f'session_id="session-1",trace_id="{trace_id}",error_type="Exception"}} 1.000000'
    ) in body
    assert "SAGE_PROMETHEUS_SESSION_LABELS" not in body
    assert "sagents_observability_operations_total" not in body


def test_prometheus_sse_failures_include_session_drilldown_only_for_failure_statuses():
    _reset_prometheus_metrics_state()

    record_sse_stream_failure("chat_stream", "session-1", "error")
    record_sse_stream_failure("chat_stream", "session-2", "cancelled")
    record_sse_stream_failure("resume_stream", "session-3", "fallback_missing")
    record_sse_stream_failure("chat_stream", "session-4", "disconnected")

    body = render_prometheus_metrics()
    trace_id = hashlib.md5(b"session-1").hexdigest()

    assert (
        'sage_server_sse_stream_failures_total{stream="chat_stream",'
        f'session_id="session-1",trace_id="{trace_id}",status="error"}} 1.000000'
    ) in body
    assert 'session_id="session-2"' in body
    assert 'session_id="session-3"' in body
    assert 'session_id="session-4"' not in body
