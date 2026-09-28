---
layout: default
title: Context Budgets
parent: Architecture
nav_order: 6
lang: en
ref: v2-detail-sagents-v2-context-budget
---

{% include lang_switcher.html %}

# v2 Context Budgets

A model request has a size limit, while conversation history can keep growing. v2 reserves space for fixed instructions and the current request, then fits history into the remaining space. When compression is needed, it summarizes older history. The token counts below are budget estimates, not provider billing measurements.

Trimming and summaries affect only the model-request projection. They do not delete raw Session messages, tool results, or events. Both `system` and `developer` messages are fixed instructions, outside history trimming and summarization.

## Budget boundaries

| Region | Default constraint | Overflow behavior |
| --- | --- | --- |
| Fixed instructions | 16,384 estimated tokens | Fail explicitly; do not truncate or ask a model to summarize fixed instructions |
| Current turn | Latest real user message and everything after it; tool calls stay with results | Use durable references for tool results when available; fail if still too large |
| Earlier recent history | At most 4 units, 8,192 tokens, and 1/3 of the budget remaining after fixed instructions | Move history beyond the protected allowance into the compressible prefix |
| Compressible history | A contiguous prefix, with validated reuse of existing summaries | Summarize in rolling batches without repeatedly summarizing overlapping raw prefixes |
| Request reserve | Tool schemas, hidden tool index, continuation guidance, protocol and output budgets | Reserve first; check the complete request again before sending |

The standard Builder and Desktop use a 32,768-token default window when neither a model window nor an input budget is configured. Configure the actual model window; estimates are not provider billing measurements. Hosts using `DefaultContextAssembler(budget=None)` directly own the total input budget; the fixed-instruction cap still applies.

## Configuration

The smaller Agent/global regional budget wins. This is a manifest fragment:

```yaml
policies:
  budgets:
    input_tokens: 32768
    system_tokens: 16384
    protected_recent_tokens: 8192
agents:
  main:
    budgets:
      system_tokens: 12000
      protected_recent_tokens: 4096
```

`protected_recent_tokens: 0` removes additional protection for history before the current turn; it does not permit deleting the current user request. The Context API fields are `ContextBudget.max_system_tokens` and `ContextBudget.protected_recent_tokens`.

Persistent-summary defaults to `max_summary_calls=4` and `max_summary_source_tokens=24000`, including space for rolling summaries. Tool calls and results are never split across batches. Oversized units without durable references, or too many batches, fail before a summary-model call. Each logical summary starts with one request and retries at most once if the response format is invalid. The default therefore permits at most 8 summary-generation requests, each with its own timeout.

An existing summary may be shortened together with newly compressible history. Output that does not reduce its source or fit the final budget is not saved as derived state; the runtime does not repeatedly enlarge the source and retry. A long tool trace within the latest user request does not automatically become old history; large results should provide durable references.

## Instruction and Skill sources

- `AGENT.md` allows 16,000 characters and fails on overflow. `MEMORY.md` allows 4,096 and `USER.md` 2,048 characters, using explicitly marked excerpts on overflow. SOUL / IDENTITY also use small excerpts.
- **Available Skill lists and descriptions are not truncated by count or characters.** The former 128-item, 12,000-character, and 500-character description caps no longer apply; multiline YAML descriptions are parsed in full.
- **Loaded active Skills** have a default total budget of 6,000 tokens, calculated from XML-escaped injected text. A single oversized Skill is rejected before materialization; loading multiple Skills may evict older active entries. Original files are not truncated, and source-provider file-size limits still apply independently.
- Server Skill descriptions use a long-text column. Reimporting original files repairs previously truncated descriptions.
- The full catalog still counts toward the final fixed-instruction budget. Insufficient total budget causes an explicit error instead of silently omitting Skills.

## Concurrency boundaries and validation

The estimator caches at most 2,048 digests and counts, not full prompts. The built-in additive estimator trims through cumulative counts; custom estimators retain whole-request semantics. Background slots are shared per event loop: 2 for token/fingerprint work, 8 for Skill I/O, and 4 for model summaries. Cancellation does not release a slot while its thread is still running. Filesystem Skill descriptions use a 2,048-entry cache invalidated by file changes.

These are context-preparation limits, not substitutes for Scheduler limits, tenant quotas, model pools, or storage guarantees.

```bash
python scripts/v2/benchmark_v2_context.py --messages 800 --sessions 8
python -m pytest tests/sagents/v2/test_context_efficiency.py tests/sagents/v2/test_skill_provider_matrix.py
```

The benchmark measures synthetic-history trimming, not real-model or database throughput or production capacity.

Implementation: [persistent_reducer.py](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/context/plugins/persistent_reducer.py) · [summarizer_model.py](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/context/plugins/summarizer_model.py) · [provider.py](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/skill/provider.py).
