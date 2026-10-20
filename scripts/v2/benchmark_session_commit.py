"""Compare lifecycle delta serialization with/without repeated accepted requests.

No Redis, MySQL or model I/O. Both modes use the same synthetic input, number
of commits and coordinator; the baseline repeats request fields in Run deltas.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.session.state import SessionStoreCoordinator


class MeasuredStore(SessionStoreCoordinator):
    def __init__(self, repeat_request):
        super().__init__()
        self.repeat_request = repeat_request
        self.samples = []

    def _run_row_payload(self, row, *, include_request=True):
        return super()._run_row_payload(row, include_request=include_request or self.repeat_request)

    async def _commit_storage_locked(self, sid):
        started = time.perf_counter()
        mutation = self._session_mutation_locked(sid)
        encoded = json.dumps(mutation.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        self.samples.append(((time.perf_counter() - started) * 1000, len(encoded.encode())))


async def main(commits, input_bytes):
    context = RequestContext(actor=ActorRef(principal_id="benchmark", principal_type=PrincipalType.USER))
    result = {"scope": "synthetic coordinator delta serialization only; no database or model I/O",
              "commits": commits, "input_bytes": input_bytes}
    for mode in ("baseline", "optimized"):
        store = MeasuredStore(mode == "baseline")
        created = await store.create_run(StartRun(agent_id="agent", resolved_spec_hash="spec", idempotency_key="start",
            input=(InputItem(role="user", content=(TextBlock(text="x" * input_bytes),)),)), context)
        store.samples.clear()
        for i in range(commits):
            await store.commit_run(run_id=created.handle.run_id, expected_revision=i,
                expected_states={RunState.QUEUED, RunState.RUNNING}, new_state=RunState.RUNNING,
                drafts=(), context=context, idempotency_key=f"commit-{i}")
        samples = sorted(elapsed for elapsed, _ in store.samples)
        result[mode] = {"median_ms": round(statistics.median(samples), 4),
                        "p95_ms": round(samples[int((len(samples) - 1) * .95)], 4),
                        "median_payload_bytes": statistics.median(size for _, size in store.samples)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commits", type=int, default=200)
    parser.add_argument("--input-bytes", type=int, default=60000)
    args = parser.parse_args()
    if args.commits < 1 or args.input_bytes < 1:
        parser.error("commits and input bytes must be positive")
    asyncio.run(main(args.commits, args.input_bytes))
