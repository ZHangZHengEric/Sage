---
layout: default
title: Tool Result Processing
parent: Architecture
nav_order: 24
lang: en
ref: v2-detail-sagents-v2-tool-result-processing
---

{% include lang_switcher.html %}

# Tool result processing

Standard v2 composition enables `tool.result-processor`, using `sage.tool.result-processor.file` by default. It processes results after tool execution or reconciliation, before commit and model history, across built-in tools, MCP, A2A and other providers. Custom loops can inject an implementation through `ToolResultProcessor`.

```yaml
capabilities:
  tool.result-processor:
    plugin: sage.tool.result-processor.file
    config:
      max_inline_characters: 12000
```

`max_inline_characters` limits the combined text and JSON characters in one tool result. It defaults to 12000 and must be positive. Oversized results retain that many original characters, followed by status and a full-file path; the reference notice does not consume the preview allowance. This is not a token, byte or image-size limit. Server defaults and Agent plugin configuration can override it under existing configuration freezing rules.

The complete `ToolExecutionResult`, including untrimmed content, errors and metadata, is saved to `.sage/tool-results/<hash>.json` in the current execution workspace. Signed runtime sandbox operations enforce tenant, directory and quota policy. Server Linux returns `/workspace/...` paths, while Desktop returns native workspace paths. Models can read sections or extract JSON fields with Shell rather than loading the whole result again.

Model history and persisted tool results use the same bounded preview, retaining call and operation IDs, outcome status and nontext blocks such as images. `context_reference` points to the complete file; later context compression may use a reference. Files remain in the workspace after the Run to support interruption recovery and later turns.

If no writable workspace is available or saving fails, the original result remains intact and `tool.result.offload_unavailable` or `tool.result.offload_failed` is recorded. This explicit fallback does not guarantee the inline limit. It must not lose results, report successful execution as a tool failure, or execute the tool again.

Summary compression still responds to model-reported input usage or actual API rejection. When history exceeds the configured recent window (four units by default), retain that window. If at most four units remain and compression is still needed, retire at least one compressible unit per pass. Keep Tool calls and results paired and retain the exact latest user request. Include another unit if selecting only the user anchor would otherwise make no progress. The last complete Tool batch is also compressible. Advisory pressure without new compressible history reuses the summary; actual API rejection may recompress an old summary for recovery.

Compare the input and output tokens reported for the same summary call, rather than judging benefit from the next primary request. Any decrease is accepted without a percentage threshold; the selected source and full request view must also shrink. Continuing pressure advances canonical coverage under the existing attempt and no-progress limits. Authoritative state overrides additional framework-derived task fields returned by the summarizer without retrying the entire summary; missing required fields, invalid types and unknown fields remain errors.

Diagnostic events `context.compression.usage_pressure`, `context.summary.selection` and `tool.result.offloaded` record usage/thresholds, summary versions and selection sizes, and before/after lengths, without business content.
