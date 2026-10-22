"""Standard per-case stdio MCP binding; no dataset-specific routing or code."""
from __future__ import annotations

import json

from sagents.v2.tool.plugins.mcp import McpToolPlugin

CASE_PROTOCOL = 'sage.rsi.case/v1'
CASE_CONTEXT_ENV = 'SAGE_RSI_CASE_CONTEXT_FILE'
ISOLATION_ENV = 'SAGE_RSI_CASE_PROTOCOL'


class McpCaseEnvironment:
    """Only explicitly opted-in local simulations can receive unattended writes.

    The server must honor the per-case state directory contract. This is a
    trusted server declaration, not an OS sandbox or arbitrary MCP isolation.
    """

    def __init__(self, servers, *, session_factory=None):
        self.servers = tuple(servers)
        if not self.servers:
            raise ValueError('case environment requires MCP servers')
        for server in self.servers:
            if server.protocol != 'stdio' or server.env.get(ISOLATION_ENV) != CASE_PROTOCOL:
                raise ValueError('RSI MCP requires an explicitly configured per-case stdio simulation')
        self.session_factory = session_factory
        self.fingerprint = McpToolPlugin.servers_fingerprint(self.servers)

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
        return McpToolPlugin(servers, session_factory=self.session_factory)
