---
layout: default
title: Model Pool and Persistence
parent: Architecture
nav_order: 8
lang: en
ref: v2-detail-sagents-v2-model-pool-and-persistence
---

{% include lang_switcher.html %}

# v2 Model Pool and Incremental Persistence

## Bounded model-client pool

The Server host owns clients; Runs borrow leases. The same user, model record, protocol, address, model name, and credentials reuse a client. Different users or changed credentials use separate entries. Pool keys are SHA-256 digests of those fields; raw credentials are not exposed.

- `SAGE_SERVER_MAX_MODEL_CLIENTS` defaults to 64 and must be positive. It limits client instances, not HTTP connections. The Scheduler separately limits execution concurrency.
- Concurrent initialization for the same configuration is coalesced. Cancelling one waiter does not cancel initialization shared by other Runs.
- Completion, failure, and cancellation release leases. Only unleased entries can be evicted, in least-recently-borrowed order. Closing entries still count toward capacity.
- A full pool with no evictable entry returns retryable rate-limit error `server.model_pool_full`, rather than accumulating unlimited waiters.
- There is no timed TTL. Idle clients remain until eviction or host shutdown. New Runs after a credential change use new clients; older Runs may finish.
- Shutdown waits for leases before closing clients. Caller cancellation does not interrupt background cleanup; later close calls may wait again. Cleanup failures are reported and stop admission of new clients.
- Externally injected fallback providers remain owned by their original owner.

Size capacity for active users and model configurations. More execution slots with a small client pool may simply cause more rate limiting.

## Incremental SQL event serialization

For MySQL / PostgreSQL commits, the coordinator serializes only events after the persisted prefix before passing them to the existing transaction. Full snapshot exports still include complete history by default.

If in-memory history is shorter than the persisted prefix, the coordinator exports the complete current history and the SQL transaction replaces old records. Run deletion cleanup and post-commit count updates keep their ordering. The serial writer connection still executes SQL transactions sequentially to preserve locking and commit consistency.

This reduces repeated event serialization, not the cost of Session metadata, command results, or fork-base events. It does not introduce distributed writers.

## Validation

The project requires Python 3.12+. Use current tests and benchmarks rather than treating historical pass counts as current acceptance results:

```bash
python -m pytest tests/app/server_v2/test_model_pool.py
python scripts/benchmark_v2_session_projection.py --events 10000 --repeats 10
```

Pool tests cover concurrent initialization, user and credential isolation, capacity, failure, cancellation, slow eviction, and shutdown failures. SQL projection tests cover incremental append, no new events, history truncation, Run deletion, and full export. Mock database connections do not constitute real MySQL / PostgreSQL acceptance.

The benchmark measures coordinator serialization of synthetic long event lists, excluding SQL, network, model calls, and task completion rates. It cannot be converted into production QPS. Long-running load against real endpoints requires separate validation.
