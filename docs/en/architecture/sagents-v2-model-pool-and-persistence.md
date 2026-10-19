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

This page covers two independent optimizations: reusing model clients instead of repeatedly creating connection objects, and serializing only new events when saving long Sessions. Neither changes conversation content or determines how many tasks may run at once.

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

## Redis execution state and MySQL archival

Set `SAGE_SERVER_REDIS_URL=redis://localhost:6379/1` alongside the existing
`SAGE_SERVER_MYSQL_URL` to select `sage.session.redis-mysql`. Without Redis configured,
the Server keeps the existing MySQL backend. SDK Packages can select the same plugin
with required `dsn` and `redis_url`, optional `table_prefix`, `key_prefix`,
`archive_interval_seconds` (default 1) and `retention_seconds` (default 3600).
The default Redis namespace is derived from the database address, database name and
table prefix, excluding credentials. Managed Packages retain isolated namespaces.

Each existing SessionStore commit atomically writes execution state, canonical events,
checkpoints, idempotency results and lookup indexes into Redis. Completion, failure,
cancellation and suspension enqueue the Session for background archival in the same
transaction. The worker writes a complete aggregate and newly appended events into
the existing MySQL tables. It creates no audit business tables. A locked SQL revision
comparison rejects stale snapshots and makes retries idempotent. A newer Redis
revision prevents acknowledgement or expiry of the newer data.

Active and unarchived state has no TTL. Archived, quiescent Session caches expire
after the retention interval and reload from MySQL. Failed archives retain their
data and retry intent in Redis. Cold reads and initial idempotency lookups still
require MySQL availability. On restart, resident Sessions rebuild dispatchable Runs
and pending Sessions are archived. Shutdown waits up to five seconds; unfinished
archival remains recoverable on the next startup. One writer owns each namespace
with a 30-second lease renewed independently every five seconds. Cross-process live
subscriptions and distributed execution are not introduced.

Deletion atomically writes Redis tombstones and removes lookup indexes before
background SQL deletion. Unique commit tokens resolve ambiguous transaction responses;
unresolved writes force authoritative reload before further operations. Derived caches
live only in Redis and may be rebuilt. Attachment bytes are committed with their
references and subsequently archived to MySQL.

Startup requires `INFO memory` to report `maxmemory_policy=noeviction` and
`INFO persistence` to report `aof_enabled=1`. The Redis account must be able to read
these values. Deployment owns AOF fsync policy: `everysec` can lose about one second
on Redis host failure; `always` provides stricter persistence with a latency cost.
See [Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
and [redis-py transactions](https://redis.io/docs/latest/develop/clients/redis-py/transpipe/).
Drain in-flight Runs and pending archives before changing storage modes; never run
the old MySQL writer concurrently against the same tables. This change does not
alter deployment configuration or migrate production data.

Lifecycle deltas use `patches.runs` rather than repeatedly serializing unchanged
`start_command` and `request_context`. Initial writes and snapshots retain complete
requests. All readers must support these journal patches before rollout.
For 200 synthetic commits with a fixed 60 KB input, median payload fell from 63650.5
to 2736.5 bytes and median serialization from 0.1984 to 0.0629 ms. These numbers exclude
Redis/MySQL networking, model calls and end-to-end latency.

## Validation

The project requires Python 3.12+. Use current tests and benchmarks rather than treating historical pass counts as current acceptance results:

```bash
python -m pytest tests/app/v2/server/test_model_pool.py
python scripts/v2/benchmark_v2_session_projection.py --events 10000 --repeats 10
python scripts/v2/benchmark_v2_session_commit.py --commits 200 --input-bytes 60000
python -m pytest tests/sagents/v2/test_redis_mysql_session_store.py tests/sagents/v2/test_mysql_session_archive.py
```

Pool tests cover concurrent initialization, user and credential isolation, capacity, failure, cancellation, slow eviction, and shutdown failures. SQL projection tests cover incremental append, no new events, history truncation, Run deletion, and full export. Mock database connections do not constitute real MySQL / PostgreSQL acceptance.

The benchmark measures coordinator serialization of synthetic long event lists, excluding SQL, network, model calls, and task completion rates. It cannot be converted into production QPS. Long-running load against real endpoints requires separate validation.

Implementation: [model_pool.py](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/server/runtime/model_pool.py).
