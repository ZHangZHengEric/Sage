"""Real stdio transport verifies the standard per-case environment contract."""
import json
import sys
from uuid import uuid4

import pytest

from evaluation_datasets.tau_bench.runtime import ROOT
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.optimization.contracts import OptimizationCase
from sagents.v2.optimization.environment import CASE_PROTOCOL, ISOLATION_ENV, McpCaseEnvironment
from sagents.v2.tool.contracts import ToolCall
from sagents.v2.tool.plugins.mcp import McpServerConfig


@pytest.mark.asyncio
async def test_real_official_stdio_writes_are_private_to_the_case_workspace(tmp_path):
    config = McpServerConfig(name='TauRetail', protocol='stdio', command=sys.executable,
        args=('-m', 'evaluation_datasets.tau_bench.mcp_server', '--state', str(tmp_path / 'ordinary.sqlite3')),
        env={'PYTHONPATH': str(ROOT.parents[1]), ISOLATION_ENV: CASE_PROTOCOL})
    binding = McpCaseEnvironment((config,))
    case = OptimizationCase(id='isolation', input='Update my address', rubric='Authorized update')
    plugins = []
    for name in ('candidate-a', 'candidate-b'):
        workspace = tmp_path / name
        workspace.mkdir()
        plugin = binding.for_workspace(workspace, case)
        tools = await plugin.list_tools(run_id='isolation')
        assert len(tools) == 16
        assert 'mcp_TauRetail_calculate' in {tool.name for tool in tools}
        plugins.append(plugin)
    db = json.loads((ROOT / 'data/tau2/domains/retail/db.json').read_text())
    user_id, user = next(iter(db['users'].items()))
    context = RequestContext(actor=ActorRef(principal_id='test', principal_type=PrincipalType.USER))
    async def call(plugin, name, arguments):
        token = uuid4().hex
        result = await plugin.execute(ToolCall(tool_call_id=token, operation_id=token,
            idempotency_key=token, owner_run_id='isolation', owner_agent_id='target',
            tool_name='mcp_TauRetail_' + name, arguments=arguments), context)
        assert result.error is None
        receipt = result.metadata["mcp_meta"]["sage.rsi.execution"]
        assert receipt["protocol"] == "sage.rsi.execution-order/v1"
        assert type(receipt["sequence"]) is int and receipt["sequence"] > 0
        blocks = [block.value for block in result.content if block.kind == 'json']
        return blocks[0] if blocks else json.loads(''.join(block.text for block in result.content if block.kind == 'text'))
    address = {**user['address'], 'address1': 'Isolated candidate address'}
    await call(plugins[0], 'modify_user_address', {'user_id': user_id, **address})
    a = await call(plugins[0], 'get_user_details', {'user_id': user_id})
    b = await call(plugins[1], 'get_user_details', {'user_id': user_id})
    assert a['address'] == address
    assert b['address'] == user['address']
    assert not (tmp_path / 'ordinary.sqlite3').exists()
    assert (tmp_path / 'candidate-a/environment/state/retail.sqlite3').is_file()
    assert (tmp_path / 'candidate-b/environment/state/retail.sqlite3').is_file()
