---
layout: default
title: Resource Management
parent: Architecture
nav_order: 4
lang: en
ref: v2-detail-SAGENTS_V2_RESOURCE_MANAGEMENT
---

{% include lang_switcher.html %}

# v2 Runtime Resource Management

This page explains how to limit model calls, waiting requests, and resident applications when several Agents run at once, and when idle resources can be released. Releasing an application instance does not delete its package or Session, or cancel a task.

These limits count different things: the Scheduler limits executing tasks, `ModelConcurrencyBudget` limits active model calls, and the management service limits assembled Applications. A task waiting for a tool may still be running while holding no model-call slot.

## Host integration

```python
from sagents.v2.agent.management import AgentManagementService
from sagents.v2.model import ModelConcurrencyBudget

budget = ModelConcurrencyBudget(limit=8, max_waiting=128, wait_timeout_seconds=60)
service = AgentManagementService(
    root,
    builder_factory=build_package,
    authorize=authorize_package,
    model_budget=budget,
    require_readiness=True,
    auto_release_idle_seconds=300,
)
report = await service.validate(bundle, context, readiness=True)
reclaimed = await service.release_idle(min_idle_seconds=300, limit=4)
metrics = service.capacity()
```

The host supplies root, bundle, context, and callbacks. All relevant services and Builders must share the same budget object; ordinary Builders use `with_model_budget(budget)`. Without a shared injection there is no cross-Application total limit.

## Resource readiness

`validate(readiness=True)` answers whether the declared tools and Skills can currently be discovered. The overall result is `readiness.ready`; each Agent’s `missing_tools`, `missing_skills`, and `unverified` fields are under `readiness.agents[agent_id]`. `valid=True` means configuration, composition, and initialization passed, not that a task will succeed.

For example, a package may reference a Skill that has been removed. An ordinary readiness check can return `valid=True` and `readiness.ready=False`, listing the missing Skill. Strict mode, described below, raises an error instead.

`require_readiness=True` blocks saving and new Runs when resources are missing or unverifiable. Repeated saves of the same ref and cached instances are revalidated, returning the actual report and reused=True. This has initialization and cleanup costs. Strict mode is off by default. `agent_package_validate` also supports readiness=true.

Checks do not call models, execute tools, or materialize Skills. Bindings verifiable only within a real Run are unverified and rejected in strict mode. Credential validity, remote execution, and Skill content loading require separate probes. Discovery cannot expand authorization.

## Model slots and queueing

`ModelConcurrencyBudget` limits provider streams and explicit capability probes. A slot covers the complete stream lifecycle and is returned on failure, cancellation, or early close. Waiting for tools or recursively creating Agents does not retain model slots. Parallel requests inside one provider do not necessarily each occupy a slot.

Defaults allow 128 waiting requests and a 60-second wait. max_waiting=0 admits only immediately available calls. Queue timeout does not terminate calls already inside the provider. A full queue returns model.queue_full; timeout returns model.queue_timeout. Both are retryable, resumable RATE_LIMITED errors. An upstream TimeoutError remains an upstream error. Existing waiters have priority; cancellation does not leak slots.

snapshot() reports limit, active, waiting, max_waiting, wait_timeout_seconds, rejected, and timed_out. The budget belongs to one event loop; it does not limit tokens, process-wide RSS, tool subprocesses, bandwidth, or all Run queues.

Desktop defaults to max_concurrent_model_calls=8, max_waiting_model_calls=128, and model_queue_timeout_seconds=60. Cached runtime model providers share this budget. Direct API rate limits return HTTP 429; Agent execution preserves state and enters the existing recovery interaction, allowing retry. Independent model-validation endpoints do not thereby receive complete host resource limits.

## Safe idle reclamation

The host can call `release_idle()` to release the oldest unused instances, at most `limit` per call. An instance is eligible only when no management operation is using it, its idle time has elapsed, its Sessions can be restored from durable storage, and it has no unfinished tasks. A task waiting for approval is unfinished; a lack of output does not make it safe to reclaim.

Reads, submissions, control operations, and waiting for builds all hold usage counts. Cancellation returns those counts.

Stores must declare durable_across_process_restart=True and support has_nonterminal_runs(). Checks include queued, running, suspended, and child Runs. Unknown and memory stores are skipped. File stores scan unloaded Sessions and journals in a background thread and report corruption. Failed shutdown retains the instance in draining; later close calls can retry.

At capacity, automatic reclamation defaults to safe instances idle for 300 seconds. auto_release_idle_seconds=None disables it; 0 permits immediate reclamation. No safe candidate means a capacity error. There is no periodic scan. Reclamation closes resources and removes cache entries while retaining persistent files; execution or continuation can rebuild the same version.

The service must exclusively manage Applications; hosts must not submit around it. capacity() reports cache, builds, in-flight operations, usage counts, automatic reclamation, cleanup, and model-budget metrics. It is not exposed as a cross-tenant model tool.

## Terminal archives and reads

When status observes completion, before reclamation, and before normal shutdown, results and Flow outputs are archived in inventory. Default AgentPackageStore uses SQLite terminal_statuses; Server inventory uses MySQL managed_agent_records. Reclamation and shutdown paginate unarchived operations in batches of at most 100.

Reads check caller ownership and current read_run authorization first. Archived results require no Builder, model client, or worker. Failed archival does not prevent resource release during normal shutdown; automatic reclamation closes an instance only after successful archival.

SessionStore remains authoritative. A crash may precede archival. Built-in file storage can read snapshots and journals offline, verify checksums, Session identity, and authorization, and archive terminal results. Nonterminal work, old records without locations, and stores without offline reading use recovery composition. Nonterminal state is never cached as a final result.

## Flow and shared JobRuntime

Flow reachability includes conditional edges, parallel branches, subflows, and member subagents, using a visited set to terminate cycles. Only the entrypoint and reachable members initialize models; explicit package validation still checks every Agent.

`InMemoryJobRuntime` defaults to 32 concurrent jobs and 1024 admitted jobs, with per-job byte/chunk and aggregate retained-output limits. Share it with `AgentManagementService(..., job_runtime=jobs)` or `SAgentBuilder().with_job_runtime(jobs)`.

The host owns injected JobRuntime objects. Close users first, then `await jobs.close()`. Without injection, each Application owns its instance and there is no cross-Application total limit. Scheduler queues remain isolated so dispatchers cannot claim another application's work.

## Validation and boundaries

Tests cover readiness, disappearing resources, shared budgets, cancellation, failed streams, suspended-instance protection, reclaim/rebuild, persistent state, corruption, and cleanup failure. See [Agent package management](SAGENTS_V2_AGENT_MANAGEMENT.md) and [single-host concurrency](sagents-v2-single-host-concurrency.md).

There is no guarantee of process-wide memory limits, cross-process fair scheduling, offline reading for arbitrary stores, isolated installation of untrusted source, or long-running real-model capacity. Threads and subprocesses created independently by plugins are not controlled merely by sharing JobRuntime.

Implementation: [service.py](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/agent/management/service.py) · [readiness.py](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/agent/management/readiness.py) · [concurrency.py](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/model/middleware/concurrency.py).
