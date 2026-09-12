"""Bounded offline reproduction of the ledger/display/queue streaming path.

No real model, tools, users or service calls. Run from repository root:
PYTHONPATH=. python scripts/diagnostics/mock_stream_latency.py --requests 4 --chunks 1000
The network timing is synthetic; this is not a production latency benchmark.
"""
import argparse
import asyncio
import json
import os
import tempfile
import time

from sagents.context.messages.message import MessageChunk
from sagents.context.session_context import SessionContext
from sagents.utils import request_latency as metrics
from sagents.utils.stream_yield import StreamYieldBudget
from common.services.chat_processor import ContentProcessor
from common.utils.stream_merge import interleave_message_and_progress


async def run(args):
    # Keep diagnostics in numeric request aggregates; no local per-request files.
    metrics._emit = lambda _: None
    budgets = []
    async def request(index, root):
        ctx = SessionContext(session_id=f'mock-{index}', user_id='mock', agent_id='mock', session_root_space=root)
        ctx.message_manager.add_messages([
            MessageChunk(role='user', content='history' * 100, message_id=f'h-{i}')
            for i in range(args.history)
        ])
        budget = metrics.RequestLatency()
        budget.session_id = f'mock-{index}'
        budgets.append(budget)
        async def tokens():
            for i in range(args.chunks):
                if i % args.network_every == 0:
                    await asyncio.sleep(args.network_delay_ms / 1000)
                yield i
        async def messages():
            with budget.activate():
                checkpoint = StreamYieldBudget()
                async for i in metrics.observe_stream(tokens(), True):
                    await checkpoint.checkpoint()
                    fields = {'content': 'x'}
                    if args.tool_deltas:
                        fields = {'tool_calls': [{'index': 0, 'id': 'call' if i == 0 else '', 'type': 'function',
                                   'function': {'name': 'mock' if i == 0 else '', 'arguments': 'x'}}]}
                    msg = MessageChunk(role='assistant', message_id='answer', **fields)
                    ctx.add_messages(msg)
                    yield ContentProcessor.clean_content(msg.to_dict())
        count = 0
        async for kind, payload in interleave_message_and_progress(messages(), asyncio.Queue(), latency_budget=budget):
            with metrics.stream_sync_stage('delivery.json_encode', budget):
                json.dumps(payload)
            count += 1
            if args.slow_consumer_ms and count % 64 == 0:
                await asyncio.sleep(args.slow_consumer_ms / 1000)
        assert count == args.chunks
        answer = ctx.message_manager.messages[-1]
        if args.tool_deltas:
            assert answer.tool_calls[0]['function']['arguments'] == 'x' * args.chunks
        else:
            assert answer.content == 'x' * args.chunks
        return budget.snapshot('mock.completed')
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='sage-mock-stream-') as root:
        results = await asyncio.gather(*(request(i, root) for i in range(args.requests)))
    print('MOCK', json.dumps({'settings': vars(args), 'wall_ms': round((time.perf_counter()-started)*1000, 2), 'requests': results}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests', type=int, default=3, choices=range(1, 9))
    parser.add_argument('--chunks', type=int, default=1000)
    parser.add_argument('--history', type=int, default=100)
    parser.add_argument('--slow-consumer-ms', type=float, default=0)
    parser.add_argument('--network-delay-ms', type=float, default=1)
    parser.add_argument('--network-every', type=int, default=64)
    parser.add_argument('--tool-deltas', action='store_true')
    parser.add_argument('--disable-diagnostics', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.chunks <= 5000 or not 0 <= args.history <= 500 or not 0 <= args.slow_consumer_ms <= 10:
        parser.error('chunks 1..5000, history 0..500, slow-consumer-ms 0..10 required')
    if not 0 <= args.network_delay_ms <= 10 or not 1 <= args.network_every <= 5000:
        parser.error('network-delay-ms 0..10, network-every 1..5000 required')
    if args.disable_diagnostics:
        os.environ['SAGE_LATENCY_DIAGNOSTICS'] = '0'
    asyncio.run(run(args))
