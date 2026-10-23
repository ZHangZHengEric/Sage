"""Small shared helpers for repository-owned, replayable benchmark adapters."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys


def activate(root, source):
    manifest = json.loads((root / 'upstream.json').read_text())
    for name, digest in manifest['files'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Pinned upstream file changed: {name}')
    path = str(root / source)
    if path not in sys.path:
        sys.path.insert(0, path)
    return manifest


def native_events(request):
    """Read canonical items, deduplicating cumulative histories by item identity.

    A proposed call without a completed tool result is not execution evidence.
    Do not accept caller-supplied scores, external files or trajectory paths.
    """
    events, seen = [], {}
    turns = request.get('conversation') or [{'target': request['observation']}]
    for turn in turns:
        observation = turn.get('target', turn.get('observation'))
        if not isinstance(observation, dict) or observation.get('state') != 'completed':
            raise ValueError('Scoring requires completed native observations')
        items = observation.get('evidence', {}).get('final_items')
        if not isinstance(items, list) or not items:
            raise ValueError('Scoring requires canonical native final_items')
        for envelope in items:
            item = envelope.get('data', {})
            identity = envelope.get('item_id')
            if identity is not None:
                if identity in seen:
                    if seen[identity] != item:
                        raise ValueError('Conflicting native item identity')
                    continue
                seen[identity] = item
            events.append(item)
    results = {e['tool_call_id']: e for e in events if e.get('kind') == 'tool_result'}
    for event in events:
        if event.get('kind') == 'tool_call':
            if event.get('tool_call_id') not in results:
                raise ValueError('Native tool call has no completed result')
    return events


def message_text(event):
    return ''.join(b.get('text', '') for b in event.get('content', []) if b.get('kind') == 'text')


def public_names(namespace, names):
    from sagents.v2.tool.plugins.mcp import McpToolPlugin
    return {McpToolPlugin._public_name(namespace, name): name for name in names}


def serve_cli(adapter, namespace):
    """A transactional JSON state survives short-lived stdio connections."""
    import argparse
    import asyncio
    import os
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import CallToolResult, TextContent, Tool

    parser = argparse.ArgumentParser()
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    context = None
    if context_file := os.environ.get('SAGE_RSI_CASE_CONTEXT_FILE'):
        payload = json.loads(Path(context_file).read_text())
        if payload.get('protocol') != 'sage.rsi.case/v1':
            raise ValueError('Unsupported per-case environment protocol')
        context = payload['context']
        args.state = Path(payload['state_directory']) / (namespace + '.sqlite3')
    server = Server(namespace)

    @server.list_tools()
    async def list_tools():
        return [Tool(name=f['name'], description=f.get('description', ''),
                     inputSchema=f['parameters']) for f in adapter.tools(context)]

    @server.call_tool()
    async def call_tool(name, arguments):
        if context is None:
            raise ValueError('Run this simulation through an imported RSI case; no case is active')
        if name not in {f['name'] for f in adapter.tools(context)}:
            raise ValueError('Tool is not available in this benchmark case')
        args.state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        identity = json.dumps(context, sort_keys=True)
        with sqlite3.connect(args.state, timeout=30) as db:
            db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, context TEXT, data TEXT)')
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT context,data FROM state WHERE id=1').fetchone()
            if row and row[0] != identity:
                raise ValueError('State directory belongs to a different case')
            state = json.loads(row[1]) if row else adapter.initial(context)
            state, result, error = adapter.call(context, state, name, arguments or {})
            db.execute('INSERT OR REPLACE INTO state VALUES(1,?,?)', (identity, json.dumps(state)))
            db.commit()
        args.state.chmod(0o600)
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return CallToolResult(content=[TextContent(type='text', text=text)], isError=bool(error))

    async def run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    asyncio.run(run())
