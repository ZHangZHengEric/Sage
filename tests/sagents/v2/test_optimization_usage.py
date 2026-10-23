from types import SimpleNamespace

import pytest

from sagents.v2.contracts.items import UsageSummary
from sagents.v2.optimization.runner import execution_usage


class EventStore:
    def __init__(self, events):
        self.events = events
        self.reads = 0

    async def read_events(self, run_id, *, after_sequence, limit):
        self.reads += 1
        return [e for e in self.events if e.run_sequence > after_sequence][:limit]


def event(sequence, usage=None):
    return SimpleNamespace(run_sequence=sequence,
        data=SimpleNamespace(kind='usage' if usage else 'tool', usage=usage))


@pytest.mark.asyncio
async def test_suspended_and_resumed_run_usage_is_incremental_and_not_limited_by_trace_capture():
    first = UsageSummary(reported=True, input_tokens=100, output_tokens=30,
        cached_input_tokens=20, reasoning_tokens=5, cost=.3)
    second = UsageSummary(reported=True, input_tokens=200, output_tokens=50,
        cached_input_tokens=40, reasoning_tokens=10, cost=.5)
    events = [event(1, first), *(event(i) for i in range(2, 604)), event(604, second)]
    store = EventStore(events)
    before = await execution_usage(store, 'same-run', after_sequence=0, last_sequence=1)
    after = await execution_usage(store, 'same-run', after_sequence=1, last_sequence=604)
    whole = await execution_usage(store, 'same-run', after_sequence=0, last_sequence=604)
    for key in ('input_tokens', 'output_tokens', 'cached_input_tokens', 'reasoning_tokens', 'cost'):
        assert before[key] + after[key] == pytest.approx(whole[key])
    assert whole['input_tokens'] == 300 and whole['cached_input_tokens'] == 60
    assert whole['reported'] and after['input_tokens'] == 200
    assert store.reads > 3


@pytest.mark.asyncio
async def test_unknown_usage_and_partial_cost_are_distinct_from_reported_zero():
    empty = await execution_usage(EventStore([]), 'run', after_sequence=0, last_sequence=0)
    assert not empty['reported'] and empty['cost'] is None
    zero = await execution_usage(EventStore([event(1, UsageSummary(reported=True, cost=0))]),
        'run', after_sequence=0, last_sequence=1)
    assert zero['reported'] and zero['input_tokens'] == 0 and zero['cost'] == 0
    partial = await execution_usage(EventStore([
        event(1, UsageSummary(reported=True, input_tokens=20, cost=.1)),
        event(2, UsageSummary(reported=True, input_tokens=30))]),
        'run', after_sequence=0, last_sequence=2)
    assert partial['reported'] and partial['input_tokens'] == 50 and partial['cost'] is None
    missing = await execution_usage(EventStore([event(1, UsageSummary(reported=False, input_tokens=10))]),
        'run', after_sequence=0, last_sequence=1)
    assert not missing['reported'] and missing['input_tokens'] == 10
