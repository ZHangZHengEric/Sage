# BFCL V4 multi-turn tasks for Sage RSI

Import a dataset JSON and Python scorer, then connect the per-case stdio MCP.
Pinned data and runtime source are included; no separate upstream checkout is needed.

## Scope

- Source: [BFCL](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard),
  commit `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`.
- `vendor/` contains unchanged data, reference calls, function schemas, environments,
  and scoring code. Hashes: `upstream.json`. License: `vendor/LICENSE` (Apache-2.0).
- Default `rsi.dataset.json`: 200 `multi_turn_base` tasks, split **160 train / 20 dev / 20 test**.
- `rsi.all.dataset.json`: 600 base, miss_param, and long_context tasks, split
  **480 train / 60 dev / 60 test**.
- Seed `20261023` groups category variants of the same task ID into one split.
  These are internal RSI splits, not official train/dev/test splits.
- `miss_func` source data is retained but not exported. It needs dynamic function
  injection per turn, which this adapter does not implement.

## 1. Install and preflight

Run from the Sage repository root with Python 3.12. Skip environment creation if
using an existing prepared `evaluation_datasets/bfcl/.venv`:

```sh
python3.12 -m venv evaluation_datasets/bfcl/.venv
evaluation_datasets/bfcl/.venv/bin/python -m pip install -e '.[desktop,test]' -r evaluation_datasets/bfcl/requirements.txt
evaluation_datasets/bfcl/.venv/bin/python -m pip check
evaluation_datasets/bfcl/.venv/bin/python -c 'from evaluation_datasets.bfcl.runtime import preflight; print(preflight())'
```

Preflight verifies source hashes and loads 600 tasks, function definitions, and
simulated backends without model calls. Do not install `vendor/` as a package or
install its full provider SDK stack.

MCP and `scorer.py` use this directory's `.venv`. Keep `scorer.runtime.json`
beside `scorer.py` when importing. Restart Desktop after updating Sage, and reimport
the scorer after changing its environment. See
[Python environments](../README.md#python-environments).

## 2. Configure MCP and an Agent

In Desktop **Settings → MCP**, add the stdio connection from
[mcp.example.json](mcp.example.json). Replace all placeholder paths.

- Name: **`BFCL`**.
- Command: the prepared Python interpreter's absolute path.
- Args: `-m evaluation_datasets.bfcl.mcp_server --state <absolute-state-path>`,
  entered as the template's JSON array.
- Env: repository `PYTHONPATH` and `SAGE_RSI_CASE_PROTOCOL=sage.rsi.case/v1`.

Verify that `mcp_BFCL_*` tools are discovered. Execution without an active RSI case
is rejected. Discovery lists all tools; a case exposes only its allowed functions.
Official `dict`/`float` schemas map to MCP `object`/`number` without changing behavior.

Create an Agent with [policy.md](policy.md) and the BFCL tools. Do not add file,
Shell, or network tools that could expose references. MCP provides no answers,
scoring, reset, or dataset-query tools. Filesystem, trading, and travel actions
operate in official local simulations.

Each case/version/repeat receives an isolated state directory. SQLite logs calls;
stdio reconnects replay them in the official backend to restore state.

## 3. Import and run

1. Import `rsi.dataset.json`, or `rsi.all.dataset.json` for all supported categories.
2. Import `scorer.py`, wait for its self-tests, and select it.
3. Start with 6 training cases, 0 new cases per round, 1 round, concurrency 2, and 1 repeat.
4. Keep test cases and evidence out of tuning and candidate selection.

Use the fixed pool; generated tasks without supported official IDs cannot be scored.
For a smaller smoke dataset, save a separate JSON retaining independent train/dev/test
splits. Report its measured size rather than claiming full test performance.

## Scoring and limits

The scorer reads canonical `final_items`, replays tool calls by conversation turn,
and runs the pinned official `multi_turn_checker` and `multi_turn_irrelevance_checker`.
It checks per-turn state and accumulated execution results, returning 0 or 1.
It does not use supplied scores or Agent claims.

Replay must match native tool success/failure results. Denied or missing calls
cannot become successful operations during scoring; mismatches fail measurement.

BFCL user messages are scripted. Exported `user_context` asks Sage's generic user
simulator to send them verbatim. The scorer checks messages and turn counts;
script drift returns `not_applicable_reason`, not an Agent score of zero.
The generic simulator is not a dedicated deterministic official runner.

References and initial states remain evaluator-only. Results describe this Sage
adapter, not the complete BFCL V4 leaderboard protocol or a demonstrated RSI gain.

## Regenerate and test

```sh
evaluation_datasets/bfcl/.venv/bin/python -m evaluation_datasets.bfcl.export_dataset
evaluation_datasets/bfcl/.venv/bin/python -m evaluation_datasets.bfcl.export_dataset --categories base miss_param long_context --output evaluation_datasets/bfcl/rsi.all.dataset.json
evaluation_datasets/bfcl/.venv/bin/python -m pytest -q tests/sagents/v2/test_bfcl_rsi_dataset.py tests/sagents/v2/test_agent_dataset_mcp_isolation.py
```

Tests cover export reproducibility, split isolation, official pass/fail scoring,
script drift, missing results, scorer subprocesses, and stdio persistence/isolation.
On another machine, install the repository and dependencies and update all paths;
copying only `scorer.py` is insufficient.
