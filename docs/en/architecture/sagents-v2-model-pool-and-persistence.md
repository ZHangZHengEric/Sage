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
transaction; every 32 commits also schedules an active Session. The worker appends
contiguous revisions to the existing session_mutations and run_events tables in
transactions of at most 32 deltas and a 256 KiB target. A single indivisible record
above that target is processed alone. Event inserts are limited by both bytes and
128 rows. Each transaction publishes events, mutations, indexes and revision together;
retries resume after the committed SQL revision. No audit tables are added. A newer
Redis revision prevents acknowledgement or expiry of the newer data.

Run commits no longer rewrite a full snapshot every 256 mutations. Background
archival compacts Redis snapshots into chunks of at most 16K characters (64 KiB
in UTF-8), then atomically publishes the base pointer and removes old deltas.
Readers retry a concurrent base switch. Referenced chunks remain persistent while
the Session is active. Legacy inline bases are readable and need a one-time atomic
SQL baseline before incremental archival. All readers must support chunked bases
before deployment. JSON replay and snapshot encoding run off the event loop. Replay
validates changed rows per revision and builds the full state once. Approval expiry
projects current suspended states without loading completed Session histories.

Active and unarchived state has no TTL. Archived, quiescent Session caches expire
after the retention interval and reload from MySQL. Failed archives retain their
data and retry intent in Redis. Cold reads and initial idempotency lookups still
require MySQL availability. On restart, resident Sessions rebuild dispatchable Runs
and pending Sessions are archived. Shutdown waits up to five seconds; unfinished
archival remains recoverable on the next startup. One writer owns each namespace
with a 30-second lease renewed independently every five seconds. Startup retries once
per second for up to 35 seconds while a previous writer's lease expires or is released.
A live writer's lease is never taken over; the new process fails startup on timeout.
Runtime writes still fail immediately after lease loss. Cross-process live subscriptions
and distributed execution are not introduced.

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
the old MySQL writer concurrently against the same tables. Changing the MySQL host
also changes the default Redis namespace: drain the previous namespace first or
explicitly preserve its key_prefix. This change does not
alter deployment configuration or migrate production data.

Lifecycle deltas use `patches.runs` rather than repeatedly serializing unchanged
`start_command` and `request_context`. Initial writes and snapshots retain complete
requests. All readers must support these journal patches before rollout.
For 200 synthetic commits with a fixed 60 KB input, median payload fell from 63650.5
to 2736.5 bytes and median serialization from 0.1984 to 0.0629 ms. These numbers exclude
Redis/MySQL networking, model calls and end-to-end latency.

## Distributed SessionStore and Scheduler plugins

`sage.session.redis-mysql-distributed` and `sage.scheduler.redis-distributed` are
separate plugins from the existing single-process implementations. Server opts in
with `SAGE_SERVER_SESSION_STORE_PLUGIN=sage.session.redis-mysql-distributed`, plus
its MySQL and Redis URLs. It selects the matching scheduler with a 30-second Run
lease, shared global/user quotas, and separate executable queues for managed Apps.
Every node must use identical database, Redis and quota configuration; managed
storage roots must have the same identity on every node. Default selection is unchanged.

The SessionStore has no process-wide owner. Renewable guards serialize individual
Session operations and actor-scoped admission keys. Child admission and tree
deletion additionally coordinate topology changes. Redis transactions check the
operation guard and the worker mutation fence at the actual commit. Cached
aggregates refresh under their local lock; metadata projections read shared state.
Subscriptions poll canonical events every 100 ms by default. Shared preview buffers
retain up to 2048 events for 300 seconds, with explicit epoch/retention gaps.
Archival reuses the existing MySQL tables and revision transactions; it adds no
audit tables. Deleted Session tombstones remain authoritative in Redis.

The Scheduler atomically updates a bounded shared queue snapshot with Redis CAS.
Queues route work to the correct application while sharing quota accounting.
Run mutation guards prevent takeover during a commit; the storage transaction
rejects an expired/replaced guard. Dispatchers reconcile remote completion and
periodically repair accepted Runs missing from the queue. This implementation
prioritizes correctness for bounded queues; a single coordination snapshot is not
a claim of unlimited scheduling throughput. Distributed storage and scheduling
must be selected together, against the same Redis URL; incompatible pairs fail startup.

Drain the old writer and pending archives before switching plugins. The distributed
plugin has a separate default Redis prefix and reuses the existing MySQL tables.
Never run the old writer concurrently against those tables. These plugins coordinate
Run/session state; the existing process-local JobRuntime, local memory databases,
workspace files and sandbox processes still need an appropriate shared-resource or
owner-routing deployment strategy. A failed process does not migrate its live OS
processes, and lease recovery does not make external tool side effects exactly-once.

## Validation

The project requires Python 3.12+. Use current tests and benchmarks rather than treating historical pass counts as current acceptance results:

```bash
python -m pytest tests/app/v2/server/test_model_pool.py
python scripts/v2/benchmark_session_projection.py --events 10000 --repeats 10
python scripts/v2/benchmark_session_commit.py --commits 200 --input-bytes 60000
python -m pytest tests/sagents/v2/test_redis_mysql_session_store.py tests/sagents/v2/test_mysql_session_archive.py
```

Pool tests cover concurrent initialization, user and credential isolation, capacity, failure, cancellation, slow eviction, and shutdown failures. SQL projection tests cover incremental append, no new events, history truncation, Run deletion, and full export. Mock database connections do not constitute real MySQL / PostgreSQL acceptance.

The benchmark measures coordinator serialization of synthetic long event lists, excluding SQL, network, model calls, and task completion rates. It cannot be converted into production QPS. Long-running load against real endpoints requires separate validation.

Implementation: [model_pool.py](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/server/runtime/model_pool.py).
