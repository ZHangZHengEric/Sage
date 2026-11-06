"""Summary-only selection, checkpoint reuse and immutable tool results."""

import pytest

from sagents.v2.composition.defaults import DEFAULT_COMPONENTS, default_runtime, effective_runtime
from sagents.v2.context import (
    ContextBudget,
    DefaultContextAssembler,
    InMemoryConversationSummaryStore,
    SummaryOnlyContextReducer,
)
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage, ModelToolCall
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig
from sagents.v2.runtime.extensions import (
    CapabilityKey,
    ExtensionScope,
    ExtensionScopeContext,
    ProviderSet,
)
from sagents.v2.runtime.extensions.official import builtin_extension_registry


class RecordingSummary:
    def __init__(self):
        self.requests = []

    async def summarize(self, request):
        self.requests.append(request)
        return "Completed file inspections; continue comparing the latest files."


def batch(index, results):
    calls = tuple(
        ModelToolCall(
            tool_call_id=f"read_{index}_{n}", name="read_file",
            arguments={"path": f"file_{index}_{n}.py"},
        )
        for n in range(results)
    )
    return (
        ModelMessage(role="assistant", tool_calls=calls),
        *(ModelMessage(
            role="tool", tool_call_id=call.tool_call_id,
            content=(TextBlock(text=f"file body {call.tool_call_id} " * 300),),
            metadata={"context_reference": {"uri": f"artifact://{call.tool_call_id}"}},
        ) for call in calls),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ["registry", "bundle"])
@pytest.mark.parametrize("pressure", ["usage", "rejection"])
@pytest.mark.parametrize("results", [1, 3])
async def test_summary_only_persists_coverage_without_references(
    selection, pressure, results, monkeypatch,
):
    async def unexpected_reference_compaction(unit):
        pytest.fail("summary-only must never invoke tool reference compaction")

    monkeypatch.setattr(
        "sagents.v2.context.plugins._shared.persistent_summary.compact_unit_to_references",
        unexpected_reference_compaction,
    )
    store, summary = InMemoryConversationSummaryStore(), RecordingSummary()
    if selection == "registry":
        registration = builtin_extension_registry().get(SummaryOnlyContextReducer.plugin_id)
        reducer = registration.factory(
            ExtensionScopeContext(
                scope=ExtensionScope.RUN, scope_id="run",
                config={"protected_recent_units": 2, "summary_target_tokens": 256},
            ),
            ProviderSet({
                CapabilityKey(capability="context.summary-store"): store,
                CapabilityKey(capability="context.summarizer"): summary,
            }),
        )
    else:
        reducer = ContextComponentBundle(
            reducer_id="summary-only", summary_store=store, summarizer=summary,
            protected_recent_units=2, summary_target_tokens=256,
        ).create_reducer()
    assert type(reducer) is SummaryOnlyContextReducer
    assert reducer.protected_recent_units == 2
    assert reducer.summary_target_tokens == 256
    command = StartRun(
        agent_id="agent", input=(), resolved_spec_hash="sha256:test",
        idempotency_key="start",
    )
    user = ModelMessage(role="user", content=(TextBlock(text="Compare the files"),))
    batches = [batch(i, results) for i in range(6)]
    source = (user, *(message for unit in batches for message in unit))
    original = tuple(message.model_dump_json() for message in source)
    assembler = DefaultContextAssembler(budget=ContextBudget(max_input_tokens=1000), reducer=reducer)
    initial = await assembler.prepare_projection(command, source, run_id="run")
    assert initial.messages == source
    assert not summary.requests
    if pressure == "usage":
        assembler.observe_usage("run", 1200)
    else:
        assembler.request_compression("run")
    projection = await assembler.prepare_projection(command, source, run_id="run")
    assert projection.strategy == "persistent_summary"
    recent = (*batches[-2], *batches[-1])
    assert projection.messages[-len(recent):] == recent
    assert len(summary.requests) == 1
    assert summary.requests[0].messages == source[:-len(recent)]
    assert "<tool_result_reference>" not in "".join(
        block.text for message in projection.messages for block in message.content
        if isinstance(block, TextBlock)
    )

    # A new reducer/assembler must reuse the stored coverage even without pressure.
    restored = DefaultContextAssembler(reducer=SummaryOnlyContextReducer(store, summarizer=summary))
    next_batch = batch(6, results)
    reused = await restored.prepare_projection(command, (*source, *next_batch), run_id="run")
    assert reused.messages == (*projection.messages, *next_batch)
    assert len(summary.requests) == 1
    assert tuple(message.model_dump_json() for message in source) == original


def test_summary_only_is_default_and_explicit_legacy_selection_is_preserved(tmp_path):
    runtime = effective_runtime(RuntimeConfig(capabilities={
        "context.reducer": CapabilitySelection(plugin=SummaryOnlyContextReducer.plugin_id),
    }))
    selection = runtime.capabilities["context.reducer"]
    assert selection.plugin == SummaryOnlyContextReducer.plugin_id
    assert selection.scope == ExtensionScope.RUN
    assert type(ContextComponentBundle().create_reducer()) is SummaryOnlyContextReducer
    assert type(DefaultContextAssembler().reducer) is SummaryOnlyContextReducer
    assert effective_runtime(RuntimeConfig()).capabilities["context.reducer"].plugin == SummaryOnlyContextReducer.plugin_id
    assert DEFAULT_COMPONENTS["context.reducer"] == SummaryOnlyContextReducer.plugin_id
    assert default_runtime(tmp_path).capabilities["context.reducer"].plugin == SummaryOnlyContextReducer.plugin_id
    explicit = effective_runtime(RuntimeConfig(capabilities={
        "context.reducer": CapabilitySelection(plugin="sage.context.reducer.persistent-summary"),
    }))
    assert explicit.capabilities["context.reducer"].plugin == "sage.context.reducer.persistent-summary"
