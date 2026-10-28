# ScienceWorld for Sage RSI

This directory includes the official Java simulator JAR, Python wrapper, original
goldpath ZIP, a verified 125-task subset, MCP, and scorer. Normal runs need no
upstream checkout, task download, or model-based grading.

## Scope and scoring

- Source: [ScienceWorld](https://github.com/allenai/ScienceWorld), commit
  `e8216d6044e8e39be9fcb185e3b2dfb602584b52`. See `vendor/LICENSE` and `upstream.json`
  for the license and source/JAR/data hashes.
- `vendor/goldpaths/goldpaths-all.zip` covers 29 task types, missing index 5.
  The initial selection took 3 train, 1 dev, and 1 test candidate per type: 145 total,
  ordered within each fold by path length and variation index.
- Replaying historical paths in the pinned JAR verified 125 tasks at score 100.
  The default export covers 28 types: **75 train / 27 dev / 23 test**. The other
  20 paths did not reach 100; this does not prove their tasks are unsolvable.
- `data/validation.json` records all checks, excluded IDs, and the JAR hash.
  `data/tasks.json` retains all candidates, original prompts, folds, and evaluator
  reference actions. Exported prompts fix 19 spelling/unit differences against the
  JAR. Reference actions are not sent to the target.
- The original JVM runs without simplification or gold-path generation. `observe`
  returns observation, look, and inventory; `step(action)` allows up to 200 target
  actions. Reset's initial look-around does not count toward this limit.
- Scoring uses cumulative official `info['score']`, clipped to `[0,100]` and divided
  by 100. Partial credit is retained; only 100 passes. Negative scores become zero.
  It is not the last action's delta reward. Completed tasks reject further actions.

The subset favors short, verified paths with uneven type coverage. Do not compare
its score directly with the full official leaderboard.

## 1. Install Java and preflight

Install Java 17 JRE/JDK. Run from the repository root; keep an existing prepared
`evaluation_datasets/scienceworld/.venv` rather than recreating it:

```sh
python3.12 -m venv evaluation_datasets/scienceworld/.venv
evaluation_datasets/scienceworld/.venv/bin/python -m pip install -e '.[desktop,test]' -r evaluation_datasets/scienceworld/requirements.txt
evaluation_datasets/scienceworld/.venv/bin/python -m pip check
evaluation_datasets/scienceworld/.venv/bin/python -m evaluation_datasets.scienceworld.configure --java-home /absolute/path/to/jdk-or-jre-17
evaluation_datasets/scienceworld/.venv/bin/python -m evaluation_datasets.scienceworld.runtime
```

Preflight starts the real JVM and resets a task. GPU and Docker are not required.
On macOS, `/usr/bin/java` may be a placeholder: verify that `java -version` works.

`configure` saves the Java path in gitignored `.runtime/java.json` for both MCP and
the scorer. Rerun it on another machine. It is optional if Desktop's PATH already
contains working Java. Setting JAVA_HOME only for MCP is insufficient because the
scorer sanitizes environment variables. py4j needs local loopback communication;
it makes no external service request.

The adapter imports the unchanged simulator as a namespace because upstream Git
omits generated `scienceworld/version.py`.

## 2. Configure Desktop

1. Add [mcp.example.json](mcp.example.json) as stdio MCP named **`ScienceWorld`**.
2. Replace every repository/state path and keep `SAGE_RSI_CASE_PROTOCOL=sage.rsi.case/v1`.
3. Create an Agent using [policy.md](policy.md) and only this MCP's tools.
4. Import `rsi.dataset.json`, then import and select `scorer.py` after self-tests pass.
5. Start with 6 training cases, 0 new cases per round, 1 round, concurrency 1, and 1 repeat.

MCP and `scorer.py` use this directory's `.venv`. Keep `scorer.runtime.json`
beside `scorer.py` when importing. Restart Desktop after updating Sage, and reimport
the scorer after changing its environment. See
[Python environments](../README.md#python-environments).

Cases, candidates, and repeats have isolated state directories. SQLite records
calls; stdio reconnects replay actions from the initial task. Without an active
case, MCP supports discovery only. Each replay starts a short-lived JVM; begin
with small runs rather than treating this adapter as a persistent environment pool.
Java subprocesses are cleaned up on close.

The scorer replays canonical `final_items` in a fresh environment and checks native
results. Permission failures, missing dependencies, and mismatches are measurement
errors, not zero scores. MCP exposes no answers, scoring, reset, or task lookup.
Do not grant the target file/Shell access to hidden references. Only committed
task IDs are supported; keep test evidence out of tuning and candidate selection.

## Regenerate and test

```sh
evaluation_datasets/scienceworld/.venv/bin/python -m evaluation_datasets.scienceworld.prepare_data
evaluation_datasets/scienceworld/.venv/bin/python -m evaluation_datasets.scienceworld.export_dataset
evaluation_datasets/scienceworld/.venv/bin/python -m pytest -q tests/sagents/v2/test_world_rsi_datasets.py -k 'scienceworld or exports'
```

`verify_reference_paths` reruns all 145 candidates with Java and no model calls.
After changing validation results, rerun prepare_data and export_dataset. Default
exports include only verified full-score IDs. The original ZIP contains a roughly
463 MB JSON, streamed with ijson during regeneration; ordinary runs use the small
committed manifest. Scorer self-tests use a real successful JVM path and a no-action
failure case.

## Native loop guards

`native-v2` can score a single-turn loop-guard endpoint with complete native tool
receipts while retaining the Run's `suspended` state. Reward still comes from
official environment replay. Unconfirmed effects and truncated evidence are not
valid measurements. See [Native episodes](../../sagents/v2/optimization/NATIVE_EPISODES.md).
