
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Any

import gzip
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from sagents.v2.runtime.observability.plugins.external.diagnostics import ExternalDiagnostics
from sagents.v2.runtime.observability.plugins.external.phoenix import PhoenixTraceQuery
from app.v2.server.main import create_app
from tests.app.v2.server.conftest import make_test_service


@pytest.mark.asyncio
async def test_dashboard_aggregates_without_fetching_model_payloads():
    source = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix',
                                 headers={'Authorization': 'secret'})
    requests = []
    def handle(request):
        requests.append(request)
        assert request.headers['Authorization'] == 'secret'
        if request.url.path == '/v1/projects/sage':
            return httpx.Response(200, json={'data': {'id': 'project-id'}})
        body = json.loads(request.content)
        assert 'attributes' not in body['query']
        assert 'attributes["deployment"]["environment"]["name"] == "production"' in body['variables']['roots']
        assert 'original' not in body['query']
        assert 'original\\"' in body['variables']['roots']
        assert 'attributes["session"]["id"] == "session:one"' in body['variables']['roots']
        assert 'attributes["session"]["id"] == "session:one"' in body['variables']['models']
        return httpx.Response(200, json={'data': {'node': {
            'requests': 2, 'errors': 1, 'tokens': 300, 'input_tokens': 200,
            'output_tokens': 100, 'cost': {'total': {'cost': .004}},
        }}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        data = await PhoenixTraceQuery(source).summary(start='2026-10-20T00:00:00Z',
                    end='2026-10-21T00:00:00Z', agent_id='original"', session_id='session:one', client=client)
    assert data['tokens'] == 300 and data['errors'] == 1
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_graphql_error_is_not_presented_as_empty_data():
    source = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix')
    def handle(request):
        if request.url.path.startswith('/v1/projects/'):
            return httpx.Response(200, json={'data': {'id': 'project-id'}})
        return httpx.Response(200, json={'errors': [{'message': 'private upstream detail'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match='Phoenix query failed'):
            await PhoenixTraceQuery(source).spans(start='a', end='b', client=client)


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', ['encoding', 'response', 'bytes', 'requests'])
async def test_graphql_enforces_the_shared_query_budget_before_parsing(limit):
    from sagents.v2.runtime.observability.plugins._shared.query import query_budget

    source = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix',
                                 headers={'Accept-Encoding': 'gzip'})
    source.max_response_bytes = 128 if limit == 'response' else 1024
    body = json.dumps({'data': {'value': 'x' * (256 if limit == 'response' else 64)}}).encode()
    reads, dispatched = [], []

    class Wire(httpx.AsyncByteStream):
        async def __aiter__(self):
            reads.append(True)
            yield gzip.compress(body) if limit == 'encoding' else body

    def handle(request):
        dispatched.append(request)
        return httpx.Response(200, stream=Wire(), headers={
            'Content-Encoding': 'gzip' if limit == 'encoding' else 'identity',
        })

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            async with query_budget(max_bytes=128 if limit == 'bytes' else 4096,
                                    requests=1 if limit == 'requests' else 4):
                with pytest.raises(ValueError, match={
                    'encoding': 'encoding', 'response': 'response exceeds',
                    'bytes': 'byte budget', 'requests': 'request budget',
                }[limit]):
                    for _ in range(2 if limit in {'bytes', 'requests'} else 1):
                        await PhoenixTraceQuery(source)._graphql(client, 'query { node { id } }', {})
        assert all(request.headers['Accept-Encoding'] == 'identity' for request in dispatched)
        if limit == 'encoding':
            assert reads == []
        if limit == 'requests':
            assert len(dispatched) == 1
    finally:
        await source.close()


def test_embedded_endpoints_require_admin_and_share_time_filter(tmp_path, monkeypatch):
    service = make_test_service(tmp_path, trace_backend='phoenix',
                                phoenix_endpoint='http://phoenix/v1/traces')
    calls = []
    async def summary(self, **options):
        calls.append(options)
        return {'requests': 1, 'errors': 0, 'tokens': 100, 'input_tokens': 80,
                'output_tokens': 20, 'cost': .01}
    monkeypatch.setattr(PhoenixTraceQuery, 'summary', summary)
    with TestClient(create_app(service=service)) as client:
        for path in ['/traces/summary', '/trace-spans', '/trace-spans/'+'a'*16,
                     '/traces/'+'b'*32+'/spans']:
            assert client.get('/api/observability'+path).status_code == 401
        assert client.post('/api/auth/login', json={'username':'admin','password':'admin12345'}).status_code == 200
        links = client.get('/api/observability/services').json()['data']
        assert not any(item['id']=='phoenix' or item['external'] for item in links)
        assert client.get('/api/observability/traces/summary?start=invalid').status_code == 422
        assert client.get('/api/observability/traces/summary?start=2026-10-21T00:00:00Z&end=2026-10-20T00:00:00Z').status_code == 422
        response = client.get('/api/observability/traces/summary?agent_id=agent&session_id=session-one')
        assert response.status_code == 200
        assert response.json()['data']['tokens'] == 100
        assert calls[0]['agent_id'] == 'agent'
        assert calls[0]['session_id'] == 'session-one'
        assert client.get('/api/observability/traces/wrong/spans').status_code == 422
        client.post('/api/auth/register', json={'username':'viewer','password':'viewer12345'})
        client.post('/api/auth/login', json={'username':'viewer','password':'viewer12345'})
        for path in ['/traces/summary','/trace-spans','/trace-spans/'+'a'*16,
                     '/traces/'+'b'*32+'/spans']:
            assert client.get('/api/observability'+path).status_code == 403


@pytest.mark.asyncio
async def test_metadata_pagination_and_raw_span_are_separate_queries():
    source = ExternalDiagnostics(backend='phoenix', query_url='http://phoenix')
    raw = {'name':'model.request', 'context':{'span_id':'a'*16,'trace_id':'b'*32},
           'attributes':{'input.value':'original-'+'x'*100000}, 'events':[]}
    def handle(request):
        if request.url.path == '/v1/projects/sage':
            return httpx.Response(200, json={'data':{'id':'project'}})
        if request.method == 'GET':
            assert request.url.params['span_id'] == 'a'*16
            return httpx.Response(200,json={'data':[raw]})
        body = json.loads(request.content)
        assert body['variables']['cursor'] == 'page-2'
        assert 'attributes["session"]["id"] == "session:one"' in body['variables']['condition']
        assert 'input' not in body['query'] and 'attributes' not in body['query']
        row = dict(span_id='a'*16, name='model.request', span_kind='LLM', status_code='OK',
                   start_time='2026-10-20T00:00:00Z',
                   trace={'trace_id':'b'*32,'num_spans':2,'error_count':0,'session':{'session_id':'session:one'}},
                   attributes={'secret':'must-not-be-returned'})
        return httpx.Response(200,json={'data':{'node':{'spans':{
            'edges':[{'node':row}], 'pageInfo':{'hasNextPage':True,'endCursor':'page-3'}}}}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        dashboard = PhoenixTraceQuery(source)
        page = await dashboard.spans(start='a',end='b',kind='LLM',session_id='session:one',cursor='page-2',client=client)
        assert page['next_cursor'] == 'page-3'
        assert 'attributes' not in page['items'][0]
        assert page['items'][0]['session_id'] == 'session:one'
        record = await dashboard.span('a'*16,client=client)
        assert cast("Any", record)['attributes'] == raw['attributes']
