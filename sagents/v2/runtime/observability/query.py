"""Bounded external query I/O and Phoenix's content-free SpanQuery projection.

Wire format follows Phoenix's /v1/spans SpanQuery and JSON table multipart API.
https://github.com/Arize-ai/phoenix/blob/main/src/phoenix/server/api/routers/v1/spans.py
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
import json
import time
import httpx


@dataclass
class QueryBudget:
    deadline: float
    bytes_left: int
    requests_left: int

    def request(self):
        self.requests_left -= 1
        if self.requests_left < 0:
            raise ValueError('trace query request budget exceeded')
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('trace query time budget exceeded')
        return remaining

    def consume(self, size):
        self.bytes_left -= size
        if self.bytes_left < 0:
            raise ValueError('trace query byte budget exceeded')


_budget = ContextVar('sage_observation_query_budget', default=None)


@asynccontextmanager
async def query_budget(*, seconds=25, max_bytes=64 * 1024 * 1024, requests=128):
    if _budget.get() is not None:
        yield
        return
    import asyncio
    token = _budget.set(QueryBudget(time.monotonic() + seconds, max_bytes, requests))
    try:
        async with asyncio.timeout(seconds):
            yield
    finally:
        _budget.reset(token)


async def request(source, client, path, params, *, method='GET', body=None, headers=None):
    budget = _budget.get()
    timeout = min(source.timeout, budget.request()) if budget else source.timeout
    request_headers = httpx.Headers({**source.headers, **(headers or {})})
    request_headers['Accept-Encoding'] = 'identity'
    async with client.stream(method, source.query_url + path, params=params,
                             headers=request_headers, json=body,
                             timeout=timeout, follow_redirects=False) as response:
        response.raise_for_status()
        if response.headers.get('content-encoding', '').strip().lower() not in {'', 'identity'}:
            raise ValueError('trace query response uses an unsupported content encoding')
        content = bytearray()
        async for chunk in response.aiter_bytes():
            if budget:
                budget.consume(len(chunk))
            if len(content) + len(chunk) > source.max_response_bytes:
                raise ValueError('trace query response exceeds limit')
            content.extend(chunk)
        return bytes(content), response.headers.get('content-type', '')


def attribute(key):
    return 'attributes' + ''.join('[' + json.dumps(part) + ']' for part in key.split('.'))


def table_rows(content, content_type):
    message = BytesParser(policy=policy.default).parsebytes(
        ('Content-Type: ' + content_type + '\r\nMIME-Version: 1.0\r\n\r\n').encode() + content)
    if not message.is_multipart():
        raise ValueError('Phoenix SpanQuery did not return a multipart table')
    parts = list(message.iter_parts())
    if len(parts) != 1 or parts[0].get_content_type() != 'application/json':
        raise ValueError('Invalid Phoenix SpanQuery response')
    table = json.loads(parts[0].get_payload(decode=True))
    # Phoenix prefixes table-schema column/index labels to preserve their names.
    return [{key.split('_', 1)[1]: value for key, value in row.items()}
            for row in table['data']]


async def performance_spans(source, client, *, start, end, agent_id=''):
    fields = ['name', 'start_time', 'context.trace_id', 'context.span_id']
    attributes = ['session_id', 'run_id', 'agent_id', 'sage.performance.format', 'sage.performance.data',
                  'sage.performance.incomplete']
    projection = {key: {'key': key} for key in fields}
    projection.update({key: {'key': attribute(key)} for key in attributes})
    base = ['name == "agent.run"',
            f'{attribute("sage.performance.service")} == {json.dumps(source.service)}',
            f'{attribute("sage.performance.environment")} == {json.dumps(source.environment)}',
            f'{attribute("sage.performance.format")} == "events/v3"']
    if agent_id:
        base.append(f'{attribute("agent_id")} == {json.dumps(agent_id)}')

    async def query(extra, limit):
        body = {'queries': [{'select': projection,
                            'filter': {'condition': ' and '.join([*base, *extra])},
                            'index': {'key': 'context.span_id'}}], 'limit': limit}
        content, content_type = await request(source, client, '/v1/spans',
                                             {'project_name': source.project}, method='POST', body=body,
                                             headers={'Accept': 'application/json'})
        import asyncio
        rows = await asyncio.to_thread(table_rows, content, content_type)
        return [{'name': row['name'], 'start_time': row['start_time'],
                 'context': {'span_id': row['context.span_id'], 'trace_id': row['context.trace_id']},
                 'attributes': {key: row.get(key) for key in attributes}} for row in rows]

    # Filter SDK entry time directly, not execution span start_time. In particular
    # never expand a historical cohort through the current wall clock.
    dates = [datetime.fromtimestamp(value, timezone.utc).isoformat() for value in (start, end)]
    entry = attribute('sage.performance.started_at')
    found = await query([f'{entry} >= {json.dumps(dates[0])}', f'{entry} < {json.dumps(dates[1])}'], source.max_spans + 1)
    truncated = len(found) > source.max_spans
    ids = sorted({row['attributes']['run_id'] for row in found[:source.max_spans]})
    spans = []
    for offset in range(0, len(ids), 100):
        # Membership is an OR over Run ids. Repeated REST attributes are AND,
        # and therefore cannot express this batch without the SpanQuery DSL.
        batch = await query([f'{attribute("run_id")} in {json.dumps(ids[offset:offset + 100])}'],
                            source.max_spans - len(spans) + 1)
        spans.extend(batch)
        if len(spans) > source.max_spans:
            return spans[:source.max_spans], True
    return spans, truncated


class QueryCache:
    """Short, byte-bounded result cache; failures are never cached.

    Pending work owns its I/O lifecycle, so a cancelled HTTP waiter cannot
    cancel a shared query or retain the caller's unfinished socket.
    """
    def __init__(self, *, ttl=5, max_entries=32, max_bytes=8 * 1024 * 1024):
        self.ttl, self.max_entries, self.max_bytes = ttl, max_entries, max_bytes
        self._cached, self._pending = {}, {}
        self._closed = False

    async def get(self, key, build):
        import asyncio
        import copy
        if self._closed:
            raise ValueError("observation query cache is closed")
        loop = asyncio.get_running_loop()
        pending_key = (loop, key)
        now = time.monotonic()
        self._cached = {k: v for k, v in self._cached.items() if v[0] > now}
        cached = self._cached.get(key)
        if cached:
            return copy.deepcopy(cached[2])
        task = self._pending.get(pending_key)
        if task is None:
            if len(self._pending) >= self.max_entries:
                raise ValueError('too many pending observation queries')
            async def execute():
                try:
                    async with query_budget():
                        result = await build()
                    size = len(json.dumps(result, ensure_ascii=False).encode())
                    if size <= self.max_bytes:
                        while self._cached and (len(self._cached) >= self.max_entries or
                              sum(v[1] for v in self._cached.values()) + size > self.max_bytes):
                            self._cached.pop(next(iter(self._cached)))
                        self._cached[key] = (time.monotonic() + self.ttl, size, result)
                    return result
                finally:
                    self._pending.pop(pending_key, None)
            task = self._pending[pending_key] = asyncio.create_task(execute())
            # Retrieve abandoned exceptions even if every waiter disconnected.
            task.add_done_callback(lambda finished: finished.exception() if not finished.cancelled() else None)
        return copy.deepcopy(await asyncio.shield(task))

    async def close(self):
        import asyncio
        self._closed = True
        self._cached.clear()
        current = asyncio.get_running_loop()
        async def cancel(task):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        waits = []
        for task in tuple(self._pending.values()):
            loop = task.get_loop()
            if loop is current:
                waits.append(cancel(task))
            elif loop.is_running():
                waits.append(asyncio.wrap_future(asyncio.run_coroutine_threadsafe(cancel(task), loop)))
        if waits:
            await asyncio.gather(*waits)
        self._pending.clear()
