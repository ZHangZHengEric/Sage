"""Real stdio proves that writes survive reconnects but never cross candidates."""
import json
import sys
from uuid import uuid4

import pytest

from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.optimization.contracts import OptimizationCase
from sagents.v2.optimization.environment import CASE_PROTOCOL, ISOLATION_ENV, McpCaseEnvironment
from sagents.v2.tool.contracts import ToolCall
from sagents.v2.tool.plugins.mcp import McpServerConfig


@pytest.mark.asyncio
@pytest.mark.parametrize('dataset,namespace,case_context', [
    ('bfcl', 'BFCL', {'task_id': 'multi_turn_base_0'}),
    ('toolsandbox', 'ToolSandbox', {'scenario': 'get_cellular'}),
])
async def test_case_state_is_private_persistent_and_has_no_admin_tools(tmp_path, dataset, namespace, case_context):
    if dataset == 'toolsandbox':
        pytest.importorskip('polars')
        pytest.importorskip('scipy')
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    ordinary = tmp_path / 'ordinary.sqlite3'
    config = McpServerConfig(name=namespace, protocol='stdio', command=sys.executable,
        args=('-m', f'evaluation_datasets.{dataset}.mcp_server', '--state', str(ordinary)),
        env={'PYTHONPATH': str(root), ISOLATION_ENV: CASE_PROTOCOL})
    binding = McpCaseEnvironment((config,))
    case = OptimizationCase(id='isolation', input='Use official simulation', rubric='Official state',
        environment_context=case_context)
    plugins = []
    for candidate in ('a', 'b'):
        workspace = tmp_path / candidate
        workspace.mkdir()
        plugin = binding.for_workspace(workspace, case)
        definitions = await plugin.list_tools(run_id='isolation')
        assert definitions
        assert not any(any(word in d.name.lower() for word in ('score', 'reset', 'evaluate')) for d in definitions)
        plugins.append(plugin)
    context = RequestContext(actor=ActorRef(principal_id='test', principal_type=PrincipalType.USER))
    async def call(plugin, name, arguments):
        token = uuid4().hex
        result = await plugin.execute(ToolCall(tool_call_id=token, operation_id=token,
            idempotency_key=token, owner_run_id='isolation', owner_agent_id='target',
            tool_name=f'mcp_{namespace}_{name}', arguments=arguments), context)
        assert result.error is None
        text = ''.join(block.text for block in result.content if block.kind == 'text')
        values = [block.value for block in result.content if block.kind == 'json']
        return text or json.dumps(values)
    if dataset == 'bfcl':
        await call(plugins[0], 'cd', {'folder': 'document'})
        await call(plugins[0], 'mkdir', {'dir_name': 'only_a'})
        assert 'only_a' in await call(plugins[0], 'ls', {})
        assert 'only_a' not in await call(plugins[1], 'ls', {})
    else:
        # get_cellular permits only the read tool. A different authorized scenario
        # exercises writes below; the discovery boundary must remain case-specific.
        assert 'True' in await call(plugins[0], 'get_cellular_service_status', {})
        assert 'True' in await call(plugins[1], 'get_cellular_service_status', {})
    assert not ordinary.exists()


@pytest.mark.asyncio
async def test_toolsandbox_device_write_survives_new_stdio_connection(tmp_path):
    pytest.importorskip('polars')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    context_path = tmp_path / 'context.json'
    context_path.write_text(json.dumps({'protocol': CASE_PROTOCOL, 'context': {'scenario': 'cellular_off'},
                                       'state_directory': str(tmp_path / 'state')}))
    parameters = StdioServerParameters(command=sys.executable,
        args=['-m', 'evaluation_datasets.toolsandbox.mcp_server', '--state', str(tmp_path / 'unused')],
        env={'PYTHONPATH': str(root), 'SAGE_RSI_CASE_CONTEXT_FILE': str(context_path)})
    for attempt in range(2):
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool('set_cellular_service_status', {'on': False})
                if attempt == 0:
                    assert not result.isError
                else:
                    # The official setter rejects a second identical transition.
                    assert result.isError
                    assert 'already disabled' in result.content[0].text
    from evaluation_datasets.toolsandbox.runtime import _set_state
    import sqlite3
    with sqlite3.connect(tmp_path / 'state/ToolSandbox.sqlite3') as db:
        state = json.loads(db.execute('SELECT data FROM state WHERE id=1').fetchone()[0])
    from tool_sandbox.common.execution_context import DatabaseNamespace
    assert _set_state(state).get_database(DatabaseNamespace.SETTING)['cellular'][0] is False
