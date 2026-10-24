"""Small shared helpers for repository-owned, replayable benchmark adapters."""
from __future__ import annotations

import hashlib
import json
import re
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


def _scorable_observation(request, observation, *, allow_closed=False):
    if isinstance(observation, dict) and observation.get('state') == 'completed':
        return observation
    if allow_closed and isinstance(observation, dict) and len(request.get('conversation') or ()) <= 1:
        from sagents.v2.optimization.contracts import OptimizationCase, OptimizationObservation
        from sagents.v2.optimization.native_episode import close_single_turn_episode
        closed = close_single_turn_episode(OptimizationObservation.model_validate(observation),
            OptimizationCase.model_validate(request['case']))
        if closed is not None:
            return closed.model_dump(mode='json')
    raise ValueError('Scoring requires completed or verified closed native observations')


def native_events(request, *, allow_closed=False):
    """Read canonical items, deduplicating cumulative histories by item identity.

    A proposed call without a completed tool result is not execution evidence.
    Do not accept caller-supplied scores, external files or trajectory paths.
    """
    events, seen = [], {}
    turns = request.get('conversation') or [{'target': request['observation']}]
    for turn in turns:
        observation = turn.get('target', turn.get('observation'))
        observation = _scorable_observation(request, observation, allow_closed=allow_closed)
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


def native_skill_read(request, call, result):
    """Accept only a bound successful built-in Skill load, never arbitrary tools.

    Loading an enabled instruction changes no benchmark state. It is auxiliary
    evidence, not an environment action or a source of reward. Declined loads,
    incomplete receipts, other tools and model-supplied claims remain invalid.
    """
    if call.get('tool_name') != 'load_skill' or result.get('error'):
        return False
    args, meta = call.get('arguments', {}), result.get('metadata', {})
    name = args.get('skill_name')
    if (not isinstance(name, str) or not name or set(args) - {'skill_name', 'session_id'}
            or meta.get('skill_name') != name or name not in meta.get('active_skills', ())
            or not re.fullmatch(r'(?:sha256:)?[a-f0-9]{64}', str(meta.get('content_hash', '')))):
        return False
    for turn in request.get('conversation') or [{'target': request['observation']}]:
        observation = _scorable_observation(request, turn.get('target', turn.get('observation')), allow_closed=True)
        evidence = observation.get('evidence', {})
        if evidence.get('runtime_events_truncated'):
            continue
        identity = call.get('tool_call_id')
        envelopes = [item for item in evidence.get('final_items', ())
                     if item.get('data', {}).get('tool_call_id') == identity]
        calls = [item for item in envelopes if item.get('data') == call]
        results = [item for item in envelopes if item.get('data') == result]
        if len(calls) != 1 or len(results) != 1:
            continue
        c, r = calls[0], results[0]
        run, step = c.get('run_id'), c.get('step_id')
        if (not run or not step or run != evidence.get('run_id')
                or r.get('run_id') != run or r.get('step_id') != step
                or r.get('status') != 'completed' or not r.get('item_id')):
            continue
        events = [e for e in evidence.get('runtime_events', ())
                  if e.get('run_id') == run and e.get('step_id') == step
                  and e.get('data', {}).get('tool_call_id') == identity]
        starts = [e['data'] for e in events if e.get('type') == 'tool.call.proposed']
        ends = [e['data'] for e in events if e.get('type') == 'tool.call.succeeded']
        if len(starts) == len(ends) == 1:
            start, end = starts[0], ends[0]
            # The native dispatcher binds the active session even when the
            # model omits this optional argument. It is not model authority.
            bound_args = {**args, 'session_id': evidence.get('session_id')}
            if (evidence.get('session_id') and start.get('tool_name') == 'load_skill'
                    and start.get('arguments') == bound_args
                    and start.get('operation_id') and start['operation_id'] == end.get('operation_id')
                    and end.get('result_item_id') == r['item_id']
                    and end.get('state') == 'completed' and not end.get('error')):
                return True
    return False


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
            db.execute('CREATE TABLE IF NOT EXISTS effect_sequence (id INTEGER PRIMARY KEY, value INTEGER NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT context,data FROM state WHERE id=1').fetchone()
            if row and row[0] != identity:
                raise ValueError('State directory belongs to a different case')
            state = json.loads(row[1]) if row else adapter.initial(context)
            state, result, error = adapter.call(context, state, name, arguments or {})
            prior = db.execute('SELECT value FROM effect_sequence WHERE id=1').fetchone()
            sequence = prior[0] + 1 if prior else 1
            db.execute('INSERT OR REPLACE INTO effect_sequence VALUES(1,?)', (sequence,))
            db.execute('INSERT OR REPLACE INTO state VALUES(1,?,?)', (identity, json.dumps(state)))
            db.commit()
        args.state.chmod(0o600)
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return CallToolResult(content=[TextContent(type='text', text=text)], isError=bool(error),
            _meta={'sage_rsi_effect_order': {'protocol': 'sage.rsi.mcp-effect-order/v1',
                'case_instance': hashlib.sha256(str(args.state.resolve()).encode()).hexdigest(),
                'sequence': sequence}})

    async def run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    asyncio.run(run())
