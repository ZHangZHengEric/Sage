"""The Server filters host tools before exposing them to SAgents."""

from types import SimpleNamespace

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.tool.contracts import ToolCall, ToolDefinition, ReconcileResult, ReconcileState
from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext

CONTEXT = RequestContext(actor=ActorRef(principal_id="agent", principal_type=PrincipalType.AGENT))

from app.v2.server.runtime.integrations.external_tools import ScopedExternalTools


class Provider(InMemoryToolCatalog):
    def __init__(self):
        super().__init__(tuple(ToolDefinition(name=name, description=name, input_schema={'type': 'object'})
                               for name in ('mcp_read', 'mcp_write')))
        self.executed = []
        self.reconciled = []
        self.released = []

    async def execute(self, call, context):
        self.executed.append(call.tool_name)
        return call.tool_name

    async def reconcile(self, operation_id, context):
        self.reconciled.append(operation_id)
        return ReconcileResult(operation_id=operation_id, state=ReconcileState.SUCCEEDED)

    def release_run(self, run_id):
        self.released.append(run_id)


def call(name, run='root'):
    return ToolCall(tool_call_id='call', tool_name=name, arguments={}, operation_id='op',
                    idempotency_key='key', owner_run_id=run)


def scoped():
    provider = Provider()
    grants = {'root': ('mcp_read',), 'child': ('mcp_write',), 'empty': (), 'unset': None, 'narrowed': (), 'default': None, 'wide': ('mcp_read', 'mcp_write')}
    async def command_reader(run_id):
        return SimpleNamespace(agent_id=run_id, config=SimpleNamespace(enabled_tools=grants[run_id]))
    agents = {name: SimpleNamespace(tools=names) for name, names in {'root': ('mcp_read',), 'child': ('mcp_write',), 'narrowed': ('mcp_read',), 'default': ('mcp_read',), 'wide': ('mcp_read',)}.items()}
    tools = ScopedExternalTools(provider, agents)
    tools.bind(command_reader)
    return tools, provider


@pytest.mark.parametrize('run, names', [('root', ['mcp_read']), ('child', ['mcp_write']), ('empty', []), ('unset', []), ('narrowed', []), ('default', ['mcp_read']), ('wide', ['mcp_read'])])
async def test_server_filters_each_runs_catalog_and_direct_lookup(run, names):
    tools, _ = scoped()
    assert [tool.name for tool in await tools.list_tools(run_id=run)] == names
    for name in ('mcp_read', 'mcp_write'):
        if name in names:
            assert (await tools.get_tool(name, run_id=run)).name == name
        else:
            with pytest.raises(SageV2Error):
                await tools.get_tool(name, run_id=run)


async def test_server_blocks_direct_execution_and_retains_recovery_and_cleanup():
    tools, provider = scoped()
    with pytest.raises(SageV2Error):
        await tools.execute(call('mcp_write'), CONTEXT)
    assert provider.executed == []
    assert await tools.execute(call('mcp_read'), CONTEXT) == 'mcp_read'
    assert (await tools.reconcile('op', CONTEXT)).state == ReconcileState.SUCCEEDED
    await tools.release_run('root')
    assert provider.released == ['root']
    assert (await tools.reconcile('op', CONTEXT)).state == ReconcileState.UNKNOWN
    assert provider.reconciled == ['op']


async def test_recovered_calls_are_authorized_before_reconciliation():
    tools, provider = scoped()
    assert (await tools.reconcile_call(call('mcp_write'), CONTEXT)).state == ReconcileState.UNKNOWN
    assert provider.reconciled == []
    assert (await tools.reconcile_call(call('mcp_read'), CONTEXT)).state == ReconcileState.SUCCEEDED
    assert provider.reconciled == ['op']


def test_dependency_receives_its_own_external_tools(tmp_path, monkeypatch):
    from copy import deepcopy
    from fastapi.testclient import TestClient
    from app.v2.server.main import create_app
    from tests.app.v2.server.conftest import make_test_service, register_and_login, scripted_hello

    model = scripted_hello()
    service = make_test_service(tmp_path, model_provider=model)
    provider = Provider()
    monkeypatch.setattr(service.mcp_plugins, 'get', lambda *args: provider)
    with TestClient(create_app(service=service)) as client:
        headers = {'Authorization': f'Bearer {register_and_login(client)}'}
        parent = client.get('/api/agent-packages/template', headers=headers).json()['data']
        child = deepcopy(parent)
        child['manifest']['metadata']['id'] += '.child'
        child['manifest']['agents']['assistant']['tools'].append('mcp_write')
        parent['manifest']['agents']['assistant']['tools'].append('mcp_read')
        parent['manifest']['agents']['assistant']['entrypoint'] = {'type': 'flow', 'flow': 'main'}
        parent['manifest']['flows'] = {'main': {
            'version': '1', 'start': 'child',
            'nodes': [{'id': 'child', 'type': 'agent', 'agent': 'worker'}, {'id': 'end', 'type': 'end'}],
            'edges': [{'from': 'child', 'to': 'end'}],
        }}
        parent['dependencies'] = {'worker': child}
        response = client.post('/api/agent-package', headers=headers, json={
            'threadId': 'scope-child', 'runId': 'scope-child-run',
            'messages': [{'id': 'm', 'role': 'user', 'content': 'hello'}],
            'tools': [], 'context': [], 'state': {}, 'agent_package': parent,
        })
        assert response.status_code == 200, response.text
        assert '"RUN_FINISHED"' in response.text, response.text
    assert model.requests
    names = {tool.name for tool in model.requests[0].tools}
    assert names & {'mcp_read', 'mcp_write'} == {'mcp_write'}
