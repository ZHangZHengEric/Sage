---
layout: default
title: Single-host Concurrency
parent: Architecture
nav_order: 9
lang: en
ref: v2-detail-sagents-v2-single-host-concurrency
---

{% include lang_switcher.html %}

# v2 Single-host Concurrency

## Commits and leases

One application process can interleave model calls, tools, and persistence across users and Sessions. The memory and file Schedulers hold their global lock in `execute_fenced` only while checking, registering, and removing lease protection. Storage writes retain a protection marker for the corresponding Run.

- Different Runs may commit concurrently; commits within one Run remain ordered.
- A committing Run cannot be reclaimed, cancelled, or have its lease released; its tenant slot is not freed early.
- Heartbeats may renew during writes; admitted protected writes retain their original lease authority.
- Protection is removed after success, failure, or repeated cancellation. Shutdown waits for protected writes to exit.
- Claim waiters wake at relevant lease expiry without depending on another request to notify them.

File Scheduler state remains atomically and sequentially persisted; SQL SessionStore writers still execute transactions sequentially. Reducing Scheduler-level serialization does not change each store's guarantees.

## Server configuration

Server keeps a long-lived Application. Chat and managed Applications have separate queues and a shared `SchedulerQuotaGroup`, so total quotas do not multiply with package count.

| Environment variable | Default | Purpose |
| --- | ---: | --- |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS` | 8 | Total executing root Runs |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER` | 2 | Atomic per-user execution quota |
| `SAGE_SERVER_MAX_PENDING_RUNS` | 1024 | Shared pending-queue limit |

This is an adjustable single-host acceptance starting point, not a capacity promise:

```dotenv
SAGE_SERVER_MAX_CONCURRENT_RUNS=32
SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER=4
SAGE_SERVER_MAX_PENDING_RUNS=1024
```

Reduce execution concurrency when model rate limits or database capacity become bottlenecks, and observe queueing and P95/P99 latency. A longer queue does not increase throughput. Direct Builder users configure `max_concurrent_runs`, `max_concurrent_runs_per_tenant`, and `max_pending_items` under `execution.scheduler`. See [resource management](SAGENTS_V2_RESOURCE_MANAGEMENT.md) for Job limits.

## Validation and deployment boundary

```bash
python -m pytest tests/sagents/v2/test_single_host_fencing.py
python scripts/benchmark_v2_single_host.py --sessions 64 --writes 8 --io-ms 2
python scripts/benchmark_v2_single_host.py --sessions 128 --writes 8 --io-ms 2
```

Tests cover parallel cross-Run commits, same-Run ordering, renewal, reclamation, quotas, cancellation, shutdown, and the Dispatcher → LeaseFencedSessionStore → SessionStoreCoordinator path. Benchmarks simulate slow asynchronous storage without real models or databases. Historical pass counts and synthetic latency are not production-capacity guarantees.

Server still requires one worker. Persistence, lease fencing, in-process event subscriptions, and JobRuntime are separate guarantees. Using MySQL does not establish multi-process or multi-host execution support.
