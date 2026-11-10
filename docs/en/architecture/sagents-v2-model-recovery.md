---
layout: default
title: LLM Error Recovery
parent: Architecture
nav_order: 12
lang: en
ref: v2-model-recovery
---

{% include lang_switcher.html %}

# LLM Error Classification and Bounded Recovery

Providers identify protocol facts, `ModelRecoveryPolicy` selects an action, and the Agent Loop and auxiliary callers execute it. Generation ending and the user's task being complete are separate decisions. Recovery does not switch providers or models automatically.

## Contracts

`ModelResponse.termination` is an optional, automatically normalized termination state: `complete`, `tool_calls`, `truncated`, `paused`, `refused`, `empty`, or `unknown`. The original `finish_reason` is retained. Empty output is checked even with missing usage or output_tokens=0. Reasoning alone cannot replace a deliverable answer.

`RuntimeErrorInfo.metadata.model_failure` carries a `model-failure/1` descriptor, including category, phase, provider, HTTP status, native code, termination reason, wait time, usage, and side-effect state. Legacy clients can still read `retryable`, but recovery decisions no longer depend on that flag alone.

Shared classification covers transport, overload, temporary rate limits, hard quotas, authentication, permission, routing, request parameters, context limits, media/request size, output truncation, tool arguments, empty output, interrupted streams, protocol/state errors, refusal, capacity, and unknown errors. Structured errors inside HTTP 200 responses use the same classification. Unknown errors stop by default rather than being assumed temporary.

## Default Budgets

| Control | Default |
| --- | --- |
| Additional identical retries | 2 |
| Empty/reasoning-only guidance | 1 |
| Argument and structured-output repairs | 2 |
| Each parameter negotiation | 1 |
| Context repairs | 6 |
| Total additional requests per recovery episode | 6 |
| Recovery episode deadline | 120 seconds |
| Total additional recovery requests per Run | 24 |

All limits apply together. Exponential backoff starts at 1 second, caps at 30 seconds, and includes jitter. A valid server `Retry-After` is a minimum wait. Recovery stops if waiting would exceed the remaining deadline. Framework-created OpenAI SDK clients use `max_retries=0`. Injected clients should also disable implicit retries; the framework cannot account for unobservable internal network requests.

Configure finite budgets through `RunConfig.model_recovery`. Explicit integers in the legacy `transient_retry_limit` remain supported. For new Runs, `None` now means the finite default, not unlimited retries. Conflicting explicit old and new settings are rejected.

## Recovery Behavior

- Transport, overload, temporary rate limits: bounded identical retries. Hard quotas, authentication, and permission failures stop.
- Empty output: add one inference-only runtime guidance message. It does not become a real user message or add authorization. Committed tool results are reused without replaying tools.
- Invalid/truncated argument JSON: regenerate complete calls in smaller batches; incomplete calls are never executed.
- Context overflow: request compression and require actual input reduction; stop when no reduction is possible.
- Text truncation, format validation, and no-progress correction: continuation/correction requests also consume recovery budgets.
- Refusal, safety filtering, unknown termination reasons: do not treat these as empty output or repeatedly request a bypass.
- Native server-side tool pauses: stop explicitly when the route cannot safely continue; this change adds no server-side tool capabilities.
- Media, signature, schema, and similar failures stop when no reliable repair is available, without silently dropping input or inventing state.

Auxiliary calls use a task-local scope and cannot share counters across independent operations. Invalid Judge output receives at most two corrections; failure cannot fall back to treating any text as completion. Tool selection validates JSON structure and available names; failure cannot enable all tools. Built-in simulators and optimization callers recognize recovery stop markers instead of restarting an entire evaluation. Capability probes allow only transport recovery and disable negotiations that change the parameter being tested.

Judge, tool-selection, and memory-query timeouts apply to each model request and enter the same bounded retry policy. Exhausted Run or recovery-episode deadlines still stop immediately. Memory queries validate their JSON contract at runtime, retaining fenced-JSON compatibility without requiring native provider schema support. Truncated structured output must regenerate a complete object instead of passing partial JSON to a business parser.

Only successful completion of the outer semantic operation releases episode counters and deadlines. Nested summaries, JSON corrections, and unresolved main calls retain the same recovery budget. Completion is persisted before release; restart does not resurrect a closed deadline from an older checkpoint. Run-wide recovery counts are always retained.

## Persistence and User Experience

The Agent checkpoint codec is `agent-loop/4` and reads older versions. Legacy retry counts import as consumed budget. Main calls persist a checkpoint before recovery; auxiliary calls persist recovery events. Dispatch markers are persisted before sending. Restart restores reservations without refunding possibly sent requests; an unconfirmed dispatched request cannot reuse the same reservation. Auxiliary calls record dispatch/completion through `step.recovery_dispatched` and `step.recovery_completed`, without emitting duplicate retry notices.

`error.metadata.recovery` in `step.retry_scheduled` contains the version, action, count, deadline, and reason. At termination, `failure_summary` provides a deterministic explanation, recorded tool-call references, and correlation IDs. Error explanations require no further LLM call, and existing artifacts do not imply task success. Clients retain messages and artifacts and clear loading state at termination.

Event categories, actions, counts, and stop reasons support aggregation of recovery success and cost. Raw payloads, credentials, and complete tool arguments must not become user messages or metric labels.

## Validation and Migration

Run `tests/sagents/v2/test_model_recovery_policy.py` together with the four provider, Agent Loop, auxiliary-call, and protocol-conversion tests. Synthetic empty-response session tests verify that successful tools execute once and that one guided recovery either completes or stops explicitly.

Migration changes include finite default retries, disabled SDK retries, and a new checkpoint codec. Old binaries are not guaranteed to restore new checkpoints. Real API smoke tests and production deployment require the relevant service environment; offline protocol tests do not establish live-service acceptance.
