# Capability-declared evaluation plugins

The recommended Python plugin protocol is `sage.rsi.evaluation/v1`. A plugin can
prepare evidence, judge, analyze and summarize training directions. Missing stages
run through the configured Eval Agent. Existing `score(request)` plugins and
`prepare`/`compare` comparison plugins keep their original protocols.

## Declaration

Export a top-level dictionary:

```python
EVALUATION_CAPABILITIES = {
    "protocol": "sage.rsi.evaluation/v1",
    "mode": "pairwise",  # or "absolute"
    "prepare": True,
    "evaluate": False,
    "analyze": False,
    "summarize": False,
    "evaluation_includes_analysis": False,
}
```

Only `mode` is required; booleans default to false. Declare at least one operation.
Export the corresponding functions below. Sync and async functions are supported;
inheritance is not required. Prose reasons do not count as declared analysis.

Also export `EVALUATION_CONTRACT` (1–16,000 characters) and
`EVALUATION_TEST_CASES` (1–10 tests covering every declared operation).
Import validation checks functions, output schemas and tests without live models.
Dependencies and the selected Python environment are frozen. Use
`EVALUATION_DEPENDENCIES` for extra static resources and `scorer.runtime.json`
for a dataset-local interpreter.

## Functions and outputs

Functions receive JSON dictionaries. Corresponding Pydantic schemas are exported
from `sagents.v2.optimization`. Unknown fields and invalid modes fail validation.

| Function | Request | Output |
| --- | --- | --- |
| `prepare(request)` | `ComparisonPreparationRequest` | `PreparedComparisonArtifact` |
| `evaluate(request)` | `EvaluationRequest` | `EvaluationResult` |
| `analyze(request)` | `AnalysisRequest` | `OptimizationDiagnosis` |
| `summarize(request)` | `SummaryRequest` | `OptimizationDiagnosisSummary` |

Every request includes `goal`. Preparation also receives a stable capture ID,
case, native observation and host-owned artifact directory. See
[comparison artifacts](PAIRWISE_EVALUATION.md) for hashes and capture boundaries.
Absolute plugins that write files also require a host artifact directory; Desktop
supplies one. Missing evidence never becomes an invented score.

Native observations include a host-owned `workspace_attestation` with protocol
`sage.rsi.workspace/v1`, the native `run_id`, and absolute `roots` for the default
execution workspace and its aliases, distinct from the package staging directory. Match the run ID before mapping absolute
file arguments into this namespace. This metadata grants no filesystem access.
Keep paths outside the declared roots rejected; never infer a root from model text.

Completed local runs also capture `workspace_files` (`sage.rsi.workspace-files/v1`)
before cleanup. It binds final UTF-8 files and SHA-256 hashes to the native run.
Only `complete: true` snapshots can supply final bytes. Validate the run ID,
hashes, bounds and recorded mutation paths. This resolves overlapping file edits
without guessing execution order. Incomplete snapshots retain receipt replay.

Structured internal replies use the terminal assistant message. Progress messages
and tool results remain in the execution archive. File-backed analysis continues
to use the declared assessment file.

Evaluation receives either `observation` with optional prepared `evidence`, or
anonymous `A` and `B` artifacts. Return exactly one judgment:

```json
{
  "protocol": "sage.rsi.evaluation.result/v1",
  "comparison": {
    "winner": "A",
    "rationale": "A has stronger visual rhythm and coherent typography."
  },
  "analysis": {
    "summary": "A uses spacing and type scale to establish hierarchy.",
    "findings": [],
    "strengths": ["Both outputs remain legible on mobile."],
    "uncertainties": ["Static images do not establish interaction quality."],
    "coverage": "All supplied desktop, tablet and mobile images.",
    "next_action": "test_hypothesis",
    "next_verification": "Test a consistent spacing scale while preserving legibility."
  }
}
```

For absolute mode return `grade` with numeric `score` in [0,1], boolean `passed`
and nonempty `rationale`, and omit `comparison`. Pairwise mode uses A/B/tie;
the host computes preference rates. Do not fabricate absolute quality scores.

Set `evaluation_includes_analysis: true` when evaluation provides structured
analysis. Omitting promised analysis fails the contract; Sage does not silently
repair a false declaration. Embedded `grade.diagnosis` and `comparison.analysis`
are also accepted. Undeclared analysis does not disable the configured fallback.

Otherwise Sage calls the declared `analyze`, or asks the Eval Agent to analyze.
If the plugin only prepares visual evidence, the Eval Agent can combine judgment
and analysis. Diagnostic files require separate blind judgment and analysis calls.
Analysis-only plugins receive the Eval Agent's fixed judgment.

The initial pairwise baseline has no judgment yet. Sage calls `analyze` with
one observation and its prepared evidence, and `result: null`. Analyze that
artifact against the goal; do not compare it with a duplicate or invent a score.
Missing comparison is expected here, not a measurement failure. A plugin must
declare `analyze` to replace this initial analysis; combined evaluation analysis
only covers calls that actually make a judgment.

Analysis findings include category, cause, evidence indexes, recommendation, scope
and confidence, alongside strengths, uncertainties, coverage and next verification.
Indexes identify submitted results: 0 for a single result, or 0=A and 1=B.
Explain screen/page details in the finding. Distinguish visual symptoms from causal
hypotheses; an image does not prove why a policy caused a design choice.

## Visual evidence

Prepared artifacts can select images explicitly:

```python
{"artifact": {"presentation": {
    "text": "Desktop, tablet and mobile captures.",
    "images": ["/host/capture/contact-0.jpg"]
}}, "files": [{"path": "/host/capture/contact-0.jpg", "sha256": "...",
               "size_bytes": 12345, "media_type": "image/jpeg"}]}
```

Only declared frozen PNG/JPEG/WebP files become native image blocks in the Eval
Agent input. Source code, paths and private metadata are not automatically shown.
The brief, goal and fixed rubric are always included. Files are checked before
and after assessment. Use a vision-capable Eval model. Dataset rendering stays
outside the Sage core.

## Training directions and complete replacement

After case analysis, `summarize` receives only training diagnoses, goal,
constraints, allowed optimization scope and current policy. It returns summary,
priorities with supporting training case IDs, uncertainties, `next_action` and
`next_verification`. Allowed actions are `test_hypothesis`, `measure`,
`measurement_issue` and `no_change`. Unknown case IDs fail validation.
Directions guide the Tuner; they do not redefine the goal or grant permissions.

If summary is not declared, the Eval Agent performs it. A plugin supplying
evaluation with analysis plus summary completely replaces these Eval Agent stages.
Dataset admission, semantic authorization checks and target execution remain
separate host responsibilities.

Initial training captures receive analysis before tuning begins. Pairwise records
retain both presentation-order judgments and analyses, with host-private mapping
to the candidate side. Judges do not see this mapping. Training feedback may use
it; dev/test analyses stay outside tuning and direction summaries. Initial
capture placeholders are not quality scores or evidence of improvement.

## Self-tests

Each test has `operation`, `request` and `expected`. Expected fields equal their
corresponding validated output fields. A prepare test can check `artifact`.
Every declared operation needs a test. Optional `model_responses` provide recorded
ModelResponse objects for offline tests. Real plugin operations can use
`get_model_provider()`; the plugin owns its prompts and parsing. Preparation
needs no model access.

See [Web Design](../../../evaluation_datasets/web_design/README.md) for a complete
prepare-only plugin, original dataset, native file tools and real browser preflight.

## Diagnostic attachments

`PreparedComparisonArtifact.diagnostics` optionally declares `text` and `files`.
Each file must be a declared frozen UTF-8 JSON, HTML, CSS, JS, SVG or TXT file.
These attachments are not shown during the blind judgment. They are supplied only
to the subsequent fixed-judgment analysis. The configured Eval Agent's existing
file protocol provides bounded read ranges, protected inputs and verified read
coverage, while images remain native image blocks. Every request retains the goal.
A prepare-only plugin with these attachments gets separate judgment and analysis
calls. Full-replacement plugins retain control of their declared evaluation stages.
