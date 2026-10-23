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
