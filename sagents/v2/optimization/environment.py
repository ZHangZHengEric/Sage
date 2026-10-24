"""Standard per-case stdio MCP binding; no dataset-specific routing or code."""
from __future__ import annotations

import json
import hashlib

from sagents.v2.tool.plugins.mcp import McpToolPlugin

CASE_PROTOCOL = 'sage.rsi.case/v1'
CASE_CONTEXT_ENV = 'SAGE_RSI_CASE_CONTEXT_FILE'
ISOLATION_ENV = 'SAGE_RSI_CASE_PROTOCOL'


class McpCaseEnvironment:
    """Only explicitly opted-in local simulations can receive unattended writes.

    The server must honor the per-case state directory contract. This is a
    trusted server declaration, not an OS sandbox or arbitrary MCP isolation.
    """

    def __init__(self, servers, *, session_factory=None, terminal_on_done=False):
        self.servers = tuple(servers)
        if not self.servers:
            raise ValueError('case environment requires MCP servers')
        for server in self.servers:
            if server.protocol != 'stdio' or server.env.get(ISOLATION_ENV) != CASE_PROTOCOL:
                raise ValueError('RSI MCP requires an explicitly configured per-case stdio simulation')
        self.session_factory = session_factory
        self.terminal_on_done = terminal_on_done
        self.fingerprint = McpToolPlugin.servers_fingerprint(self.servers)
        if terminal_on_done:
            self.fingerprint = hashlib.sha256((self.fingerprint + ':terminal-on-done/v1').encode()).hexdigest()

    async def definitions(self):
        return await McpToolPlugin(self.servers, session_factory=self.session_factory).list_tools(run_id='rsi-case-preflight')

    def for_workspace(self, workspace, case):
        if case is None:
            raise ValueError('case environment cannot run without case context')
        state = workspace / 'environment'
        state.mkdir(mode=0o700)
        context_file = state / 'context.json'
        context_file.write_text(json.dumps({'protocol': CASE_PROTOCOL, 'case_id': case.id,
            'context': case.environment_context, 'state_directory': str(state / 'state')}, ensure_ascii=False))
        context_file.chmod(0o600)
        servers = tuple(s.model_copy(update={'env': {**s.env, CASE_CONTEXT_ENV: str(context_file)}}) for s in self.servers)
        return CaseMcpToolPlugin(servers, session_factory=self.session_factory,
            terminal_on_done=self.terminal_on_done)


class CaseMcpToolPlugin(McpToolPlugin):
    """Only successful, complete results from the bound case server can end it."""

    def __init__(self, *args, terminal_on_done=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.terminal_on_done = terminal_on_done

    def _project_result(self, call, server, remote_name, response):
        result = super()._project_result(call, server, remote_name, response)
        if not self.terminal_on_done or result.error or result.metadata.get('mcp_result_truncated'):
            return result
        try:
            value = json.loads(''.join(block.text for block in result.content if block.kind == 'text'))
        except (ValueError, TypeError):
            return result
        if isinstance(value, dict) and value.get('done') is True:
            return result.model_copy(update={'metadata': {**result.metadata, 'rsi_case_terminal': CASE_PROTOCOL}})
        return result


class CaseEnvironmentContinuationPolicy:
    """End at the host-attested environment boundary, before another model call."""

    def __init__(self, fallback_plugin):
        from sagents.v2.agent.policy.plugins.continuation import CompositeContinuationPolicy, ExplicitStatusContinuationPolicy
        choices = {CompositeContinuationPolicy.plugin_id: CompositeContinuationPolicy,
            ExplicitStatusContinuationPolicy.plugin_id: ExplicitStatusContinuationPolicy}
        if fallback_plugin not in choices:
            raise ValueError('Environment termination requires a supported deterministic continuation policy')
        self.fallback = choices[fallback_plugin]()

    async def decide(self, context):
        from sagents.v2.agent.policy.continuation import ContinuationAction, ContinuationDecision
        from sagents.v2.agent.policy.plugins._shared.continuation_rules import BudgetRule
        if (not context.pending_tool_calls and context.ledger and context.ledger[-1].role == 'tool'
                and context.ledger[-1].metadata.get('rsi_case_terminal') == CASE_PROTOCOL):
            budget = await BudgetRule().evaluate(context)
            if budget is not None:
                return budget
            return ContinuationDecision(action=ContinuationAction.COMPLETE_RUN,
                reason_code='environment.terminal', reason='Bound case environment reported done=true',
                metadata={'protocol': CASE_PROTOCOL, 'completion_basis': 'environment_terminal_result'})
        return await self.fallback.decide(context)
