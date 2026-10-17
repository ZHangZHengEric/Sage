---
layout: default
title: Context Budgets
parent: Architecture
nav_order: 6
lang: en
ref: v2-detail-sagents-v2-context-budget
---

{% include lang_switcher.html %}

# v2 Context Compression

Local input-token estimation, calibration and preflight token gates are removed. Configured model input limits remain compression triggers: actual provider input usage at or above the configured limit minus explicit reserves schedules compression before the next request. Cached usage is a subset of input usage. New input size is known only after API feedback; output-token limits still go to the API.

API context rejection triggers compression immediately, with at most six retries per uncommitted main step. Summary requests first send the complete source, including the previous checkpoint. Only API overflow splits it in half; both halves must complete before merging. Format retries and transient retries share a 64-call operation quota and splitting is limited to depth 12.

Main inference, tool selection, completion judging and memory-query generation handle API overflow. Transient failures retry with bounded backoff. Empty or expanding summaries, exhausted quotas, permanent errors and cancellation never commit partial coverage.

Compression changes inference views only. Canonical messages, Tool results, media references and events remain intact. The exact latest user request is retained. Parallel Tool batches are atomic; completed batches in a long current turn can also be summarized. Durable references must come from the Tool. Successful Tool calls are never replayed by model recovery.

Usage- or API-overflow-triggered summaries advance through completed history up to the most recent `protected_recent_units` conversation units (default 4), rather than selecting only part of the history before the latest user request. Completed active-turn Tool batches and their image followups may enter the summary; the exact latest user request is retained separately. Recent units keep parallel calls, results and image followups together. Short histories retain the existing minimum recovery behavior. This expands coverage per summary without estimating or promising a fixed resulting token count; subsequent API usage remains authoritative.

A checkpoint commits only after the complete selected prefix succeeds, using digest validation and revision CAS. Irreducible mandatory instructions or a single current user input cause a bounded, resumable failure. Proactive usage pressure alone does not fail an otherwise usable request when nothing can be reduced.

Estimator plugins and configuration entries are removed. Persisted `estimated_tokens` fields remain for snapshot compatibility only. Legacy source-token caps are accepted but ignored. Summary output limits remain active.

Run `python -m pytest tests/sagents/v2/test_api_context_recovery.py tests/sagents/v2/test_persistent_summary_context_matrix.py tests/sagents/v2/test_agent_loop_matrix.py`. Real-model acceptance tests in `tests/sagents/v2/live/test_gpt_5_6_luna_scenarios.py` cover reported-usage limits and injected overflow followed by real summaries and Tool execution.

Extended real-API acceptance lives in `tests/sagents/v2/live/test_real_api_context_recovery.py`, including genuine HTTP 422 overflow, reported usage limits, parallel Tools, vision, cancellation, output truncation and filesystem restart. Successful fragments are merged structurally without clipping API-generated facts. Completion-Judge instructions and its JSON contract stay in a system message. Separately labeled HTTP fault-gateway tests cover 401/429/503 and truncated streams; successful responses come from the real model.
