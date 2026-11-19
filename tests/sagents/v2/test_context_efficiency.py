from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Literal

from sagents.v2.model.provider import ModelProvider
from tests.sagents.v2.model_fixture import TEST_MODELS

import asyncio

import pytest

from sagents.v2.context import (
    ContextReductionScope,
)
from sagents.v2.context.runtime_metadata import RunMetadataContextProvider
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage


def message(text, role="assistant", **kwargs):
    return ModelMessage(role=cast("Literal['system', 'developer', 'user', 'assistant', 'tool']", role), content=(TextBlock(text=text),), **kwargs)


def scope(key="session"):
    return ContextReductionScope(context_key=key, session_id=key, run_id=key)


class Summary:
    def __init__(self, text="history summary"):
        self.requests = []
        self.text = text

    async def summarize(self, request):
        self.requests.append(request)
        return self.text


def test_workspace_memory_is_bounded_but_core_instructions_are_not_silently_cut():
    provider = RunMetadataContextProvider()
    memory = provider._identity_document("MEMORY", "记忆" * 100000, "zh")
    assert len(memory) < 4200
    assert "仅为节选" in memory
    with pytest.raises(SageV2Error):
        provider._identity_document("AGENT", "instruction " * 5000, "en")


def test_retired_estimated_budgets_load_but_are_never_enforced_or_reported():
    from sagents.v2.context import ContextBudget
    from sagents.v2.package.presets.factory import BuiltinPackageFactory
    from sagents.v2.package.manifest.resolver import CompositionResolver, PolicyCeiling

    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.context-zones",
    )
    resolver = CompositionResolver(models=TEST_MODELS)
    plain = resolver.resolve(package)
    data = package.model_dump(mode="json")
    agent_id = data["entrypoint"]["agent"]
    data["agents"][agent_id]["budgets"].update(
        system_tokens=12000, protected_recent_tokens=4096
    )
    data["policies"]["budgets"].update(system_tokens=8000, protected_recent_tokens=0)
    resolved = resolver.resolve(type(package).model_validate(data))

    ceiling = resolved.policy_ceilings[agent_id].model_dump()
    assert "max_system_tokens" not in ceiling
    assert "protected_recent_tokens" not in ceiling
    # Historical identity still distinguishes archives with explicit old values.
    # It is not a runtime limit and must not invalidate previously saved Runs.
    assert resolved.manifest_hash != plain.manifest_hash
    # Saved revisions and host budgets written before retirement still load.
    legacy = {**ceiling, "max_system_tokens": 16384, "protected_recent_tokens": None}
    assert PolicyCeiling.model_validate(legacy).model_dump() == ceiling
    budget = ContextBudget(max_input_tokens=1000, max_system_tokens=1, protected_recent_tokens=0)
    assert budget.model_dump() == ContextBudget(max_input_tokens=1000).model_dump()


def test_optimizer_cannot_tune_retired_budget_fields():
    from sagents.v2.optimization.contracts import OptimizationConstraints

    constraints = OptimizationConstraints.model_validate(
        {"editable_budget_fields": ["max_steps", "system_tokens", "protected_recent_tokens"]}
    )
    assert constraints.editable_budget_fields == ("max_steps",)


@pytest.mark.asyncio
async def test_summary_capacity_is_shared_across_plugin_instances():
    from sagents.v2.context import ModelConversationSummarizer
    from sagents.v2.context.summary import SummarizationRequest

    active = peak = 0

    class SummaryPlugin(ModelConversationSummarizer):
        async def _summarize(self, request, progress):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            try:
                await asyncio.sleep(0.01)
                return "summary"
            finally:
                active -= 1

    request = SummarizationRequest(scope=scope(), messages=(), target_tokens=512)
    values = await asyncio.gather(
        *(SummaryPlugin(cast(ModelProvider, None)).summarize(request) for _ in range(16))
    )
    assert values == ["summary"] * 16
    assert peak == 4


@pytest.mark.asyncio
async def test_concurrent_extractive_compression_bounds_workers_and_cancellation(monkeypatch):
    import threading

    from sagents.v2.context import (
        InMemoryConversationSummaryStore,
        PersistentSummaryContextReducer,
    )
    from sagents.v2.context.plugins._shared import progress_summary

    loop = asyncio.get_running_loop()
    event_loop_thread = threading.get_ident()
    worker_release = threading.Event()
    two_started = asyncio.Event()
    lock = threading.Lock()
    active_keys = set()
    max_active = 0
    summarize = progress_summary.bounded_snapshot

    def blocked_summary(request):
        nonlocal max_active
        assert threading.get_ident() != event_loop_thread
        key = request.scope.context_key
        with lock:
            active_keys.add(key)
            max_active = max(max_active, len(active_keys))
            if len(active_keys) == 2:
                loop.call_soon_threadsafe(two_started.set)
        try:
            assert worker_release.wait(5)
            return summarize(request)
        finally:
            with lock:
                active_keys.remove(key)

    monkeypatch.setattr(progress_summary, "bounded_snapshot", blocked_summary)
    messages = tuple(
        message(f"{index}: " + "historic decision " * 60,
                "user" if index % 2 == 0 else "assistant")
        for index in range(24)
    )
    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(store)
    requests = [scope(f"session-{index}").model_copy(update={"force": True}) for index in range(16)]
    tasks = [asyncio.create_task(reducer.reduce(messages, scope=request)) for request in requests]
    try:
        await asyncio.wait_for(two_started.wait(), timeout=3)
        with lock:
            cancelled_key = min(active_keys)
        index = next(i for i, request in enumerate(requests) if request.context_key == cancelled_key)
        tasks[index].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[index]
    finally:
        worker_release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)

    assert max_active == 2
    assert sum(isinstance(result, asyncio.CancelledError) for result in results) == 1
    assert await store.get(cancelled_key, session_id=cancelled_key) is None
    for request, result in zip(requests, results, strict=True):
        if isinstance(result, asyncio.CancelledError):
            continue
        assert not isinstance(result, BaseException)
        assert result.strategy == "persistent_summary"
        assert result.messages[-1] == messages[-1]
        assert result.historical_messages == messages[:20]
        assert await store.get(request.context_key, session_id=request.session_id) is not None
