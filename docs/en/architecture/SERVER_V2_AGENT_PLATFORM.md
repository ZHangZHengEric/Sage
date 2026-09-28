---
layout: default
title: Server Agent Platform
parent: Architecture
nav_order: 5
lang: en
ref: v2-detail-SERVER_V2_AGENT_PLATFORM
---

{% include lang_switcher.html %}

# Server v2 Agent Platform

Use ordinary chat to send messages to an existing Agent. Use Agent package management in `/studio` when you need to save complete configurations, compare versions, and test a version before activating it. Both use the v2 runtime, but have separate entry points and task workflows.

## Responsibilities and entrypoints

SAgents v2 provides definitions, composition, Flow, execution, persistence, and interactions. Server owns identity, authorization, user catalogs, host configuration, and HTTP/Web entrypoints. HTTP and model management tools use the same AgentManagementService.

Ordinary chat uses AG-UI through `/api/agent`. Full package workflows live at `/api/agent-packages` and `/studio`. Import a catalog Agent as a draft retaining prompts, models, tools, and Skill selection; import does not modify the original Agent, and later edits do not propagate automatically to saved packages.

Studio supports JSON definition editing, Schema/resource checks, save, copy, paginated versions, activation, execution, history, events, cancellation, feedback, approval, and same-Session continuation. It is not a drag-and-drop Flow canvas. Package runs are a separate API workflow, not an AG-UI chat stream.

## Versions and authorization

- Native AgentPackageBundle retains the full manifest and text resources. Immutable ID/version and ref bind complete content. Identical saves are idempotent; changes require a new version.
- Activation compares expected_ref and can reactivate old refs. Existing work does not change versions. Continuation requires the same user, version, Agent, and Session.
- JWT supplies user identity. Inventory, tasks, and events are isolated by owner key; request bodies cannot select another user.
- Models use `provider: server`, with model set to the caller's catalog model ID or default. The host resolves credentials and addresses. Packages cannot override credential, base_url, environment variables, persistence, scheduling, or logging backends.
- Package max_steps is capped at 10000. Memory read/write claims are rejected without a memory backend.
- Model-facing `agent_package_*` tools remain authorized by the host and cannot exercise human approval privileges. HTTP control approve is separately authenticated and checks owner, interaction ID, allowed decisions, revision, and authorization.

## Tools, Skills, and extensions

`ServerHost(package_extensions=..., package_authorizer=...)` registers extensions and authorization. Packages can select authorized flow.node, tool.catalog, and memory.provider implementations; the host fixes other infrastructure. Source extensions are off by default and, when enabled, execute trusted host Python. This is not untrusted-code isolation and does not automatically install dependencies with pip.

ExecutionBindingProvider binds official tools to the user's workspace and sandbox by real Run ID; child Runs get independent bindings. MCP, Skills, and models come from the caller's catalog. Models borrow host-pool leases; credentials never enter package inventory. Skill catalog descriptions are complete; loaded active content has a separate token budget.

Server MCP supports only sse and streamable_http, not tenant stdio commands. Invalid configurations return 422 on save; historical stdio records are skipped on read. One unavailable MCP does not abort the whole Run. Discovery caches are reused by user/configuration fingerprint; `POST /api/mcp/{name}/refresh` invalidates them.

Manage outbound A2A peers through `/api/a2a-agents`. Inbound `/a2a/v1` and Agent Cards mount only when the a2a extra is installed. They require Agent-bound API Keys and a2a:read / a2a:invoke scopes. `/api/keys` manages keys; SAGE_SERVER_PUBLIC_URL can set the published Card address.

## Concurrency and lifecycle

Chat and managed Applications have separate queues and share SchedulerQuotaGroup. Claims and quota checks are atomic, so totals do not multiply with package count. This does not promise strict cross-tenant FIFO; inline child Agents retain core delegation and shared model-budget constraints.

| Configuration | Default | Purpose |
| --- | ---: | --- |
| SAGE_SERVER_MAX_CONCURRENT_RUNS | 8 | Shared execution and model-call slots |
| SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER | 2 | Per-user execution quota |
| SAGE_SERVER_MAX_PENDING_RUNS | 1024 | Shared pending queue and model waiters |
| SAGE_SERVER_MAX_MODEL_CLIENTS | 64 | Model-client pool |
| SAGE_SERVER_MAX_MANAGED_APPLICATIONS | 32 | Managed instances plus build reservations |
| SAGE_SERVER_MAX_MANAGED_BUILDS | 4 | Parallel composition |

The host owns and shares JobRuntime. Shutdown stops execution before closing managed Applications and the main Application. Applications release their owned dispatchers, schedulers, model pools, and other resources. Failed cleanup retains objects for retry. Capacity reclamation requires idle, durably recoverable instances with no nonterminal work; no safe candidate means overload.

Agent, model, MCP, A2A peer, and Skill-binding data occupy separate columns with category-specific in-process locks, preventing unrelated writes from overwriting each other. This is not cross-process CAS.

## Storage and recovery

Production inventory uses MySQL managed_agent_records for versions, active pointers, operations, replies, and terminal archives. Identity fields are indexed; operation and Agent names use binary comparisons.

Sessions use the core MySQL SessionStore. Managed Applications derive separate table prefixes from host-owned persistent paths. Real execution creates table families; validation uses temporary file storage. More versions mean more table families, a deployment cost to plan for.

Startup paginates unarchived operations and rechecks current authorization without resubmitting StartRun. Suspended work retains interactions. An admission_pending operation without a durable handle requires retry with its original operation and input. Recovery failure preserves state and logs the error rather than claiming success.

Archived results need no model initialization. File storage supports read-only cold reads of unarchived terminal state and events; unarchived MySQL results still require composition. Events use a run_sequence cursor with at most 200 per page; Studio shows the latest 100.

## HTTP and deployment

See [HTTP API](../api/HTTP_API_REFERENCE.md) for the complete route inventory, authentication, and conditional mounts. Resource denial returns 403, invisible objects 404, version conflicts 409, capacity/model rate limits 429, and invalid definitions 422.

After building app/server_v2/web, the backend hosts web/dist, including `/studio`. Unknown APIs and escaping file paths never fall back to HTML. Separate frontend hosting with API proxying is also supported; see [Server setup](../applications/WEB.md).

Only one worker is supported. MySQL persistence does not supply horizontal scaling. AG-UI replay reads Session events without Redis. SQLite transactions, scripted models, and synthetic concurrency tests do not replace real MySQL, native-platform, or long-running model-load acceptance.

Implementation: [bootstrap.py](https://github.com/ZHangZHengEric/Sage/blob/main/app/server_v2/bootstrap.py).

Package authorization rules: [policy.py](https://github.com/ZHangZHengEric/Sage/blob/main/app/server_v2/packages/policy.py).
