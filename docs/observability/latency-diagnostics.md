# V1 preparation and memory latency diagnostics

V1 emits one bounded JSON summary when session preparation takes at least 500 ms,
or `search_memory` takes at least 1,000 ms. Exceptions/cancellations also emit a
summary. `SAGE_LATENCY_DIAGNOSTICS=0` disables collection. Timings use a monotonic
clock. There are no polling tasks, stack profilers, additional index scans, or
new database writes. This instrumentation does not change indexing, lock scope,
thread pool size, or cancellation/shield semantics.

## Location and retention

`$SAGE_LOGS_DIR_PATH/latency-diagnostics.jsonl` (default `logs/`). Production:
`/data/sage/sage-server/logs/latency-diagnostics.jsonl` on the host.

The log is separate from the existing application log and does not propagate to
it. UTC daily rotation keeps the current day and at most two previous daily
files (three calendar days, not a guaranteed full 72-hour history). Each day's
file is capped at 10 MiB; additional summaries are dropped after saturation.
Rotation/expiry runs on the next diagnostic write, including after restart;
there is no background cleanup worker. Thus idle files can remain until that
next write. The cap applies to this process's single writer; multi-process
server deployments should use a distinct log directory per process.

Each record contains a session ID, unique operation ID, operation name, status,
timestamp, wall duration, at most 96 stage names, 64 counters and the five slowest
file operations taking at least 50 ms. File identifiers are truncated SHA-256
hashes; paths, queries, model messages and file contents are not logged.

## Reading a slow request

Match `session_id` with the existing first-output log and Jaeger trace. The two
operations are `session.prepare` and `memory.search`. Repeated calls in one
session have distinct `operation_id` and timestamps. These operation durations
are **not** model TTFT or complete Ling-to-Sage latency. Model query generation
and the boundary before/after Sage still use their existing traces. A first
response over four seconds does not imply that either operation alone exceeded
its logging threshold.

For example, read only the tail, then filter locally:

```sh
tail -n 100 /data/sage/sage-server/logs/latency-diagnostics.jsonl
```

Each stage has `count`, `total_ms`, and `max_ms`. Stages nest and parallel file
operations overlap: **do not sum all stage totals to derive request duration**.

| Field | Interpretation |
| --- | --- |
| `prepare.*` | Workspace paths/registry, external context, sandbox creation, bootstrap files, skill preparation, finalization, persisted messages, todo cleanup |
| `sandbox.factory_create`, `sandbox.filesystem_construct`, `sandbox.init_isolation` | Factory, filesystem setup, and isolation initialization |
| `skills.*` | Skill metadata loading and recursive file-list generation |
| `*.queue` | Submission until worker thread starts: executor backlog plus scheduling delay |
| `*.run` | Worker wall duration, including its CPU, I/O, locks and OS scheduling |
| `*.cpu` | CPU time on the executing thread; low CPU with high wall duration indicates waiting, not proof of a particular device or lock |
| `*.resume` | Worker completion until the coroutine resumes: event-loop dispatch/wakeup delay |
| `index.scope_lock.wait` | Waiting behind another search for the same user/agent/workspace |
| `index.file_semaphore.wait` | Waiting for one of the existing eight file-processing slots |
| `index.fts_write_lock.wait` | Waiting for the current index writer |
| `index.initialize.*` | Index constructor queue/run/resume, with metadata/schema stages underneath |
| `index.get_dir_mtime`, `index.list_directory`, `local.*` | Directory scan and sandbox filesystem operations |
| `index.read_file_content`, `index.replace_file_documents` | Reading and chunk creation |
| `index.build_*_search_text` | Tokenizing chunk/full-file text |
| `fts.delete`, `fts.insert`, `fts.commit` | SQLite statements and commit; statements may include SQLite lock waits |
| `index.save_metadata.*`, `index.query.*` | Metadata persistence and actual retrieval |
| `memory.history_search` | Session-history retrieval, separately from file search |

Async stage wall time includes suspension; it is not CPU time. A large
`queue` cannot by itself distinguish a saturated pool from CPU scheduling.
A large `resume` is evidence of delayed event-loop delivery, not identification
of the blocking callback. Use contemporaneous CPU/trace information to narrow
those cases. Cancelled shielded file operations can continue safely; the
cancellation summary is a snapshot and may not contain their final timings.

## Why net five files is not five units of work

`index.files_before` and `index.files_after` are metadata file counts. The
operation records `index.added`, `updated`, `removed`, `unchanged`, `errors`,
`scan_errors`, and `delete_errors` separately. For a successful non-forced
update, `after - before = added - removed`; updates do not change the net count.

`index.directories_visited`, `directories_unchanged`, `directories_blacklisted`,
`entries_listed`, and `files_checked` describe scan work. `unchanged` counts
individually checked files, not files in skipped directories. `source_bytes`
is the sum of source sizes of processed files, while `content_characters` is
the content actually supplied to chunking (large files can be truncated).
`chunks_built` can greatly exceed file count. `fts_commits` counts replacement
commit attempts, excluding schema and removal commits. `force` flags rebuilds.

Existing behavior processes changed file content, replaces all of that file's
chunks and full-file FTS text, and commits per file. Small net growth can coexist
with many rewritten files, many chunks, or mostly waiting. The previous
864-to-869 observation alone cannot establish which of these occurred.

## Validation

Tests cover queue/run/resume separation, cancellation without releasing another
caller's lock, independent concurrent collectors, fast-call silence, bounded
payloads, private file identifiers, log capacity/retention, and an actual SQLite
update with net +5 but added 6 / updated 1 / removed 1. Existing scoped-cache,
shielded cancellation, FTS retrieval, and sandbox lifecycle/permissions tests
remain part of the targeted regression run.

## Event-loop stall attribution and efficiency fixes

Server lifespan now starts one daemon watchdog. It sleeps indefinitely when
there are no observed preparation/memory operations or their instrumented
thread jobs. During those operations it checks every 50 ms, with at most one
outstanding `call_soon_threadsafe` heartbeat. A heartbeat delayed at least
100 ms produces at most one `event_loop.stall` record per second in the same
size-capped, three-calendar-day diagnostic file. No asyncio debug mode or
callback monkey-patching is enabled.

A stall record contains:

- up to twelve event-loop stack frames (code filename, function, line only);
- up to four worker stacks, eight frames each; tracked workers take priority;
- up to eight active operation/session identifiers for correlation;
- current tracked thread jobs pending/running, oldest pending age, lifetime
  high-water marks, and the five most frequent queued operation names;
- process CPU time and available Linux cgroup CPU throttling/pressure,
  I/O pressure, memory usage/limits/events and PID usage/limits.

Job counters cover **instrumented** `to_thread` work, not every job submitted
by third-party libraries. Zero tracked workers does not prove the executor is
idle. Worker samples marked `untracked_executor_worker` may expose such work.
Maps are capped at 256 observed operations and 1,024 tracked thread jobs;
overflow is recorded for jobs. No frame locals, arguments, source lines,
queries, file bodies or full code paths are collected. Frames are released
immediately after extracting bounded location metadata.

The stack is a sample taken while a heartbeat is delayed, not proof that its
leaf frame consumed the entire delay. `sampler_gap_ms` reveals when the sampler
itself ran late: native code holding the GIL or OS starvation can prevent a
Python watchdog from observing the original blocker. A Python stack may also
stop at a native event-loop boundary. Compare repeated samples and resource
counter deltas before attributing such cases.

The same change removes independently confirmed repeated work:

- FTS existence checks use `LIMIT 1`, not complete row counts. Schema setup is
  performed once per index object and reset on `clear_index`.
- Newly scanned file size is reused when reading content; the parent directory
  is no longer enumerated again for each file. The existing large-file limit
  remains in place.
- Local directory mtime uses one worker call instead of an exists call followed
  by a second stat call; missing paths still return zero and path permissions
  are checked first.
- Session initialization reads current sandbox SKILL.md metadata, retaining
  user overrides. Recursive skill file trees and redundant existence checks
  are removed from initialization; trees are built on actual `load_skill`,
  with serialized completion for concurrent loads. No cross-session stale
  metadata cache is introduced.

## Prompt budget efficiency and three-second target

Prompt components reuse their canonical JSON for hashing and estimation. A
process-local LRU retains at most 2,048 SHA-256 keys and pairs of numeric text
estimates; it never retains message bodies. Image cost and message identity
are applied per call. Both original estimation formulas and fingerprints are
unchanged, and mutable inputs are hashed again on every call.

The four asynchronous AgentBase accounting paths snapshot input containers
before yielding and run manifests in the existing instrumented thread executor.
Provider request observers support both synchronous and awaited asynchronous
callbacks, so accounting still finishes before the actual provider call.
`prompt_budget.manifest` records operations taking at least 100 ms, including
component count, serialized character count, cache hits/misses, and instrumented
worker queue/run/resume timing. No additional worker pool is created.

Sage first visible output above 3,000 ms produces a `first_output.slow` record
in the existing size-capped, three-calendar-day diagnostic log. This is an
investigation target, not a timeout or a context truncation rule. Sage-side
latency excludes the additional Ling boundary overhead; use the hourly Ling
metric for end-to-end assessment. Thread offloading does not eliminate the
Python GIL or upstream model latency, so production samples remain necessary.

A post-deployment sample showed budget worker execution at 0.4–11 ms but
resumption delayed by 220–429 ms. A concurrent event-loop sample pointed to
full parameter JSON conversion inside `list_tools_simplified`. That discovery
path now requests name/description metadata only, using the same localization
and fallback logic without visiting parameters or return schemas. Full provider
schema generation remains unchanged. Tests compare metadata against full
schemas across built-in tools and languages, and reject any parameter/return
access during simplified discovery.

## One-second framework overhead target

`request.first_output` and `request.completed` are small per-execution summaries
in the same capped, three-calendar-day file. They retain only IDs and numeric
aggregates (at most 16 stage counters); no interval history or message payloads.
For `/api/chat` and `/api/stream`, the clock starts at handler entry, before
configuration lookup and session preparation. It excludes upstream Ling work,
FastAPI authentication/body parsing before handler invocation, and transport
work after Sage's visible output. Other callers start at `mark_request_execution`
or, if unavailable, `prepare_session`.

`framework_overhead_ms` is elapsed wall time minus the **union** of model SDK
create/stream-read awaits and tool execution. Parallel waits and a model called
inside a tool are not double-subtracted. `model_wait_union_ms` includes SDK and
network time; it is not provider-only inference time. Work between stream reads
is outside model time. `tool_execution_union_ms` is reported separately and is
excluded from the one-second target. `non_model_ms` is the older literal
elapsed-minus-model quantity and still includes tool execution; use
`framework_overhead_ms` and `framework_target_ms` for the new target.

The first-output and completed summaries share an execution ID and have
independent statuses. A multi-step turn can accumulate over one second of
framework overhead even when first output is fast. Concurrent local work hidden
behind a model/tool wait is not on this uncovered wall-clock path; the existing
loop watchdog and thread CPU/run/resume diagnostics still detect such work.
Recorded preparation stages include config/dispatch, lock/validation, service
construction, client construction, workspace assets, conversation lookup,
Sage session preparation, budget calculations and memory search. Stage durations
can overlap or nest; do not sum them as mutually exclusive buckets.

Client creation now runs in the existing instrumented thread executor because
SSL trust-store loading and lazy SDK initialization are synchronous. It performs
no network request until the client is used on the requesting event loop.
Standard/fast models reuse one client only within the same request when endpoint
and credentials are identical; different providers or credentials remain
isolated. Shared clients are closed once. Cancelled construction disposes of an
unclaimed client when its worker completes and releases the session run lock.
The stream accounting scope resets before yielding, allowing disconnect cleanup
from another task without crossing ContextVar token boundaries.

The first production sample exposed 575 ms of one-time SDK resource loading in
the worker. Server lifespan now constructs and closes one dummy client before
accepting traffic to move this cold cost out of user requests. It uses a reserved
`.invalid` endpoint and makes no model/network call; subsequent request clients
remain independently owned and use their current configured credentials.

A concurrent batch also sampled host SkillManager recursive file-tree scanning
on the event loop. Request skill-proxy construction now uses the same existing
instrumented executor; metadata, instructions, file trees, caller workspace and
Agent-owner skill precedence are preserved. Its elapsed/queue/run/resume times
are separate from model-client creation. This does not alter tool execution or
cache mutable skill contents across requests.
