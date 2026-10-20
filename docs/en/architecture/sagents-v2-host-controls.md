---
layout: default
title: Host Control Interfaces
parent: Architecture
nav_order: 20
lang: en
ref: v2-detail-sagents-v2-host-controls
---

{% include lang_switcher.html %}

# Desktop and Server standard control interfaces

This audit records Sage v2 host entry points and SDK calls on 2026-10-19.

| Operation | Desktop | Server | Standard contract |
| --- | --- | --- | --- |
| Start | `/api/v2/runs/stream` | `/api/agent`, package runs, external Runs, A2A | `load_agent`, then `entrypoint().run_stream` or public `run_interface` adapters |
| Reply to approval or interaction | `/api/v2/runs/{run_id}/interactions/reply` | `/api/threads/{thread_id}/resume`, `/api/approvals/{run_id}/decisions`, external `/reply` | `runtime.reply_interaction(ReplyInteraction, context)`; approval cancellation uses `CancelRun` |
| Cancel | `/api/v2/runs/{run_id}/cancel` | Thread/external `/cancel`, A2A cancellation | `runtime.cancel_run(CancelRun, context)` |
| Pause | `/api/v2/runs/{run_id}/pause` | No separate manual-pause HTTP endpoint | `runtime.pause_run(PauseRun, context)` persists at a safe point |
| Resume | `/api/v2/runs/{run_id}/resume` | Thread `/resume` distinguishes suspension type | Accept `ResumeRun` or reply to interaction, then `agent_for_run` and `entrypoint().continue_run` |
| Restart recovery | Standard App, persisted versions and scheduler | Same | Restore original Run, graph, frozen configuration and resource leases |
| Publish candidate Session | Run `/commit-proposals`, proposal `/publish` and `/reject` | No corresponding HTTP endpoint | Entrypoint `propose_session_commit`, `publish_session_commit`, `reject_session_commit` |
| Goal/Plan submission | Declared standard tools | Same | Official Goal/Plan tools and continuation policy |

Desktop paths include `/api/v2`. Server external paths start with `/api/agents/{agent_id}/runs/{thread_id}/{run_id}`. A thread resume request's `runId` identifies a new AG-UI observation stream, while the native Sage Run remains unchanged.

State commands require authenticated `RequestContext`, revisions and idempotency keys. Pause reaches a safe point; cancellation, execution exit and resource release happen at different times. Detach disconnects observation. Shared nested resource recovery is documented in [Run tree recovery](sagents-v2-run-tree-recovery.md).

Accepted `continue_run` schedules the original Run. Repeated continuation observes active execution or returns an existing terminal result, without creating Runs or replaying completed tools. Suspended Runs first need the corresponding state command.

Candidate publication uses the original Agent version and triggers enabled long-term memory writes only after success. Rejection does not write candidate memory. Hosts use the standard entrypoint to retain this behavior rather than raw `runtime.publish_session_commit` alone.

Desktop preflight failures now return structured HTTP errors without placeholder Runs or fabricated Agent hashes. Accepted failures are recorded by the SDK with their original classification, quota data and localized diagnostics. Server removed unused model binding and manual sandbox lifecycle paths. Auxiliary concurrency uses public `sagents.v2.concurrency`, which does not control Agent execution. Frontend command and environment allowlists now use registered execution policy parameters, with explicit user fields taking precedence.

Hosts retain authentication, catalogs, settings, protocols, event display, product callbacks and file management through public contracts. They do not reconstruct loops, official tool runtimes or Team executors. Trusted raw SessionStore access does not replace caller-authorized `session.access`.

Regression tests cover standard publication/rejection, memory writes, original versions, repeated continuation, pause, authorization, Desktop preflight and restart. Source checks prevent private SDK imports, executor assembly, component replacement and direct `provision()` calls. Local tests do not establish multi-day endurance or Linux browser-image acceptance; the prior Chromium failure still needs a fresh candidate-image run.

## Validation record

macOS / Python 3.13; native sandbox tests ran with process-monitoring permission.

| Scope | Result |
| --- | --- |
| Initial SDK + Desktop + Server | 4186 passed, 56 skipped; one native PATH test exceeded its three-second deadline |
| Final Desktop + Server, controls and unchanged PATH retest | 900 passed, 1 skipped |
| Final SDK controls, facade and dispatcher lifecycle | 38 passed |
| Ruff, compilation and `git diff --check` | Passed |

These suites overlap and must not be added. The original timeout passed unchanged on retest. Skips include optional services, platforms and opt-in acceptance; the final host skip required external MySQL.
