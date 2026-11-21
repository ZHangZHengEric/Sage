"""Replay a deterministic long Agent run locally with no model or tool network I/O.

By default, the session coordinator serializes durable deltas to a counting
sink. Use --filesystem for a real temporary filesystem-backed SessionStore.
The projected share uses the observed external time from the reference run.
Run each comparison in a fresh Python process.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
import json
import os
from pathlib import Path
import resource
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sagents.v2.agent.observed import ObservedRunDriver
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.items import TextBlock, UsageSummary
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.model.contracts import ModelCapabilities, ModelEventKind, ModelResponse, ModelStreamEvent, ModelToolCall
from sagents.v2.runtime.kernel import HarnessRuntime
from sagents.v2.runtime.session.plugins.filesystem import _FilesystemSessionState
from sagents.v2.runtime.session.state import SessionStoreCoordinator
from sagents.v2.tool.contracts import SideEffectLevel, ToolDefinition, ToolExecutionResult
from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog, InMemoryToolExecutor

TOOL = ToolDefinition(
    name="inspect_record",
    description="Read one record",
    input_schema={"type": "object", "properties": {}},
    side_effect_level=SideEffectLevel.READ,
)
FIXED_EXTERNAL_SECONDS = 664.069


class MeasuredStore(SessionStoreCoordinator):
    def __init__(self, io_ms, read_ms):
        super().__init__()
        self.io_seconds = io_ms / 1000
        self.read_seconds = read_ms / 1000
        self.run_reads = 0
        self.transactions = 0
        self.payload_bytes = 0
        self.storage_seconds = 0.0
        self.serialization_seconds = 0.0

    async def get_run(self, run_id):
        self.run_reads += 1
        if self.read_seconds:
            await asyncio.sleep(self.read_seconds)
        return await super().get_run(run_id)

    async def _commit_storage_locked(self, sid):
        started = perf_counter()
        mutation = self._session_mutation_locked(sid)
        self.payload_bytes += len(mutation.model_dump_json().encode())
        self.serialization_seconds += perf_counter() - started
        self.transactions += 1
        if self.io_seconds:
            await asyncio.sleep(self.io_seconds)
        self.storage_seconds += perf_counter() - started


class MeasuredFilesystemStore(_FilesystemSessionState):
    def __init__(self, root):
        super().__init__(root)
        self.run_reads = 0
        self.transactions = 0
        self.storage_seconds = 0.0
        self.aggregate_seconds = 0.0
        self.snapshot_seconds = 0.0

    async def get_run(self, run_id):
        self.run_reads += 1
        return await super().get_run(run_id)

    async def _commit_storage_locked(self, session_id):
        started = perf_counter()
        await super()._commit_storage_locked(session_id)
        self.transactions += 1
        self.storage_seconds += perf_counter() - started

    def _state_from_mutation(self, previous, mutation):
        started = perf_counter()
        state = super()._state_from_mutation(previous, mutation)
        self.aggregate_seconds += perf_counter() - started
        return state

    def _write_snapshot(self, path, state):
        started = perf_counter()
        super()._write_snapshot(path, state)
        self.snapshot_seconds += perf_counter() - started


class MeasuredDriver(ObservedRunDriver):
    def __init__(self, *, log_sink, **kwargs):
        super().__init__(log_sink=log_sink, **kwargs)
        self.totals = log_sink
        self.detail_seconds = Counter()
        self.digest_seconds = 0.0
        self.digest_count = 0

    @contextmanager
    def _outside_commit(self, phase):
        started = perf_counter()
        commit_ms = self.totals.ms["agent.state.commit"]
        try:
            yield
        finally:
            committed = (self.totals.ms["agent.state.commit"] - commit_ms) / 1000
            self.detail_seconds[phase] += perf_counter() - started - committed

    async def _stream_model(self, *args, **kwargs):
        with self._outside_commit("model_stream"):
            return await super()._stream_model(*args, **kwargs)

    async def _dispatch_tool(self, *args, **kwargs):
        with self._outside_commit("tool_dispatch"):
            return await super()._dispatch_tool(*args, **kwargs)

    def _ledger_digest(self, messages):
        started = perf_counter()
        digest = super()._ledger_digest(messages)
        self.digest_seconds += perf_counter() - started
        self.digest_count += 1
        return digest


class ReplayModel:
    plugin_id = "benchmark.replay"

    def __init__(self, model_calls, tool_calls, stream_chunks):
        self.calls = 0
        self.model_calls = model_calls
        self.tool_calls = tool_calls
        self.stream_chunks = stream_chunks
        self.non_tool_steps = set(
            range(7, model_calls, 7)
            if (model_calls, tool_calls) == (64, 55)
            else range(tool_calls + 1, model_calls)
        )
        if (model_calls, tool_calls) == (64, 55):
            self.non_tool_steps.discard(63)

    async def capabilities(self, model_binding):
        return ModelCapabilities(supports_streaming=True, supports_tools=True)

    async def stream(self, request):
        self.calls += 1
        index = self.calls
        final = index == self.model_calls
        partial = index in self.non_tool_steps
        calls = () if final or partial else (
            ModelToolCall(tool_call_id=f"call_{index}", name=TOOL.name, arguments={}),
        )
        for _ in range(self.stream_chunks):
            yield ModelStreamEvent(kind=ModelEventKind.REASONING_DELTA, delta="Reasoning fragment. ")
        yield ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(
                response_id=f"response_{index}",
                text="Inspection complete." if final else f"Inspection step {index}.",
                tool_calls=calls,
                finish_reason="stop" if final else "length" if partial else "tool_calls",
                usage=UsageSummary(input_tokens=2000, output_tokens=100, reported=True),
            ),
        )


class StageTotals:
    def __init__(self):
        self.ms = Counter()
        self.counts = Counter()

    def write(self, record):
        duration = record.attributes.get("duration_ms")
        if duration is not None and record.event in {"agent.preparation.completed", "agent.state.commit"}:
            name = record.attributes.get("phase", record.event)
            self.ms[name] += duration
            self.counts[name] += 1


async def benchmark(store, args):
    runtime = HarnessRuntime(store)
    model = ReplayModel(args.model_calls, args.tool_calls, args.stream_chunks)
    totals = StageTotals()
    tool_calls = 0

    async def read_record(call, context):
        nonlocal tool_calls
        tool_calls += 1
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text=str(tool_calls) + "x" * args.tool_payload_bytes),),
        )

    loop = MeasuredDriver(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog((TOOL,)),
        tool_executor=InMemoryToolExecutor({TOOL.name: TOOL}, {TOOL.name: read_record}),
        log_sink=totals,
    )
    context = RequestContext(actor=ActorRef(principal_id="benchmark", principal_type=PrincipalType.USER))
    started = perf_counter()
    handle = await runtime.start_run(StartRun(
        agent_id="benchmark",
        input=(InputItem(role="user", content=(TextBlock(text="Inspect the records and report."),)),),
        config=RunConfig(max_steps=args.model_calls + 6, model_bindings={"primary": "replay"}),
        idempotency_key="benchmark",
        resolved_spec_hash="benchmark",
    ), context)
    result = await loop.execute(handle.run_id, context)
    elapsed = perf_counter() - started
    assert (result.state, model.calls, tool_calls) == (RunState.COMPLETED, args.model_calls, args.tool_calls), (
        result.state, model.calls, tool_calls,
    )
    state_commit = totals.ms["agent.state.commit"] / 1000
    model_request = totals.ms["model_request"] / 1000
    remainder = elapsed - state_commit - model_request
    return {
        "model_calls": model.calls, "tool_calls": tool_calls,
        "tool_payload_bytes": args.tool_payload_bytes,
        "stream_chunks_per_model": args.stream_chunks,
        "simulated_storage_io_ms": 0 if args.filesystem else args.storage_io_ms,
        "simulated_run_read_ms": args.run_read_ms,
        "local_framework_seconds": round(elapsed, 4),
        "projected_framework_share_percent": round(100 * elapsed / (args.external_seconds + elapsed), 4),
        "run_reads": store.run_reads,
        "storage_transactions": store.transactions,
        "checkpoint_digest_count": loop.digest_count,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "stage_seconds": {
            "agent_state_commit": round(state_commit, 4),
            "session_storage_including_other_writes": round(store.storage_seconds, 4),
            "checkpoint_digest_including_time_outside_commit": round(loop.digest_seconds, 4),
            "model_request_preparation": round(model_request, 4),
            "context_projection_inside_model_preparation": round(totals.ms["context_projection"] / 1000, 4),
            "model_stream_outside_agent_commit": round(loop.detail_seconds["model_stream"], 4),
            "tool_dispatch_outside_agent_commit": round(loop.detail_seconds["tool_dispatch"], 4),
            "other_loop_admission_and_cleanup": round(remainder - loop.detail_seconds.total(), 4),
        },
        "agent_state_commits": totals.counts["agent.state.commit"],
    }


async def main(args):
    if not args.filesystem:
        store = MeasuredStore(args.storage_io_ms, args.run_read_ms)
        metrics = await benchmark(store, args)
        metrics["serialized_delta_bytes"] = store.payload_bytes
        metrics["stage_seconds"]["delta_serialization_inside_storage"] = round(store.serialization_seconds, 4)
        return metrics

    with TemporaryDirectory(prefix="sage-agent-benchmark-") as directory:
        store = MeasuredFilesystemStore(directory)
        fsync = os.fsync
        fsync_seconds = 0.0

        def measured_fsync(fd):
            nonlocal fsync_seconds
            started = perf_counter()
            try:
                fsync(fd)
            finally:
                fsync_seconds += perf_counter() - started

        try:
            os.fsync = measured_fsync
            metrics = await benchmark(store, args)
        finally:
            os.fsync = fsync
            await store.close()
        metrics["stage_seconds"]["filesystem_fsync_inside_storage"] = round(fsync_seconds, 4)
        metrics["stage_seconds"]["filesystem_aggregate_inside_storage"] = round(store.aggregate_seconds, 4)
        metrics["stage_seconds"]["filesystem_snapshot_inside_storage"] = round(store.snapshot_seconds, 4)
        metrics["filesystem_bytes"] = sum(
            path.stat().st_size for path in Path(directory).rglob("*") if path.is_file()
        )
        return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool-payload-bytes", type=int, default=8192)
    parser.add_argument("--model-calls", type=int, default=64)
    parser.add_argument("--tool-calls", type=int, default=55)
    parser.add_argument("--stream-chunks", type=int, default=0)
    parser.add_argument("--run-read-ms", type=float, default=0)
    parser.add_argument("--external-seconds", type=float, default=FIXED_EXTERNAL_SECONDS)
    parser.add_argument("--trace-allocations", action="store_true", help="Measure Python heap separately from RSS")
    storage = parser.add_mutually_exclusive_group()
    storage.add_argument("--storage-io-ms", type=float, default=2)
    storage.add_argument("--filesystem", action="store_true")
    args = parser.parse_args()
    if min(args.tool_payload_bytes, args.storage_io_ms, args.run_read_ms, args.stream_chunks) < 0:
        parser.error("payload size, chunk count and I/O delays must be non-negative")
    if not 0 <= args.tool_calls < args.model_calls or args.external_seconds <= 0:
        parser.error("model calls must exceed tool calls and external time must be positive")
    if args.filesystem and args.run_read_ms:
        parser.error("run-read-ms is available only for simulated storage")
    if args.trace_allocations:
        import tracemalloc

        tracemalloc.start()
    result = asyncio.run(main(args))
    if args.trace_allocations:
        result["python_peak_allocated_bytes"] = tracemalloc.get_traced_memory()[1]
    print(json.dumps(result, indent=2))
