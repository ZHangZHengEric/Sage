"""Official retail business tools over stdio MCP with local simulated state.

This server exposes business tools only: no test tasks, expected answers, scoring
or evaluation controls are available to the executing agent.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys

from evaluation_datasets.tau_bench.runtime import ROOT, activate


class RetailState:
    def __init__(self, path, *, initial_state=None):
        self.path = Path(path)
        self.initial_state = initial_state

    def call(self, name, arguments):
        from tau2.domains.retail.data_model import RetailDB
        from tau2.domains.retail.tools import RetailTools
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Each stdio connection may be short-lived. Persist the complete simulated
        # DB transactionally, so writes survive subsequent tool connections.
        with sqlite3.connect(self.path, timeout=30) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, data TEXT NOT NULL)')
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT data FROM state WHERE id=1').fetchone()
            raw = row[0] if row else (ROOT / 'data/tau2/domains/retail/db.json').read_text()
            db = RetailDB.model_validate_json(raw)
            if row is None and self.initial_state is not None:
                from tau2.data_model.tasks import InitialState
                from tau2.domains.retail.environment import get_environment
                state = InitialState.model_validate(self.initial_state)
                environment = get_environment(db=db)
                environment.set_state(state.initialization_data, state.initialization_actions, state.message_history or [])
                db = environment.tools.db
            result = RetailTools(db).use_tool(name, **arguments)
            connection.execute('INSERT OR REPLACE INTO state(id,data) VALUES(1,?)', (db.model_dump_json(),))
            # Commit before returning. Failed official operations roll back.
            connection.commit()
        self.path.chmod(0o600)
        if hasattr(result, 'model_dump'):
            result = result.model_dump(mode='json')
        return result


def create_server(state_path, *, initial_state=None):
    from mcp.server import Server
    from mcp.types import TextContent, Tool
    from tau2.domains.retail.tools import RetailTools
    server = Server('TauRetail')
    tools = RetailTools(None).get_tools()
    state = RetailState(state_path, initial_state=initial_state)
    @server.list_tools()
    async def list_tools():
        return [Tool(name=name, description=tool.openai_schema['function']['description'],
            inputSchema=tool.openai_schema['function']['parameters']) for name, tool in tools.items()]
    @server.call_tool()
    async def call_tool(name, arguments):
        if name not in tools:
            raise ValueError('unknown official retail tool')
        result = await asyncio.to_thread(state.call, name, arguments)
        return [TextContent(type='text', text=result if isinstance(result, str) else json.dumps(result, ensure_ascii=False))]
    return server


async def serve(state_path, *, initial_state=None):
    from mcp.server.stdio import stdio_server
    server = create_server(state_path, initial_state=initial_state)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level='ERROR', backtrace=False, diagnose=False)
    activate()
    initial_state = None
    context_path = os.environ.get('SAGE_RSI_CASE_CONTEXT_FILE')
    if context_path:
        context = json.loads(Path(context_path).read_text())
        if context.get('protocol') != 'sage.rsi.case/v1':
            raise ValueError('unsupported RSI case environment protocol')
        args.state = Path(context['state_directory']) / 'retail.sqlite3'
        initial_state = context['context'].get('initial_state')
    asyncio.run(serve(args.state, initial_state=initial_state))


if __name__ == '__main__':
    main()
