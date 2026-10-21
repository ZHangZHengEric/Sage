"""Lifecycle and resource regressions found by the observation architecture review."""

from opentelemetry.util.types import AttributeValue

from typing import Any, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from anyio.from_thread import BlockingPortal
    from opentelemetry.trace import SpanContext
    from sagents.v2.contracts.principals import PrincipalType
    from sagents.v2.model.provider import ModelProvider
    from sagents.v2.runtime.observability.contracts import LogLevel
    from typing import Iterable, Mapping, Sequence

import asyncio
import gzip
import json
import threading
import tracemalloc
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.v2.server.main import create_app
from sagents.v2.runtime.observability.plugins.external.diagnostics import ExternalDiagnostics
from app.v2.server.storage.downloads import prepare_session_export
from sagents.v2.model.contracts import ModelMessage, ModelRequest, ModelResponse
from sagents.v2.contracts.items import TextBlock
from sagents.v2.runtime.observability.contracts import TraceSpan, LogRecord
from sagents.v2.runtime.observability.plugins.external.evidence import ExternalEvidenceSink
from sagents.v2.runtime.observability.plugins.phoenix import PhoenixTraceSink
from sagents.v2.runtime.observability.plugins._shared.query import query_budget
from sagents.v2.runtime.observability.evidence.raw import reconstruct
from sagents.v2.runtime.observability.traces import StructuredTracer
from tests.app.v2.server.conftest import make_test_service, register_and_login
from tests.app.v2.server.test_agui_chat import _run_input


@pytest.mark.asyncio
async def test_cancelled_catalog_diagnostic_preparation_releases_model_span():
    from types import SimpleNamespace
    from app.v2.server.catalog.records import UserCatalog
    from app.v2.server.packages.builder import CatalogPackageModel
    from sagents.v2.model.middleware.recording import RecordingModelProvider
    from sagents.v2.runtime.observability.plugins.diagnostic_noop import NoopDiagnosticSink
    from tests.app.v2.server.conftest import scripted_hello

    entered, release = asyncio.Event(), asyncio.Event()

    async def catalog(user):
        assert user == 'owner'
        entered.set()
        await release.wait()
        return UserCatalog()

    adapter = CatalogPackageModel(SimpleNamespace(editor_catalog=catalog),
        SimpleNamespace(fallback_model=scripted_hello(1)), 'owner', {})
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=exporter, max_active_spans=2)

    async def session(_):
        return 'session'

    recording = RecordingModelProvider(cast('ModelProvider', adapter), sink=NoopDiagnosticSink(),
                                       session_id_resolver=session, trace_sink=trace)

    async def consume(identifier):
        return [event async for event in recording.stream(ModelRequest(
            request_id=identifier, run_id='run', model_binding='primary', messages=()))]

    try:
        for index in range(3):
            entered.clear()
            task = asyncio.create_task(consume(f'cancel-{index}'))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert trace.statistics()['active_spans'] == 0
        release.set()
        events = await consume('success')
        assert cast('ModelResponse', events[-1].response).text == 'hello'
        assert trace.statistics()['dropped_spans'] == 0
        spans = exporter.get_finished_spans()
        assert len(spans) == 4
        assert [span.status.status_code.name for span in spans] == ['ERROR'] * 3 + ['OK']
    finally:
        release.set()
        trace.close()


def test_terminal_http_replay_does_not_start_a_new_performance_segment(tmp_path, monkeypatch):
    exporter = InMemorySpanExporter()
    original = PhoenixTraceSink.__init__
    def initialize(self, **options):
        original(self, **options, exporter=exporter)
    monkeypatch.setattr(PhoenixTraceSink, '__init__', initialize)
    host = make_test_service(tmp_path, trace_backend='phoenix', phoenix_endpoint='http://unused/v1/traces')
    with TestClient(create_app(host)) as client:
        headers = {'Authorization': f'Bearer {register_and_login(client)}'}
        async def settle():
            async with asyncio.timeout(5):
                while host.execution._drives:
                    await asyncio.sleep(.01)
        for _ in range(3):
            response = client.post('/api/agent', json=_run_input(), headers=headers)
            assert response.status_code == 200, response.text
            cast('BlockingPortal', client.portal).call(settle)
            assert not cast('Any', host.diagnostics)._timings._performance
        assert sum(span.name == 'agent.run' for span in exporter.get_finished_spans()) == 1


@pytest.mark.asyncio
async def test_dropped_root_spans_do_not_retain_finished_performance_rows():
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=InMemorySpanExporter(), max_active_spans=1)
    source = ExternalDiagnostics(backend='phoenix', query_url='http://unused')
    source.bind_trace_sink(trace)
    blocker = TraceSpan(trace_id=uuid4().hex, span_id=uuid4().hex[:16], name='blocked')
    trace.start_span(blocker)
    try:
        for index in range(10):
            scope: dict[str, Any] = {'session_id':f's{index}', 'run_id':f'r{index}'}
            source._timings.emit('log', {**scope, 'event':'server.run.performance.accepted'})
            handle = StructuredTracer(trace, 'test').start_span('agent.run', **scope)
            source._timings.emit('log', {**scope, 'event':'agent.run.started'})
            handle.end()
            source._timings.emit('log', {**scope, 'event':'server.run.performance.finished'})
            assert not source._timings._performance
        assert trace.statistics()['dropped_spans'] == 10
    finally:
        trace.end_span(blocker)
        await source.close()
        trace.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['raw', 'metadata', 'redacted'])
async def test_request_preflight_precedes_dump_and_keeps_rejected_input_memory_bounded(mode):
    class Request(ModelRequest):
        def model_dump(self, **options):
            raise AssertionError('request serializer ran before admission')
    request = Request(request_id='request', run_id='run', model_binding='main', messages=tuple(
        ModelMessage(role='user', content=(TextBlock(text='history'),)) for _ in range(20_000)))
    source = ExternalEvidenceSink(capture_mode=mode, backend='phoenix', query_url='http://unused', raw_max_bytes=4096)
    setattr(source, 'trace_sink', type('Trace', (), {'content_mode':mode})())
    try:
        tracemalloc.start()
        await source.begin_model_request(session_id='session', request=request)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert peak < 256 * 1024
        assert source.raw_statistics()['dropped_records'] == (1 if mode == 'raw' else 0)
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        await source.close()


@pytest.mark.asyncio
async def test_response_and_log_preserve_json_fields_without_pre_admission_serializers():
    class Response(ModelResponse):
        def model_dump(self, **options):
            raise AssertionError('response serializer ran before admission')
    class Record(LogRecord):
        def model_dump(self, **options):
            raise AssertionError('log serializer ran before admission')
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=exporter, content_mode='raw')
    source = ExternalDiagnostics(capture_mode="raw", backend='phoenix', query_url='http://unused')
    source.bind_trace_sink(trace)
    request = ModelRequest(request_id='q', run_id='r', model_binding='main', messages=())
    response = Response(response_id='response', finish_reason='stop', text='original\0中')
    record = Record(level=cast('LogLevel', 'info'), component='review', event='custom.event', message='original log', session_id='s', run_id='r')
    try:
        await source.complete_model_request(session_id='s', request=request, response=response)
        source.write(record)
        assert await source.flush_raw()
        rows = [{'name':span.name, 'start_time':cast('int', span.start_time)/1e9, 'attributes':dict(cast('Mapping[str, AttributeValue]', span.attributes))} for span in exporter.get_finished_spans()]
        records, gaps = reconstruct(rows)
        assert not gaps
        payloads = [json.loads(attrs['sage.diagnostic.data']) for _, attrs in records]
        assert next(row['response']['text'] for row in payloads if 'response' in row) == response.text
        log = next(row for row in payloads if row.get('event') == 'custom.event')
        assert log['timestamp'] == record.timestamp.isoformat().replace('+00:00', 'Z')
        assert log['message'] == record.message and log['session_id'] == 's'
    finally:
        await source.close()
        trace.close()


@pytest.mark.asyncio
async def test_compressed_query_is_rejected_before_body_decompression():
    compressed = gzip.compress(b'x' * (16 * 1024 * 1024))
    class Wire(httpx.AsyncByteStream):
        read = False
        async def __aiter__(self):
            self.read = True
            yield compressed
    wire = Wire()
    source = ExternalDiagnostics(backend='phoenix', query_url='http://unused', headers={'Accept-Encoding':'gzip'})
    def respond(request):
        assert request.headers['Accept-Encoding'] == 'identity'
        return httpx.Response(200, stream=wire, headers={'Content-Encoding':'gzip'})
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            tracemalloc.start()
            with pytest.raises(ValueError, match='encoding'):
                async with query_budget(max_bytes=1024*1024):
                    await source._request(client, '/', [])
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        assert not wire.read and peak < 1024*1024
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        await source.close()


@pytest.mark.asyncio
async def test_raw_flush_timeout_reaches_download_manifest_and_partial_availability(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    class BlockedSink:
        content_mode = 'raw'
        def start_span(self, span):
            entered.set()
            release.wait(5)
        def end_span(self, span):
            pass
    source = ExternalEvidenceSink(capture_mode="raw", backend='phoenix', query_url='http://unused')
    setattr(source, 'trace_sink', BlockedSink())
    original_flush = source._raw_pipeline.flush
    monkeypatch.setattr(source._raw_pipeline, 'flush', lambda timeout=5: original_flush(cast('int', .01)))
    async def query(client, **options):
        return [], False
    monkeypatch.setattr(source, '_query', query)
    try:
        assert source._evidence('log', session_id='s', run_id='r', event='pending')
        assert await asyncio.to_thread(entered.wait, 1)
        evidence = await source.snapshot('s', {'r'})
        assert evidence['raw_capture_statistics']['retained_bytes'] > 0
        output, _ = prepare_session_export('s', {'r'}, evidence)
        with output, ZipFile(BytesIO(output.read())) as archive:
            manifest = json.loads(archive.read('s/manifest.json'))
        assert evidence['pending_writes'] is True
        assert manifest['diagnostic_writes_pending'] is True
        assert evidence['logs_complete'] is False
    finally:
        release.set()
        await source.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [RuntimeError('load failed'), asyncio.CancelledError()])
async def test_resume_preparation_failure_closes_its_performance_segment(monkeypatch, failure):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from app.v2.server.conversations import runs as module
    from sagents.v2.contracts.principals import ActorRef, RequestContext
    from sagents.v2.contracts.run_state import RunState
    from sagents.v2.contracts.commands import StartRun
    source = ExternalDiagnostics(backend='phoenix', query_url='http://unused')
    events = []
    class Logger:
        def info(self, event, message, **fields):
            events.append((event, fields))
            source._timings.emit('log', {'event':event, **fields})
    monkeypatch.setattr(module, 'LOGGER', Logger())
    application = SimpleNamespace(runtime=SimpleNamespace(get_run=AsyncMock(return_value=SimpleNamespace(state=RunState.RESUMING))),
                                  agent_for_run=AsyncMock(side_effect=failure))
    command = StartRun(agent_id='agent', session_id='s', input=(),
                       resolved_spec_hash='sha256:test', idempotency_key='resume')
    service = module.RunService(application=application,
                                session_access=SimpleNamespace(get_start_command=AsyncMock(return_value=command)),
                                execution=SimpleNamespace(driving=lambda _:False))
    context = RequestContext(actor=ActorRef(principal_id='owner', principal_type=cast('PrincipalType', 'user')))
    try:
        with pytest.raises(type(failure)):
            await service.continue_detached_run('r', context, user_id='owner', session_id='s', label='resume')
        assert events[-1][0] == 'server.run.performance.finished'
        assert events[-1][1]['attributes']['run_state'] == ('cancelled' if isinstance(failure, asyncio.CancelledError) else 'failed')
        assert not source._timings._performance
    finally:
        await source.close()


@pytest.mark.asyncio
async def test_pending_performance_entries_and_rows_are_bounded_and_report_loss(monkeypatch):
    from sagents.v2.runtime.observability.performance.trace_projection import timing_rows
    from sagents.v2.runtime.observability.performance import build_run
    from tests.app.v2.server.test_performance import BASE
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=exporter)
    source = ExternalDiagnostics(backend='phoenix', query_url='http://unused', performance_max_entries=2, performance_max_rows=3)
    source.bind_trace_sink(trace)
    try:
        for index in range(3):
            source._timings.emit('log', {'session_id':f's{index}', 'run_id':f'r{index}', 'event':'server.run.performance.accepted'})
        assert len(source._timings._performance) == 2 and source.capture_failures == 1
        source._timings.emit('log', {'session_id':'s', 'run_id':'r', 'event':'server.run.performance.accepted',
                            'timestamp':BASE, 'attributes':{'started_at':BASE}}, at=BASE)
        handle = StructuredTracer(trace, 'test').start_span('agent.run', session_id='s', run_id='r')
        for event, at in [('agent.run.started', 1), ('agent.run.completed', 9), ('model.request.completed', 9.5), ('server.run.performance.finished', 10)]:
            source._timings.emit('log', {'session_id':'s', 'run_id':'r', 'event':event, 'timestamp':BASE+at}, at=BASE+at)
        handle.end()
        span = next(span for span in exporter.get_finished_spans() if span.name == 'agent.run')
        assert cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', span.attributes)['sage.performance.incomplete'] is True
        assert not cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', span.attributes).get('sage.interrupted')
        assert source.capture_failures >= 3
        rows = [{'name':span.name, 'start_time':cast('int', span.start_time)/1e9, 'attributes':dict(cast('Mapping[str, AttributeValue]', span.attributes)),
                 'context':{'trace_id':format(cast('SpanContext', span.context).trace_id,'032x'), 'span_id':format(cast('SpanContext', span.context).span_id,'016x')}}]
        events, models = timing_rows(rows)
        result = build_run(events['r'], models['r'])
        assert result['coverage'] == 'incomplete' and result['total_ms'] is None
    finally:
        await source.close()
        trace.close()


@pytest.mark.asyncio
async def test_stale_performance_expiry_exports_deferred_span_as_incomplete():
    exporter = InMemorySpanExporter()
    trace = PhoenixTraceSink(endpoint='http://unused/v1/traces', exporter=exporter)
    source = ExternalDiagnostics(backend='phoenix', query_url='http://unused', performance_idle_seconds=10)
    source.bind_trace_sink(trace)
    try:
        source._timings.emit('log', {'session_id':'s', 'run_id':'r', 'event':'server.run.performance.accepted'})
        handle = StructuredTracer(trace, 'test').start_span('agent.run', session_id='s', run_id='r')
        handle.end()
        assert not exporter.get_finished_spans()
        source._timings._performance[('s', 'r')]['last_seen'] -= 11
        source._timings.emit('log', {'session_id':'next', 'run_id':'next', 'event':'server.run.performance.accepted'})
        assert ('s', 'r') not in source._timings._performance
        span = exporter.get_finished_spans()[0]
        assert cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', span.attributes)['sage.performance.incomplete'] is True
        assert cast('Mapping[str, str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]]', span.attributes)['sage.performance.loss_reason'] == 'expired'
        assert source.capture_failures == 1
    finally:
        await source.close()
        trace.close()


@pytest.mark.asyncio
async def test_query_identity_response_still_works_for_phoenix_and_jaeger():
    for backend in ('phoenix', 'jaeger'):
        source = ExternalDiagnostics(backend=backend, query_url='http://unused')
        def respond(request):
            assert request.headers['Accept-Encoding'] == 'identity'
            return httpx.Response(200, text='{"value":"原文"}', headers={'Content-Encoding':'identity'})
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                assert json.loads(await source._request(client, '/', [])) == {'value':'原文'}
        finally:
            await source.close()


@pytest.mark.asyncio
async def test_queued_transport_bytes_are_pending_even_after_raw_worker_drains(monkeypatch):
    source = ExternalEvidenceSink(backend='phoenix', query_url='http://unused')
    setattr(source, 'trace_sink', type('Trace', (), {'content_mode':'raw', 'statistics': lambda _: {'retained_bytes':128}})())
    async def query(client, **options):
        return [], False
    monkeypatch.setattr(source, '_query', query)
    try:
        result = await source.snapshot('s', {'r'})
        assert result['raw_flush_completed'] is True
        assert result['raw_capture_statistics']['retained_bytes'] == 0
        assert result['pending_writes'] is True
        assert result['trace_export_statistics']['retained_bytes'] == 128
    finally:
        await source.close()
