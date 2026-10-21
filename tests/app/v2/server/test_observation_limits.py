"""Resource and cohort contracts for external observations."""
import asyncio
import json

import httpx
import pytest

from sagents.v2.runtime.observability.performance_evidence import ExternalDiagnostics
from tests.app.v2.server.test_external_observability import TraceCapture, capture_sample, phoenix_span
from tests.app.v2.server.test_performance import BASE


def projected_response(rows):
    data = []
    for span in rows:
        values = dict(span['attributes'])
        data.append({'index_context.span_id': span['context']['span_id'],
                     'column_name': span['name'], 'column_start_time': span['start_time'],
                     'column_context.trace_id': span['context']['trace_id'],
                     **{'column_' + key: value for key, value in values.items()}})
    body = '--test\r\nContent-Type: application/json\r\n\r\n' + json.dumps({'schema': {}, 'data': data}) + '\r\n--test--\r\n'
    return httpx.Response(200, text=body, headers={'Content-Type': 'multipart/mixed; boundary=test'})


@pytest.mark.asyncio
async def test_performance_pushes_entry_cohort_agent_and_projects_no_content():
    sink = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix')
    sink.trace_sink = TraceCapture()
    capture_sample(sink)
    rows = [phoenix_span(s) for s in sink.trace_sink.spans]
    calls = []
    def handle(request):
        assert request.method == 'POST' and request.url.path == '/v1/spans'
        body = json.loads(request.content)
        calls.append(body)
        query = body['queries'][0]
        condition = query['filter']['condition']
        assert 'agent_id' in condition and '"agent"' in condition
        assert body.get('end_time') is None
        assert 'events' not in query['select'] and 'input' not in str(query['select'])
        assert 'sage.performance.data' in query['select']
        return projected_response(rows)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await sink.report(start=BASE, end=BASE + 5, agent_id='agent', client=client)
    assert result['summary']['total_ms']['p50'] == 10000
    assert len(calls) == 2
    assert 'started_at' in calls[0]['queries'][0]['filter']['condition']
    assert 'run_id' in calls[1]['queries'][0]['filter']['condition']


@pytest.mark.asyncio
async def test_report_coalesces_identical_requests_and_does_not_cache_errors(monkeypatch):
    sink = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix')
    calls = 0
    async def query(client, **options):
        nonlocal calls
        calls += 1
        await asyncio.sleep(.01)
        if calls == 1:
            raise httpx.ConnectError('offline')
        return [], False
    monkeypatch.setattr(sink, '_query', query)
    with pytest.raises(httpx.ConnectError):
        await sink.report(start=BASE, end=BASE+1)
    results = await asyncio.gather(*(sink.report(start=BASE, end=BASE+1) for _ in range(4)))
    assert calls == 2 and len(results) == 4
    await sink.report(start=BASE, end=BASE+1)
    assert calls == 2


def test_performance_timeout_is_service_unavailable(client, service, monkeypatch):
    from tests.app.v2.server.test_admin import admin_login
    source = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix')
    service.observability.diagnostics = source
    async def fail(**options):
        raise TimeoutError()
    monkeypatch.setattr(source, 'report', fail)
    response = client.get('/api/observability/performance', headers={'Authorization': f'Bearer {admin_login(client)}'})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_hundred_runs_are_fetched_in_one_batch_and_limits_are_explicit():
    import copy
    sink = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix')
    sink.trace_sink = TraceCapture()
    capture_sample(sink)
    original = phoenix_span(sink.trace_sink.spans[0])
    rows = []
    for index in range(100):
        row = copy.deepcopy(original)
        row['context']['span_id'] = f'{index:016x}'
        row['attributes']['run_id'] = f'r-{index}'
        rows.append(row)
    requests = []
    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        return projected_response(rows[:body['limit']])
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        found, truncated = await sink._query(client, start=BASE, end=BASE+1)
        assert len(found) == 100 and not truncated
        assert len(requests) == 2
        condition = requests[1]['queries'][0]['filter']['condition']
        assert all(json.dumps(f'r-{index}') in condition for index in range(100))
        sink.max_spans = 3
        found, truncated = await sink._query(client, start=BASE, end=BASE+1)
        assert len(found) == 3 and truncated


@pytest.mark.asyncio
async def test_raw_queries_keep_byte_request_and_total_time_budgets():
    from sagents.v2.runtime.observability.query import query_budget
    source = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix')
    source.trace_sink = type('Raw', (), {'content_mode':'raw'})()
    source.max_response_bytes = 8
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'x'*9))) as client:
        with pytest.raises(ValueError, match='response exceeds'):
            await source._request(client, '/', [])
    source.max_response_bytes = 1024
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'x'*60))) as client:
        async with query_budget(max_bytes=100):
            await source._request(client, '/', [])
            with pytest.raises(ValueError, match='byte budget'):
                await source._request(client, '/', [])
        async with query_budget(requests=1):
            await source._request(client, '/', [])
            with pytest.raises(ValueError, match='request budget'):
                await source._request(client, '/', [])
    async def slow(request):
        await asyncio.sleep(.1)
        return httpx.Response(200, content=b'{}')
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        with pytest.raises(TimeoutError):
            async with query_budget(seconds=.01):
                await source._request(client, '/', [])


@pytest.mark.asyncio
async def test_close_cancels_shared_queries_and_rejects_new_builds(monkeypatch):
    source = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix')
    started, cancelled = asyncio.Event(), asyncio.Event()
    async def query(client, **options):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(source, '_query', query)
    task = asyncio.create_task(source.report(start=BASE, end=BASE+1))
    await started.wait()
    await source.close()
    assert cancelled.is_set()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ValueError, match='closed'):
        await source.report(start=BASE, end=BASE+1)
    assert not source._query_cache._pending


@pytest.mark.asyncio
async def test_whole_log_record_loss_is_detected_from_root_after_restart(monkeypatch):
    from io import BytesIO
    from zipfile import ZipFile
    from app.v2.server.storage.downloads import prepare_session_export
    source = ExternalDiagnostics(capture_mode="raw", backend='phoenix', query_url='http://phoenix')
    trace = TraceCapture()
    trace.content_mode = 'raw'
    source.trace_sink = trace
    capture_sample(source)
    await source.flush_raw()
    rows = [phoenix_span(span) for span in trace.spans]
    lost = next(row['attributes']['sage.diagnostic.record_id'] for row in rows
                if row['attributes'].get('sage.diagnostic.kind') == 'log')
    rows = [row for row in rows if row['attributes'].get('sage.diagnostic.record_id') != lost]
    # A fresh reader has no process-local drop counters; the root observation's
    # content-free log count must still reveal a wholly missing raw record.
    reader = ExternalDiagnostics(capture_mode="raw", backend='phoenix', query_url='http://phoenix')
    async def query(client, **options): return rows, False
    monkeypatch.setattr(reader, '_query', query)
    try:
        evidence = await reader.snapshot('s', {'r'})
        assert evidence['raw_capture_statistics']['dropped_records'] == 0
        assert evidence['dropped_logs'] == 1 and evidence['logs_complete'] is False
        output, _ = prepare_session_export('s', {'r'}, evidence)
        with output, ZipFile(BytesIO(output.read())) as archive:
            manifest = json.loads(archive.read('s/manifest.json'))
        assert manifest['evidence_availability']['logs']['status'] == 'partial'
    finally:
        await source.close()
        await reader.close()
