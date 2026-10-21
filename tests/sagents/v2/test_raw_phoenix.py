import json

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sagents.v2.model.wire_diagnostics import WireCapture
from sagents.v2.runtime.observability.contracts import TraceEvent, TraceSpan
from sagents.v2.runtime.observability.plugins.phoenix import PhoenixTraceSink


def diagnostic_payloads(spans):
    from sagents.v2.runtime.observability.raw import reconstruct
    records, gaps = reconstruct([{'name':span.name, 'start_time':span.start_time / 1e9,
                                  'attributes':dict(span.attributes)} for span in spans])
    assert not gaps
    return [json.loads(attrs['sage.diagnostic.data']) for _, attrs in records]


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
    assert json.loads(exported.attributes['input.value']) == payload
    assert exported.events[0].attributes['text'] == payload['text']
    assert exported.events[0].attributes['password'] == 'original-secret'
    from sagents.v2.runtime.observability.traces import StructuredTracer
    handle = StructuredTracer(sink, 'test').start_span('custom', attributes=payload)
    handle.add_event('event', payload)
    handle.end(status='error', error=RuntimeError('original-secret-' + 'x' * 20000))
    facade = exporter.get_finished_spans()[1]
    assert facade.attributes['password'] == 'original-secret'
    assert facade.events[0].attributes['text'] == payload['text']
    assert len(facade.events[-1].attributes['exception.message']) > 20000
    sink.close()


def test_unbounded_wire_capture_preserves_large_event():
    capture = WireCapture(max_bytes=None)
    payload = {'delta': 'x' * (8 * 1024 * 1024 + 1)}
    capture.append(payload)
    assert capture.events == [payload]
    assert capture.dropped == 0


@pytest.mark.asyncio
async def test_phoenix_external_diagnostics_preserve_raw_records():
    from sagents.v2.runtime.observability.performance_evidence import ExternalDiagnostics
    from sagents.v2.runtime.observability.contracts import LogRecord
    from tests.sagents.v2.test_trace_exporters import request

    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://localhost:6006/v1/traces',
                             content_mode='raw', exporter=exporter)
    diagnostics = ExternalDiagnostics(capture_mode="raw", backend='phoenix', query_url='http://localhost:6006')
    diagnostics.trace_sink = trace
    model_request = request()
    wire = {'messages': [{'content': '原始请求' * 10000}], 'password': 'keep'}
    stream = {'wire_events': [{'delta': '原始流' * 10000}], 'normalized_events': []}
    await diagnostics.begin_model_request(session_id='s', request=model_request,
                                           provider={}, wire_request=wire)
    await diagnostics.record_model_stream(session_id='s', request=model_request, evidence=stream)
    diagnostics.write(LogRecord(level='info', component='test', event='custom.event', message='raw log',
                                session_id='s', run_id=model_request.run_id,
                                attributes={'password': 'keep'}))
    await diagnostics.close()
    evidence = diagnostic_payloads(exporter.get_finished_spans())
    assert any(row.get('request') == wire for row in evidence)
    assert any(row.get('stream') == stream for row in evidence)
    assert any(row.get('message') == 'raw log' and row['attributes']['password'] == 'keep'
               for row in evidence)
    trace.close()


@pytest.mark.asyncio
async def test_recording_roundtrip_preserves_large_wire_and_normalized_events(monkeypatch):
    from sagents.v2.runtime.observability.performance_evidence import ExternalDiagnostics
    from sagents.v2.model import RecordingModelProvider
    from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
    from sagents.v2.model.wire_diagnostics import record_wire_event
    from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider
    from tests.sagents.v2.test_trace_exporters import request

    body = 'original-secret-' + 'x' * (8 * 1024 * 1024)
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://localhost:6006/v1/traces',
                             content_mode='raw', exporter=exporter)
    diagnostics = ExternalDiagnostics(capture_mode="raw", backend='phoenix', query_url='http://localhost:6006',
                                      raw_max_bytes=128 * 1024 * 1024)
    diagnostics.trace_sink = trace

    class Provider(ScriptedModelProvider):
        def diagnostic_request(self, request):
            return {'model': 'test', 'password': 'keep', 'messages': body}

        async def _stream(self, request):
            record_wire_event({'delta': body})
            yield ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta=body)
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED,
                                   response=ModelResponse(response_id='response', finish_reason='stop', text=body))

    async def session(_):
        return 's'

    model = RecordingModelProvider(Provider(()), sink=diagnostics,
                                   trace_sink=trace, session_id_resolver=session)
    async for _ in model.stream(request()):
        pass
    await diagnostics.close()
    spans = list(exporter.get_finished_spans())
    assert diagnostics.capture_failures == 0
    evidence = diagnostic_payloads(spans)
    assert any(row.get('response', {}).get('text') == body for row in evidence)
    assert any(row.get('request', {}).get('messages') == body for row in evidence)
    assert any(row.get('event', {}).get('delta') == body for row in evidence)

    async def query(client, **kwargs):
        return [{'name': s.name, 'start_time': s.start_time / 1e9,
                 'attributes': dict(s.attributes),
                 'events': [{'name': e.name, 'timestamp': e.timestamp / 1e9, 'attributes': dict(e.attributes)} for e in s.events]} for s in spans], False

    monkeypatch.setattr(diagnostics, '_query', query)
    result = await diagnostics.snapshot('s', {'run_1'})
    assert result['raw_model_streams_available']
    assert result['models'][0]['response']['text'] == body
    assert result['models'][0]['stream']['wire_events'] == [{'delta': body}]
    assert result['models'][0]['stream']['normalized_events'][0]['delta'] == body
    assert result['models'][0]['stream']['dropped_wire_events'] == result['models'][0]['stream']['dropped_normalized_events'] == 0
    assert result['models'][0]['raw_capture_complete']
    assert not result['models'][0]['truncated']
    trace.close()


@pytest.mark.asyncio
async def test_raw_tool_span_keeps_complete_result_error_and_operation():
    from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
    from sagents.v2.contracts.items import TextBlock
    from sagents.v2.runtime.observability.tool_evidence import tool_evidence
    from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep
    from sagents.v2.tool.contracts import ToolExecutionResult
    from tests.sagents.v2.test_observability_matrix import _CapturingTraceSink
    from tests.sagents.v2.test_agent_loop_matrix import CONTEXT, completed, setup_loop, tool_call

    traces = _CapturingTraceSink()
    traces.content_mode = "raw"
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
    from sagents.v2.runtime.observability.tool_evidence import tool_evidence
    evidence = tool_evidence([{
        "name": "tool.call", "status_code": "OK",
        "attributes": {"run_id": "r", "tool_call_id": "t", "tool_name": "read_value"},
    }], [])
    assert evidence["tools"][0]["outcome"] == "completed"
    assert evidence["tool_results_available"] is False
    assert evidence["failures"] == []


def test_redacted_performance_summary_keeps_timing_json_beyond_content_limit():
    from sagents.v2.runtime.observability.performance_evidence import ExternalDiagnostics
    from tests.app.v2.server.test_external_observability import capture_sample
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://localhost:6006/v1/traces', content_mode='redacted',
                             max_content_chars=256, exporter=exporter)
    diagnostics = ExternalDiagnostics(capture_mode="raw", backend='phoenix', query_url='http://phoenix')
    diagnostics.trace_sink = trace
    capture_sample(diagnostics)
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == 'agent.run'
    payload = ''.join(spans[0].attributes['sage.performance.data'])
    assert len(payload) > 256
    rows = json.loads(payload)
    assert len(rows) == 8
    assert spans[0].attributes['sage.performance.framework_ms'] == 4000
    trace.close()


@pytest.mark.asyncio
async def test_raw_events_follow_the_active_managed_application_exporter():
    from sagents.v2.runtime.observability.performance_evidence import ExternalDiagnostics
    from sagents.v2.runtime.observability.traces import StructuredTracer, current_trace_sink
    from tests.sagents.v2.test_trace_exporters import request
    host_exporter, managed_exporter = InMemorySpanExporter(), InMemorySpanExporter()
    host = PhoenixTraceSink(endpoint='http://localhost:6006/v1/traces', content_mode='raw', exporter=host_exporter)
    managed = PhoenixTraceSink(endpoint='http://localhost:6006/v1/traces', content_mode='raw', exporter=managed_exporter)
    diagnostics = ExternalDiagnostics(capture_mode="raw", backend='phoenix', query_url='http://phoenix')
    diagnostics.trace_sink = host
    span = StructuredTracer(managed, 'test').start_span('model.request', session_id='s', run_id='run_1')
    assert current_trace_sink() is managed
    await diagnostics.begin_model_request(session_id='s', request=request(), provider={},
                                         wire_request={'password':'keep', 'messages':'原始请求'})
    span.end()
    assert current_trace_sink() is None
    await diagnostics.close()
    payloads = diagnostic_payloads(managed_exporter.get_finished_spans())
    assert payloads[0]['request']['password'] == 'keep'
    managed_spans = managed_exporter.get_finished_spans()
    model = next(row for row in managed_spans if row.name == 'model.request')
    chunks = [row for row in managed_spans if row.name.startswith('sage.diagnostic.')]
    assert chunks and all(row.context.trace_id == model.context.trace_id and row.parent.span_id == model.context.span_id for row in chunks)
    assert not host_exporter.get_finished_spans()
    host.close()
    managed.close()
