import asyncio
import json

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.v2.server.observability.external import ExternalDiagnostics
from sagents.v2.model.contracts import ModelRequest, ModelStreamEvent, ModelResponse
from sagents.v2.model.middleware.recording import RecordingModelProvider
from sagents.v2.model.wire_diagnostics import record_wire_event
from sagents.v2.runtime.observability.plugins.phoenix import PhoenixTraceSink


@pytest.mark.asyncio
async def test_long_wire_stream_exports_independent_chunks_before_model_finishes(monkeypatch):
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=exporter, content_mode='raw')
    source = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix')
    source.bind_trace_sink(trace)
    gate = asyncio.Event()
    async def session(_): return 's'
    class Provider:
        async def stream(self, request):
            for i in range(80):
                record_wire_event({'i': i, 'value': '中' * 2000})
                yield ModelStreamEvent(kind='text_delta', delta=str(i))
            await gate.wait()
            yield ModelStreamEvent(kind='completed', response=ModelResponse(response_id='response', text='done', finish_reason='stop'))
    provider = RecordingModelProvider(Provider(), sink=source, trace_sink=trace, session_id_resolver=session)
    task = asyncio.create_task(_consume(provider, ModelRequest(request_id='request', run_id='r', model_binding='main', messages=())))
    try:
        async with asyncio.timeout(3):
            while not any(s.name == 'sage.diagnostic.chunk' for s in exporter.get_finished_spans()):
                await asyncio.sleep(.01)
        assert not task.done()
        assert source.raw_statistics()['retained_bytes'] <= source.raw_statistics()['max_bytes']
        gate.set()
        await task
        await source.flush_raw()
        spans = exporter.get_finished_spans()
        model = next(s for s in spans if s.name == "model.request")
        assert all(s.context.trace_id == model.context.trace_id and s.parent.span_id == model.context.span_id
                   for s in spans if s.attributes.get("request_id") == "request" and s.name.startswith("sage.diagnostic."))
        async def query(client, **options):
            return [{'name': s.name, 'start_time': s.start_time / 1e9,
                     'end_time': s.end_time / 1e9, 'attributes': dict(s.attributes),
                     'events': [{'name':e.name, 'timestamp':e.timestamp/1e9, 'attributes':dict(e.attributes)} for e in s.events],
                     'context': {'trace_id':format(s.context.trace_id,'032x'), 'span_id':format(s.context.span_id,'016x')}} for s in spans], False
        monkeypatch.setattr(source, '_query', query)
        evidence = await source.snapshot('s', {'r'})
        row = evidence['models'][0]
        assert row['stream']['wire_events'] == [{'i': i, 'value': '中' * 2000} for i in range(80)]
        assert row['stream']['complete'] is True
        # Losing one exported chunk must never be presented as a complete request.
        missing = next(s for s in spans if s.name == 'sage.diagnostic.chunk')
        spans = tuple(s for s in spans if s is not missing)
        evidence = await source.snapshot('s', {'r'})
        assert evidence['models'][0]['truncated'] is True
    finally:
        gate.set()
        await task
        await source.close()
        trace.close()


async def _consume(provider, request):
    return [event async for event in provider.stream(request)]


def test_transport_counts_active_queued_and_inflight_bytes():
    import threading
    class SlowExporter(InMemorySpanExporter):
        def __init__(self):
            super().__init__()
            self.entered, self.release = threading.Event(), threading.Event()
        def export(self, spans):
            self.entered.set()
            self.release.wait(2)
            return super().export(spans)
    exporter = SlowExporter()
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=exporter,
                             content_mode='raw', max_retained_bytes=32 * 1024)
    try:
        from sagents.v2.runtime.observability.contracts import TraceSpan
        from uuid import uuid4
        def start():
            span = TraceSpan(trace_id=uuid4().hex, span_id=uuid4().hex[:16], name='large', attributes={'data':'x' * 1000})
            trace.start_span(span)
            return span
        first = start()
        worker = threading.Thread(target=lambda: trace.end_span(first))
        worker.start()
        assert exporter.entered.wait(1)
        others = [start() for _ in range(20)]
        stats = trace.statistics()
        assert 0 < stats['retained_bytes'] <= 32 * 1024
        assert stats['dropped_spans'] > 0
        exporter.release.set()
        worker.join()
        for span in others:
            trace.end_span(span)
    finally:
        exporter.release.set()
        trace.close()
    assert trace.statistics()['retained_bytes'] == 0


@pytest.mark.asyncio
async def test_blocked_raw_export_drops_explicitly_without_stalling_model(monkeypatch):
    import threading
    from sagents.v2.runtime.observability.raw import RawEvidencePipeline
    class BlockedExporter(InMemorySpanExporter):
        def __init__(self):
            super().__init__()
            self.entered, self.release = threading.Event(), threading.Event()
        def export(self, spans):
            self.entered.set()
            self.release.wait(5)
            return super().export(spans)
    exporter = BlockedExporter()
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=exporter, content_mode='raw')
    source = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix')
    source.bind_trace_sink(trace)
    source._raw_pipeline = RawEvidencePipeline(max_bytes=16 * 1024)
    class Provider:
        async def stream(self, request):
            for index in range(100):
                record_wire_event({'text':'x' * 2000, 'index':index})
                yield ModelStreamEvent(kind='text_delta', delta=str(index))
    async def session(_): return 's'
    recording = RecordingModelProvider(Provider(), sink=source, session_id_resolver=session)
    # The model emits a deliberately unfinished stream; diagnostics must not
    # delay the output even while the observation exporter is stuck.
    try:
        async with asyncio.timeout(1):
            events = [event async for event in recording.stream(ModelRequest(request_id='m', run_id='r', model_binding='main', messages=()))]
        assert len(events) == 100
        assert source.raw_statistics()['retained_bytes'] <= 16 * 1024
        assert source.raw_statistics()['dropped_records'] > 0
        exporter.release.set()
        await source.flush_raw()
        spans = exporter.get_finished_spans()
        async def query(client, **options):
            return [{'name':s.name, 'attributes':dict(s.attributes), 'start_time':s.start_time/1e9} for s in spans], False
        monkeypatch.setattr(source, '_query', query)
        result = await source.snapshot('s', {'r'})
        assert result['models'] and all(row['truncated'] for row in result['models'])
    finally:
        exporter.release.set()
        await source.close()
        trace.close()


def test_raw_encoder_preserves_escaped_unicode_in_bounded_fragments():
    from sagents.v2.runtime.observability.raw import _json_fragments
    value = {'unicode':'中🧪' * 1000, 'escaped':'\0\n"\\' * 2000, 'nested':[True, None, 1.25]}
    fragments = list(_json_fragments(value, 128))
    assert json.loads(''.join(fragments)) == value
    assert max(map(len, fragments)) <= 6 * 128


def test_oversized_raw_input_is_rejected_before_encoding(monkeypatch):
    from sagents.v2.runtime.observability.contracts import TraceSpan
    from uuid import uuid4
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=exporter,
                             content_mode='raw', max_retained_bytes=8192)
    calls = []
    original = trace._attributes
    def encode(span):
        calls.append(span.span_id)
        return original(span)
    monkeypatch.setattr(trace, '_attributes', encode)
    span = TraceSpan(trace_id=uuid4().hex, span_id=uuid4().hex[:16], name='huge', attributes={'input':'x' * 5_000_000})
    try:
        trace.start_span(span)
        assert calls == []
        assert trace.statistics()['dropped_spans'] == 1
        assert trace.statistics()['retained_bytes'] == 0
    finally:
        trace.close()


def test_error_content_obeys_byte_budget_and_marks_incomplete():
    from sagents.v2.runtime.observability.contracts import TraceSpan, TraceStatus, LogError
    from sagents.v2.contracts.common import utc_now
    from uuid import uuid4
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=exporter,
                             content_mode='raw', max_retained_bytes=8192)
    span = TraceSpan(trace_id=uuid4().hex, span_id=uuid4().hex[:16], name='error', status=TraceStatus.ERROR,
                     error=LogError(type='RuntimeError', message='x'*1_000_000, stack_trace='y'*1_000_000), end_time=utc_now())
    try:
        trace.start_span(span)
        trace.end_span(span)
        exported = exporter.get_finished_spans()[0]
        assert exported.status.status_code.name == 'ERROR'
        assert exported.attributes['sage.content.incomplete'] is True
        assert exported.status.description is None
        assert not any('exception.message' in event.attributes for event in exported.events)
        assert trace.statistics()['retained_bytes'] == 0
    finally:
        trace.close()


def test_event_end_race_cannot_retain_finished_span_bytes(monkeypatch):
    import threading
    from sagents.v2.runtime.observability.contracts import TraceSpan, TraceEvent
    from uuid import uuid4
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=exporter, content_mode='raw', max_retained_bytes=8192)
    span = TraceSpan(trace_id=uuid4().hex, span_id=uuid4().hex[:16], name='race')
    trace.start_span(span)
    entered, release, ending = threading.Event(), threading.Event(), threading.Event()
    original = trace._trace_value
    def gated(value):
        if isinstance(value, dict) and 'race_event' in value:
            entered.set()
            release.wait(2)
        return original(value)
    monkeypatch.setattr(trace, '_trace_value', gated)
    event_worker = threading.Thread(target=lambda: trace.add_event(span.span_id, TraceEvent(name='race', attributes={'race_event':'x'*100})))
    def end():
        ending.set()
        trace.end_span(span)
    end_worker = threading.Thread(target=end)
    try:
        event_worker.start()
        assert entered.wait(1)
        end_worker.start()
        assert ending.wait(1)
        end_worker.join(.05)
        release.set()
        event_worker.join(2)
        end_worker.join(2)
        assert not event_worker.is_alive() and not end_worker.is_alive()
        assert trace.statistics()['active_spans'] == trace.statistics()['retained_bytes'] == 0
    finally:
        release.set()
        event_worker.join(2)
        end_worker.join(2)
        trace.close()
    assert trace.statistics()['retained_bytes'] == 0


@pytest.mark.parametrize('backend', ['otlp', 'phoenix'])
@pytest.mark.parametrize('operation', ['start', 'event', 'finish'])
def test_raw_json_escape_expansion_is_bounded_before_encoding(backend, operation):
    import tracemalloc
    from uuid import uuid4
    from sagents.v2.runtime.observability.contracts import TraceSpan, TraceEvent
    from sagents.v2.runtime.observability.plugins._shared.otlp_transport import OtlpTraceTransport
    exporter = InMemorySpanExporter()
    options = dict(exporter=exporter, content_mode='raw', max_retained_bytes=8 * 1024 * 1024)
    trace = (PhoenixTraceSink(endpoint='http://unused/v1/traces', **options) if backend == 'phoenix'
             else OtlpTraceTransport(**options))
    payload = {'input': '\0' * 2_000_000}
    span = TraceSpan(trace_id=uuid4().hex, span_id=uuid4().hex[:16], name='model.request')
    if operation != 'start':
        trace.start_span(span)
    event = TraceEvent(name='escaped', attributes={'nested':payload})
    try:
        tracemalloc.start()
        if operation == 'start':
            span = span.model_copy(update={'attributes':payload})
            trace.start_span(span)
        elif operation == 'event':
            trace.add_event(span.span_id, event)
        else:
            span = span.model_copy(update={'attributes':payload})
        trace.end_span(span)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert peak < 8 * 1024 * 1024
        spans = exporter.get_finished_spans()
        assert trace.statistics()['dropped_spans'] or spans[0].attributes['sage.content.incomplete']
        assert trace.statistics()['retained_bytes'] == 0
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        trace.close()


def test_unknown_raw_values_are_refused_before_custom_conversion():
    from uuid import uuid4
    from sagents.v2.runtime.observability.contracts import TraceSpan
    from sagents.v2.runtime.observability.raw import RawEvidencePipeline
    from sagents.v2.contracts.common import utc_now
    class ExpandingObject:
        def __str__(self):
            raise AssertionError('must not invoke unknown __str__')
        def model_dump(self, **options):
            raise AssertionError('must not invoke unknown model_dump')
    value = ExpandingObject()
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=exporter, content_mode='raw')
    pipeline = RawEvidencePipeline()
    try:
        span = TraceSpan(trace_id=uuid4().hex, span_id=uuid4().hex[:16], name='unknown', attributes={'value':value})
        trace.start_span(span)
        assert trace.statistics()['dropped_spans'] == 1 and not exporter.get_finished_spans()
        assert not pipeline.submit(trace, uuid4().hex, None, 's', 'r', 'request', {'value':value}, utc_now())
        assert pipeline.statistics()['dropped_records'] == 1
    finally:
        pipeline.close()
        trace.close()


def test_raw_pydantic_extensions_survive_without_custom_serializers():
    from pydantic import BaseModel, ConfigDict
    from sagents.v2.runtime.observability.raw import (
        _json_fragments,
        raw_trace_value,
        json_working_size,
    )
    class WireEvent(BaseModel):
        model_config = ConfigDict(extra='allow')
        kind: str
        def model_dump(self, **options):
            raise AssertionError('admission must not execute custom serializers')
    event = WireEvent(kind='delta', provider_extension={'text':'原文\0'})
    expected = {'kind':'delta', 'provider_extension':{'text':'原文\0'}}
    assert json_working_size(event, 4096) < 4096
    assert raw_trace_value(event) == expected
    assert json.loads(''.join(_json_fragments(event, 128))) == expected


def test_multiple_sdk_event_objects_share_one_raw_retention_budget():
    from pydantic import BaseModel
    from sagents.v2.runtime.observability.raw import RawEvidencePipeline
    from sagents.v2.contracts.common import utc_now
    class Event(BaseModel):
        text: str
    payload = {'events':[Event(text=letter * 4000) for letter in ('a', 'b', 'c')]}
    pipeline = RawEvidencePipeline(max_bytes=16 * 1024)
    try:
        assert not pipeline.submit(None, '1'*32, None, 's', 'r', 'stream', payload, utc_now())
        assert pipeline.statistics()['retained_bytes'] == 0
    finally:
        pipeline.close()


def test_many_pydantic_extras_are_preflighted_without_merging(monkeypatch):
    import tracemalloc
    from pydantic import BaseModel, ConfigDict
    import sagents.v2.runtime.observability.raw as raw
    from sagents.v2.contracts.common import utc_now
    class Event(BaseModel):
        model_config = ConfigDict(extra='allow')
    event = Event(**{f'field_{index}':'value' for index in range(50_000)})
    def forbidden_merge(_):
        raise AssertionError('must not merge fields before admission')
    monkeypatch.setattr(raw, '_model_fields', forbidden_merge)
    pipeline = raw.RawEvidencePipeline(max_bytes=8192)
    try:
        tracemalloc.start()
        assert raw.json_working_size(event, 8192) > 8192
        assert not pipeline.submit(None, '1'*32, None, 's', 'r', 'request', {'event':event}, utc_now())
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert peak < 16 * 1024
        assert pipeline.statistics()['dropped_records'] == 1
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        pipeline.close()
