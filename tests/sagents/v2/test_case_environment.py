import json

import pytest

from sagents.v2.optimization.contracts import OptimizationCase
from sagents.v2.optimization.environment import CASE_CONTEXT_ENV, CASE_PROTOCOL, ISOLATION_ENV, McpCaseEnvironment
from sagents.v2.tool.plugins.mcp import McpServerConfig


def server(**updates):
    return McpServerConfig.model_validate({'name': 'simulation', 'protocol': 'stdio', 'command': 'python',
        'env': {ISOLATION_ENV: CASE_PROTOCOL}, **updates})


def test_case_context_is_private_and_each_workspace_has_independent_state(tmp_path):
    binding = McpCaseEnvironment((server(),))
    case = OptimizationCase(id='one', input='Question', rubric='Rubric', reference_answer='HIDDEN ANSWER',
        environment_context={'initial_state': {'x': 1}})
    paths = []
    for name in ('a', 'b'):
        workspace = tmp_path / name
        workspace.mkdir()
        plugin = binding.for_workspace(workspace, case)
        path = plugin.servers[0].env[CASE_CONTEXT_ENV]
        from pathlib import Path
        context = json.loads(Path(path).read_text())
        assert context['context'] == {'initial_state': {'x': 1}}
        assert 'HIDDEN ANSWER' not in Path(path).read_text()
        assert context['protocol'] == CASE_PROTOCOL
        paths.append(context['state_directory'])
    assert paths[0] != paths[1]


@pytest.mark.parametrize('config', [server(env={}), server(protocol='streamable_http', command=None, url='https://example.invalid')])
def test_unisolated_or_remote_mcp_is_not_silently_granted_unattended_writes(config):
    with pytest.raises(ValueError, match='explicitly configured'):
        McpCaseEnvironment((config,))


@pytest.mark.parametrize('enabled,done,error,truncated,expected', [
    (True, True, False, False, True), (False, True, False, False, False),
    (True, False, False, False, False), (True, 'true', False, False, False),
    (True, True, True, False, False), (True, True, False, True, False),
])
def test_terminal_receipt_requires_opt_in_and_successful_complete_boolean_result(enabled, done, error, truncated, expected):
    from types import SimpleNamespace
    from sagents.v2.optimization.environment import CaseMcpToolPlugin
    plugin = CaseMcpToolPlugin((server(max_result_bytes=1 if truncated else 100000),), terminal_on_done=enabled)
    call = SimpleNamespace(tool_call_id='call', operation_id='operation')
    result = plugin._project_result(call, plugin.servers[0], 'step',
        {'content': [{'type': 'text', 'text': json.dumps({'done': done})}], 'isError': error,
         '_meta': {'rsi_case_terminal': CASE_PROTOCOL}})
    assert (result.metadata.get('rsi_case_terminal') == CASE_PROTOCOL) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize('role,receipt,terminal', [
    ('tool', True, True), ('tool', False, False), ('user', True, False), ('assistant', True, False),
])
async def test_only_host_tool_receipt_can_trigger_environment_completion(role, receipt, terminal):
    from sagents.v2.agent.policy.continuation import ContinuationContext
    from sagents.v2.model.contracts import ModelMessage, ModelResponse, ModelToolCall
    from sagents.v2.optimization.environment import CaseEnvironmentContinuationPolicy
    from sagents.v2.contracts.items import TextBlock
    message = ModelMessage(role=role, tool_call_id='step' if role == 'tool' else None,
        content=(TextBlock(text='{"done":true}'),), metadata={'rsi_case_terminal': CASE_PROTOCOL} if receipt else {})
    context = ContinuationContext(run_id='run', step_number=1, max_steps=10,
        response=ModelResponse(response_id='response', finish_reason='tool_calls', tool_calls=(ModelToolCall(tool_call_id='step',name='step',arguments={}),)),
        ledger=(message,))
    result = await CaseEnvironmentContinuationPolicy('sage.agent.continuation.deterministic').decide(context)
    assert (result.reason_code == 'environment.terminal') is terminal


def test_environment_done_opt_in_changes_frozen_fingerprint_without_relabeling_legacy_datasets():
    from sagents.v2.optimization.dataset import DatasetEnvironment
    assert McpCaseEnvironment((server(),)).fingerprint != McpCaseEnvironment((server(),), terminal_on_done=True).fingerprint
    assert 'terminal_on_done' not in DatasetEnvironment(mcp_servers=['simulation']).model_dump()
    assert DatasetEnvironment(mcp_servers=['simulation'],terminal_on_done=True).model_dump()['terminal_on_done'] is True
