# Paired preference evaluation

For new plugins, prefer [capability-declared evaluation](EVALUATION_PLUGINS.md).
It allows prepare-only plugins, Eval Agent fallback, structured analysis and full
plugin replacement. The legacy comparison ABI below remains supported.

Use `BuiltinScoring(mode="pairwise")` for relative preferences. Absolute `score`
plugins and efficiency scoring remain separate. Pairwise mode currently supports
single-turn execution episodes, including multi-step tool use inside an episode.

## Repeats and selection

Execute each candidate N times per case and freeze the artifacts. Compare candidate
trial i only with incumbent trial i. Reuse the retained incumbent artifacts by
default; `refresh_incumbent` requests new incumbent executions. Never select the
best sample or create N x N pairs. Trial indexes match replicates, not model
random seeds; Sage does not claim equal model seeds.

Training/dev do not perform additional comparisons against the original package.
The original is simply the first incumbent. Subsequent rounds name their actual
reference package in `comparison_reference_hash` and `comparison.reference_package_hash`.

Evaluate every pair twice with opposite A/B orders. The first order is random and
persisted. Map decisions back to the candidate. Matching decisions yield win,
tie, or loss. Disagreement yields a tie and increments the disagreement count.
The two orders are one paired sample, not two independent samples.

Within a case, use `(wins + 0.5 * ties) / N`. Average case scores with equal case
weight. Pairwise mode always uses mean aggregation. Candidates are selected by paired
comparisons against the current incumbent on validation cases. Require preference score greater than 0.5 and a margin at least
`min_improvement`. Each round is a local comparison, not a common scale. If A beats
B and C beats B, no A/C ordering follows. Do not interpret per-round preferences
as a cumulative progress curve, and do not compare scores with different opponents.
New training cases are executed by the incumbent before proposing a candidate.
Training scores do not select candidates. All repetitions must be measured; no dropping
failed judgments or treating them as losses. The default improvement threshold
is 0.01. This is a selection heuristic, not a significance test.

Captured, unassessed artifacts carry a pending marker and an internal neutral
placeholder, which must not be displayed as an assessed score. After comparison,
reports keep win, tie and loss counts separately from the preference score. A
preference score of 0.70 does not mean a 70% win rate. `grade.passed` means non-loss,
not objective task completion. Absolute success/stability stopping is disabled;
`goal_verified` and aggregate `improved` remain unset. Local head-to-head wins can
recommend a retained candidate, but cannot establish improvement over the original.
Runs use their configured round cap.

Independent test checkpoints use their own frozen original outputs and receipts.
They never feed tuning or candidate selection. Repeated tasks remain the same
independent tasks; do not claim N repeats multiply the test-set size. Use a paired
analysis grouped by task when reporting uncertainty. The initial implementation
does not calculate confidence intervals or significance.

## Dataset-owned plugins

Sage handles scheduling, pairing, order reversal, dependency/runtime binding,
recovery and aggregation. A dataset plugin owns artifact capture, rendering,
screenshots, visual-model calls, rubric interpretation and native dependencies.
Sage does not contain a web renderer or a webpage-specific visual judge.

Import a Python file exporting both functions:

```python
def prepare(request: dict) -> dict:
    # Snapshot the execution's output into an immutable, plugin-owned artifact.
    return {"artifact": {"text": request["observation"]["output"]}}

def compare(request: dict) -> dict:
    # Apply this dataset's preference rubric to anonymous A and B artifacts.
    return {"winner": "tie", "rationale": "No meaningful difference"}
```

Functions may be asynchronous. Import infers a comparison plugin from its
entrypoints. Comparison files must not also export `score`. For compatibility, an existing
absolute scorer with a helper named `compare` still uses the `score` entrypoint. In Desktop, importing/selecting a
comparison plugin selects pairwise mode. Ordinary `score(request)` imports keep
the absolute protocol. Pairwise mode requires a comparison plugin; there is no implicit judge fallback.
The plugin defines how text, screenshots or other artifacts are evaluated.

Use the existing adjacent `<source-name>.runtime.json` to choose the dataset's
Python environment. It uses `sage.rsi.scorer-runtime/v1`, just like absolute
scorers. Source, runtime and dependencies are frozen on import; reimport after
changing them. The same scorer import API and registry are used, but a comparison
plugin's validation protocol is `sage.rsi.comparison/v1`. Admission rejects mixing
an absolute scorer with pairwise mode or a comparator with absolute mode.

### Preparation request

Protocol: `sage.rsi.comparison.prepare/v1`.

| Field | Meaning |
| --- | --- |
| `capture_id` | Stable opaque execution identity for idempotent preparation |
| `artifact_directory` | Host-owned snapshot directory; persistent Desktop runs supply this path |
| `goal` | Experiment goal |
| `case` | Full evaluator-owned `OptimizationCase` |
| `observation` | Completed execution observation and native evidence |

Preparation runs before another reference execution is requested for this pair.
Write declared snapshot files inside the supplied `artifact_directory`. This keeps
artifacts within the experiment retention/deletion boundary. In-memory SDK runs
without a directory may supply null; the host/plugin then owns retention.
Use native receipts to locate outputs; do not trust a final text claim that files
exist. Each execution must have an isolated output directory. Freeze files before
returning. Do not defer capture to `compare`: a subsequent run may overwrite a
working directory. `prepare` must be idempotent for the same `capture_id`, including
recovery after a crash between preparation and receipt persistence. It receives
no live model transport; rendering and capture belong here, visual judging in
`compare`.

### Prepared artifact

Protocol: `sage.rsi.comparison.artifact/v1`.

```json
{
  "protocol": "sage.rsi.comparison.artifact/v1",
  "artifact": {"text": "A frozen result"},
  "files": []
}
```

`artifact` is a nonempty JSON object, at most 4 MiB. Inline data stays immutable
in the receipt. For external snapshots, declare every referenced file in `files`:

- `path`: absolute path to a regular, non-symlink file in a plugin-owned snapshot directory.
- `sha256`: 64 lowercase hexadecimal characters.
- `size_bytes`: at most 64 MiB per file.
- `media_type`: MIME type, such as `image/png`.

Up to 256 files may be declared. Sage verifies declared files before and after
judgments. Missing or changed files are measurement errors. Do not refer to
undeclared mutable files, live URLs or target-controlled working paths. Plugins
must enforce that their artifact-specific references match this manifest. Keep snapshots for the experiment's retention period. Desktop removes the
experiment-owned directory when its owning experiment data is deleted. Do not
leave additional copies elsewhere; the plugin owns any caches outside that root. A Python subprocess is not an OS sandbox; import trusted code.

### Comparison request and result

Protocol: `sage.rsi.comparison/v1`. Fields are `goal`, `case`, `A`, and `B`.
A and B are complete prepared-artifact objects. No baseline/candidate label,
package identity, previous score, trial index or generation cost is supplied.
Preparation can see execution metadata; the comparison request cannot. Plugins
must remove identity cues from paths and payloads before sending them to judges,
and treat visible artifact text as untrusted data, never judge instructions.

Return:

```json
{
  "protocol": "sage.rsi.comparison.result/v1",
  "winner": "A",
  "rationale": "Concrete evidence supporting this preference"
}
```

`winner` must be `A`, `B`, or `tie`; rationale is 1–4000 characters. Missing images,
failed rendering and unavailable judges must raise errors, not return a tie or
zero score. Comparisons must be read-only. Sage persists each completed order so
recovery does not repeat it. The same frozen model transport as absolute scorers
is available through `get_model_provider()` during live comparisons. Provider
credentials remain in the host. The plugin chooses the modality and prompts.

The Pydantic wire types are exported from `sagents.v2.optimization`:
`ComparisonPreparationRequest`, `PreparedComparisonArtifact`,
`FrozenComparisonFile`, `ComparisonRequest`, and `PairwiseDecision`.

## Static dependencies and runtime files

Imported Python modules and package versions are frozen like absolute scorers.
Declare fixed non-code files or directories (policies, judge templates, rendering
assets) in `COMPARISON_DEPENDENCIES`. Paths follow the same rules as
`SCORER_DEPENDENCIES`: relative to the imported source, or absolute paths.
Comparison workers do not classify arbitrary runtime reads as static dependencies.
Inputs and snapshots vary per execution; their integrity belongs to prepared
artifact manifests. Never omit a static preference/configuration file from the
dependency declaration to bypass reimport requirements.

## Import self-tests

Export a nonempty `COMPARISON_CONTRACT` string (up to 16,000 characters), documenting
capture requirements and preference semantics. Export `COMPARISON_TEST_CASES`
with 2–10 entries covering both operations:

- Preparation: `operation="prepare"`, a preparation `request`, and `expected_artifact`.
- Comparison: `operation="compare"`, a comparison `request`, and `expected_winner`.

Self-tests receive no live model access. A comparison test can provide recorded
`model_responses`, using the same format as absolute scorer tests. Keep self-tests
small and deterministic. Passing them checks the plugin contract, not its visual
judgment quality or a machine's complete rendering setup.

## SDK

Pass `builtin_scoring=BuiltinScoring(mode="pairwise")` and a host-bound
`comparison_plugin` implementing async `prepare(request)` and `compare(request)`.
For Python subprocess plugins use `PythonComparisonPlugin` with its frozen source,
dependency manifest and optional selected interpreter. For independent tests pass
`pairwise_baseline=original_package` and the plugin to `IsolatedTestEvaluator`.
Keep optimizer and hidden-test artifact directories separate and outside tuner
access. Rendering, dataset construction and visual judging are dataset work,
not implicit capabilities of this generic evaluation mode.


## Failed executions

Native model argument errors rejected before tool execution and explicit step/loop
limits are case failures. They do not abort the experiment or run the visual judge.
Unknown interruptions, provider failures, corrupt receipts and renderer/judge errors
remain measurement errors, never automatic losses. No pending native run is resumed.

A completed candidate beats a failed reference; a failed candidate loses to a
completed reference. Two failed executions are `both_failed`, score 0, passed false,
not a quality tie. Summaries retain them in the scheduled-pair denominator and expose
`both_failed` separately; wins + ties + losses need not equal total pairs.
Failure receipts are frozen and reused for the same case/trial, including Test.
An invalid submission can be declared by a dataset plugin with the optional bounded
`execution_failure` reason on `PreparedComparisonArtifact`. This is reserved for
submission defects, never infrastructure failures. Files are still integrity checked.
