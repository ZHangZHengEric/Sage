"""Compare full and append-only event serialization; no database/model I/O."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.session.plugins.ephemeral import EphemeralSessionStore


async def main(events: int, repeats: int):
    store = EphemeralSessionStore()
    created = await store.create_run(
        StartRun(
            agent_id="benchmark",
            input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
            resolved_spec_hash="sha256:benchmark",
            idempotency_key="start",
        ),
        RequestContext(
            actor=ActorRef(principal_id="benchmark", principal_type=PrincipalType.USER)
        ),
    )
    sid, rid = created.handle.session_id, created.handle.run_id
    sample = store._run_events[rid][-1]
    # Synthetic long ledger; event construction is outside the timed section.
    store._run_events[rid] = [
        sample.model_copy(update={"run_sequence": i + 1}) for i in range(events)
    ]
    result = {
        "events": events,
        "repeats": repeats,
        "scope": "coordinator serialization only; synthetic ledger; no SQL/model I/O",
    }
    for mode, offsets in [("full", None), ("append", {rid: events - 1})]:
        elapsed = []
        for _ in range(repeats):
            start = time.perf_counter()
            state = store._dump_session_state_locked(sid, event_offsets=offsets)
            elapsed.append((time.perf_counter() - start) * 1000)
        result[mode] = {
            "median_ms": round(statistics.median(elapsed), 4),
            "serialized_events": len(state["run_events"][rid]),
        }
    print(json.dumps(result, ensure_ascii=False))
    await store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=10000)
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()
    if args.events < 1 or args.repeats < 1:
        parser.error("events and repeats must be positive")
    asyncio.run(main(args.events, args.repeats))
