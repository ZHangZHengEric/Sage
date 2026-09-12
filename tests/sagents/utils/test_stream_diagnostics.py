import asyncio
import time
from types import SimpleNamespace

import pytest
from sagents.utils import request_latency as metrics
from sagents.utils.stream_yield import StreamYieldBudget
from common.utils.stream_merge import interleave_message_and_progress


def test_sync_scope_separates_cpu_and_wall_preserves_errors_and_bounds(monkeypatch):
    clock = SimpleNamespace(wall=0.0, cpu=0.0)
    monkeypatch.setattr(metrics.time, 'perf_counter', lambda: clock.wall)
    monkeypatch.setattr(metrics.time, 'thread_time', lambda: clock.cpu)
    budget = metrics.RequestLatency()
    @metrics.timed_stream_sync('ledger.test')
    def fail():
        clock.wall += .2
        clock.cpu += .03
        raise ValueError('expected')
    with budget.activate(), pytest.raises(ValueError, match='expected'):
        fail()
    assert budget.stream_snapshot()['ledger.test'] == {
        'count': 1, 'total_ms': 200, 'max_ms': 200, 'cpu_ms': 30, 'cpu_count': 1}
    for i in range(1000):
        budget.add_stream_timing(str(i), .1)
    assert len(budget.stream_stages) == 24


@pytest.mark.asyncio
async def test_competing_cpu_is_scheduler_wait_not_this_requests_sync_cpu(monkeypatch):
    monkeypatch.setattr(metrics, '_emit', lambda _: None)
    one, two = metrics.RequestLatency(), metrics.RequestLatency()
    clock = SimpleNamespace(now=0.0)
    checkpoint = StreamYieldBudget(clock=lambda: clock.now)
    @metrics.timed_stream_sync('ledger.injected_cpu')
    def spin():
        until = time.thread_time() + .005
        while time.thread_time() < until:
            pass
    async def competitor():
        with two.activate():
            spin()
    with one.activate():
        task = asyncio.create_task(competitor())
        clock.now = .006
        await checkpoint.checkpoint()
        await task
    wait = one.stream_snapshot()['stream.scheduler_yield']
    assert wait['total_ms'] >= 5
    assert wait['cpu_ms'] is None
    assert 'ledger.injected_cpu' not in one.stream_stages
    assert two.stream_snapshot()['ledger.injected_cpu']['cpu_ms'] >= 5


@pytest.mark.asyncio
async def test_queue_delays_progress_order_and_no_per_chunk_logging(monkeypatch):
    records = []
    monkeypatch.setattr(metrics, '_emit', records.append)
    budget = metrics.RequestLatency()
    queue = asyncio.Queue()
    async def messages():
        for i in range(300):
            yield i
        await queue.put({'progress': 'done'})
    output = []
    async for kind, item in interleave_message_and_progress(messages(), queue, latency_budget=budget):
        output.append((kind, item))
        if kind == 'message' and item == 0:
            await asyncio.sleep(.005)
    assert [v for k, v in output if k == 'message'] == list(range(300))
    assert ('tool_progress', {'progress': 'done'}) in output
    assert len(records) == 1
    record = records[0]
    assert record['operation'] == 'request.stream_delivery'
    assert record['stream_stages']['delivery.downstream_resume']['max_ms'] >= 5
    assert record['stream_stages']['delivery.queue_residence']['max_ms'] >= 5
    assert record['stream_gauges']['merge_queue_peak'] >= 300


@pytest.mark.asyncio
async def test_queue_error_propagates_and_diagnostics_disabled(monkeypatch):
    monkeypatch.setenv('SAGE_LATENCY_DIAGNOSTICS', '0')
    records = []
    monkeypatch.setattr(metrics, '_emit', records.append)
    budget = metrics.RequestLatency()
    async def messages():
        yield 1
        raise ValueError('stream failure')
    with pytest.raises(ValueError, match='stream failure'):
        async for _ in interleave_message_and_progress(messages(), asyncio.Queue(), latency_budget=budget):
            pass
    assert records == []
    assert budget.stream_stages == {}


def test_message_timing_does_not_serialize_payload_and_preserves_fields(monkeypatch):
    from sagents.context.session_context import SessionContext
    from sagents.context.messages.message import MessageChunk, MessageType
    ctx = SessionContext.__new__(SessionContext)
    ctx._message_timing = {}
    ctx._now_perf_ms = lambda: 100.0
    events = []
    ctx.record_timing_event = lambda *args, **kwargs: events.append((args, kwargs))
    msg = MessageChunk(role='assistant', content='text', message_id='m', metadata={'large': ['payload']})
    # to_dict normalizes enum fields, even if assigned after construction.
    msg.message_type = MessageType.DO_SUBTASK_RESULT
    msg.type = MessageType.DO_SUBTASK_RESULT
    expected = msg.to_dict()
    def forbidden():
        raise AssertionError('full payload serialization is unnecessary')
    monkeypatch.setattr(msg, 'to_dict', forbidden)
    ctx._record_message_timing(msg)
    stat = dict(ctx._message_timing['m'])
    assert stat['role'] == expected['role']
    assert stat['message_type'] == expected['message_type']
    assert stat['tool_call_id'] == expected.get('tool_call_id')
    assert len(events) == 1
    ctx._now_perf_ms = lambda: 200.0
    ctx._record_message_timing(msg)
    assert ctx._message_timing['m']['start_perf_ms'] == 100
    assert ctx._message_timing['m']['end_perf_ms'] == 200
    assert len(events) == 1
    assert msg.metadata == {'large': ['payload']}
    ctx._record_message_timing({'message_id': 'dict', 'role': 'tool', 'type': 'tool_call_result', 'tool_call_id': 'call'})
    assert ctx._message_timing['dict']['tool_call_id'] == 'call'
