

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Iterable, Mapping, Sequence

import json

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sagents.v2.model.wire_diagnostics import WireCapture
from sagents.v2.runtime.observability.contracts import TraceEvent, TraceSpan
from sagents.v2.runtime.observability.plugins.phoenix import PhoenixTraceSink


def test_raw_phoenix_preserves_content_and_events(monkeypatch):
    monkeypatch.setenv('OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT', '10')
    exporter = InMemorySpanExporter()
    sink = PhoenixTraceSink(endpoint='http://localhost:6006/v1/traces',
                            content_mode='raw', exporter=exporter)
    payload = {'password': 'original-secret', 'url': 'https://host/x?token=original',
               'data': 'data:image/png;base64,unchanged', 'text': '原文' * 40000,
               'items': list(range(200))}
    span = TraceSpan(trace_id='1' * 32, span_id='2' * 16, name='model.request',
                     attributes={'input': payload})
    sink.start_span(span)
    sink.add_event(span.span_id, TraceEvent(name='raw.event', attributes=payload))
    sink.end_span(span)
    exported = exporter.get_finished_spans()[0]
    assert json.loads(cast('str | bytes | bytearray', cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', exported.attributes)['input.value'])) == payload
    assert cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', exported.events[0].attributes)['text'] == payload['text']
    assert cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', exported.events[0].attributes)['password'] == 'original-secret'
    from sagents.v2.runtime.observability.traces import StructuredTracer
    handle = StructuredTracer(sink, 'test').start_span('custom', attributes=payload)
    handle.add_event('event', payload)
    handle.end(status='error', error=RuntimeError('original-secret-' + 'x' * 20000))
    facade = exporter.get_finished_spans()[1]
    assert cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', facade.attributes)['password'] == 'original-secret'
    assert cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', facade.events[0].attributes)['text'] == payload['text']
    assert len(cast(str, cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', facade.events[-1].attributes)['exception.message'])) > 20000
    sink.close()


def test_unbounded_wire_capture_preserves_large_event():
    capture = WireCapture(max_bytes=cast('int', None))
    payload = {'delta': 'x' * (8 * 1024 * 1024 + 1)}
    capture.append(payload)
    assert capture.events == [payload]
    assert capture.dropped == 0


@pytest.mark.asyncio
async def test_raw_tool_span_keeps_complete_result_error_and_operation():
    from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
    from sagents.v2.contracts.items import TextBlock
    from sagents.v2.runtime.observability.evidence.tools import tool_evidence
    from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep
    from sagents.v2.tool.contracts import ToolExecutionResult
    from tests.sagents.v2.test_observability_matrix import _CapturingTraceSink
    from tests.sagents.v2.test_agent_loop_matrix import CONTEXT, completed, setup_loop, tool_call

    traces = _CapturingTraceSink()
    setattr(traces, 'content_mode', "raw")
    message = "password=original-secret " + "原始错误" * 20000
    results = []

    async def failed_tool(call, _context):
        result = ToolExecutionResult(
            tool_call_id=call.tool_call_id, operation_id=call.operation_id,
            content=(TextBlock(text="原始结果" * 20000),),
            error=RuntimeErrorInfo(code="tool.failed", category=ErrorCategory.PROVIDER_PERMANENT,
                                   message=message), metadata={"opaque": "original-secret"})
        results.append(result)
        return result

    model = ScriptedModelProvider((
        ScriptedModelStep(events=(completed("", calls=(tool_call(),)),)),
        ScriptedModelStep(events=(completed("handled"),)),
    ))
    _runtime, handle, loop, _executor = await setup_loop(
        model, trace_sink=traces,
        handlers={"read_value": failed_tool, "write_value": failed_tool})
    await loop.execute(handle.run_id, CONTEXT)
    span = next(s for s in traces.ended if s.name == "tool.call")
    assert span.attributes["execution_result"] == results[0].model_dump(mode="json")
    assert span.attributes["error"]["message"] == message
    assert message in span.attributes["status_message"]
    assert span.attributes["operation_id"] == results[0].operation_id
    evidence = tool_evidence([{
        "name": span.name, "attributes": {k: json.dumps(v) if isinstance(v, dict) else v
                                           for k, v in span.attributes.items()},
        "start_time": span.start_time.isoformat(),
    }], [])
    assert evidence["tools"][0]["result"] == results[0].model_dump(mode="json")
    assert evidence["failures"][0]["error"]["message"] == message


def test_historical_successful_tool_span_marks_missing_result_without_failure():
    from sagents.v2.runtime.observability.evidence.tools import tool_evidence
    evidence = tool_evidence([{
        "name": "tool.call", "status_code": "OK",
        "attributes": {"run_id": "r", "tool_call_id": "t", "tool_name": "read_value"},
    }], [])
    assert evidence["tools"][0]["outcome"] == "completed"
    assert evidence["tool_results_available"] is False
    assert evidence["failures"] == []


@pytest.mark.asyncio
async def test_redacted_performance_summary_keeps_timing_json_beyond_content_limit():
    from sagents.v2.runtime.observability.plugins.external.diagnostics import ExternalDiagnostics
    from tests.app.v2.server.test_external_observability import capture_sample
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://localhost:6006/v1/traces', content_mode='redacted',
                             max_content_chars=256, exporter=exporter)
    diagnostics = ExternalDiagnostics(capture_mode="raw", backend='phoenix', query_url='http://phoenix')
    diagnostics.trace_sink = trace
    try:
        capture_sample(diagnostics)
        spans = [span for span in exporter.get_finished_spans() if span.name == 'agent.run']
        assert len(spans) == 1
        payload = ''.join(cast('Iterable[str]', cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', spans[0].attributes)['sage.performance.data']))
        assert len(payload) > 256
        rows = json.loads(payload)
        assert len(rows) == 8
        assert cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', spans[0].attributes)['sage.performance.framework_ms'] == 4000
    finally:
        await diagnostics.close()
        trace.close()
