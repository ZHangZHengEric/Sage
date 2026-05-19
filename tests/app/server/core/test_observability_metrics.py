import asyncio

from app.server.core.middleware import _is_whitelisted, _should_record_prometheus_http_metrics
from app.server.routers.observability import prometheus_metrics
from app.server.services.prometheus_metrics import (
    _reset_prometheus_metrics_state,
    finish_http_request,
    finish_operation,
    render_prometheus_metrics,
    start_http_request,
    start_operation,
)
from sagents.observability.prometheus_handler import (
    PrometheusTraceHandler,
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
    assert response.media_type.startswith("text/plain")
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

    assert 'sage_server_http_requests_total{method="GET",path="/api/chat",status="200"} 1.000000' in body
    assert 'sage_server_http_request_duration_seconds_count{method="GET",path="/api/chat"} 1.000000' in body
    assert 'sage_server_http_requests_in_progress{method="GET",path="/api/chat"} 0.000000' in body


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

    assert 'sage_server_operations_total{category="stream",name="api_chat",status="completed"} 1.000000' in body
    assert 'sage_server_operations_active{category="stream",name="api_chat"} 0.000000' in body


def test_prometheus_trace_handler_records_agent_llm_tool_and_mcp_hooks():
    reset_prometheus_trace_metrics()
    handler = PrometheusTraceHandler()

    handler.on_chain_start("session-1", {})
    handler.on_chain_end("ok")
    handler.on_agent_start("session-1", "SimpleAgent")
    handler.on_agent_end({"status": "finished"})
    handler.on_llm_start("session-1", "gpt-test", [], step_name="plan")
    handler.on_llm_end("ok")
    handler.on_tool_start("session-1", "search", {})
    handler.on_tool_error(Exception("boom"))
    handler.on_tool_start("session-1", "query", {}, tool_type="mcp", server_name="AnyTool")
    handler.on_tool_end({"content": "ok"})

    body = render_prometheus_trace_metrics()

    assert 'sagents_observability_operations_total{category="chain",name="session-1",status="success"} 1.000000' in body
    assert 'sagents_observability_operations_total{category="agent",name="session-1",status="success"} 1.000000' in body
    assert 'sagents_observability_operations_total{category="llm",name="session-1",status="success"} 1.000000' in body
    assert 'sagents_observability_operations_total{category="tool",name="session-1",status="error"} 1.000000' in body
    assert 'sagents_observability_operations_total{category="mcp",name="session-1",status="success"} 1.000000' in body
