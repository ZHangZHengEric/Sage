# ToolSandbox offline tasks for Sage RSI

This adapter includes a dataset JSON, Python scorer, stdio MCP, and dependencies.
Official Python scenarios define the task pool; import `rsi.dataset.json` in Desktop.

## Scope

- Source: [ToolSandbox](https://github.com/apple-aiml-research/ToolSandbox),
  commit `c8571d7854316d2e1c5f288e59fe1e34e53f6dd1`.
- `vendor/` preserves official code, scenarios, milestone/minefield scoring,
  dependencies, `LICENSE`, and `ACKNOWLEDGEMENTS`. Its Apple license is separate
  from Sage's MIT license. `upstream.json` records file hashes.
- The export includes base scenarios without RapidAPI search tools: single-tool,
  multi-tool, multi-turn, and insufficient-information tasks. It excludes tool
  augmentations/distractors and needs no RapidAPI credentials.
- The 95 tasks are split **79 train / 10 dev / 6 test**, using seed `20261023`.
  Related device-state, multi-turn, alt, implicit, and insufficient-information
  variants stay in one task-family split. Counts need not be proportional.

These are internal RSI splits, not official leaderboard splits.

## 1. Install and preflight

Use Python 3.12. Run from the repository root; skip environment creation if
`evaluation_datasets/toolsandbox/.venv` is already prepared:

```sh
python3.12 -m venv evaluation_datasets/toolsandbox/.venv
evaluation_datasets/toolsandbox/.venv/bin/python -m pip install -e '.[desktop,test]' -r evaluation_datasets/toolsandbox/requirements.txt
evaluation_datasets/toolsandbox/.venv/bin/python -m pip check
evaluation_datasets/toolsandbox/.venv/bin/python -c 'from evaluation_datasets.toolsandbox.runtime import preflight; print(preflight())'
```

Use this directory's requirements, not upstream's full SDK/development lockfile.
NumPy 1.26.4 and SciPy 1.13.1 support the older Pint/Polars stack; ccy 1.5.0 supports
Python 3.12. The selected langchain-core supports the upstream API and Sage's
tenacity 9. Upstream model-provider clients are not required.

MCP and `scorer.py` use this directory's `.venv`. Keep `scorer.runtime.json`
beside `scorer.py` when importing. Restart Desktop after updating Sage, and reimport
the scorer after changing its environment. See
[Python environments](../README.md#python-environments).
Preflight prints task/tool counts, the pinned commit, and frozen time without model
or search calls. It does not change Desktop settings.

## 2. Configure MCP and an Agent

Add the stdio connection from [mcp.example.json](mcp.example.json), replacing all paths:

- Name: **`ToolSandbox`**.
- Command: the prepared Python interpreter's absolute path.
- Args: `-m evaluation_datasets.toolsandbox.mcp_server --state <absolute-state-path>`,
  entered as the template's JSON array.
- Env: repository `PYTHONPATH` and `SAGE_RSI_CASE_PROTOCOL=sage.rsi.case/v1`.

Verify `mcp_ToolSandbox_*` discovery. A running case exposes only its allowed Agent
tools. Use [policy.md](policy.md) for the baseline and enable these MCP tools only.
User termination, reset, scoring, and database management are not target tools.

Each case/candidate has an isolated state directory. SQLite transactions store JSON
world state and snapshots; reconnects restore that case without sharing other cases.
The adapter does not load pickle/dill console objects from execution records.

## 3. Import and run

1. Import `rsi.dataset.json`.
2. Import and select `scorer.py` after self-tests pass.
3. Start with 6 training cases, 0 new cases per round, 1 round, concurrency 2, and 1 repeat.
4. Increase the run only after checking tools, scoring, and case isolation.

Only exported official scenarios are supported. Do not exhaust the training pool
and then generate tasks without official milestones. For smaller smoke datasets,
use a separate JSON with independent splits. Test evidence is not tuning input.

## Scoring and limits

The scorer replays native `final_items`, tool calls, and user/assistant messages
with official execution roles and `Evaluation.evaluate()`. It rebuilds database
history and uses the official milestone DAG and minefields. Similarity is retained
in `[0,1]`; Sage marks `passed` only at 1. This threshold is not interchangeable
with other benchmarks' success rates.

Scenario creation, tool execution, and scoring use **2024-05-17 12:00:00 UTC** to
avoid date-dependent drift. The clock adapter affects ToolSandbox modules only,
not global process time. Official source and milestones are unchanged.
Replay checks native success/failure results; rejected calls cannot become writes.
Mismatches fail measurement. Supplied similarities, trajectory paths, and success
claims are not scoring inputs.

Sage's generic user simulator follows official user instructions; upstream
`end_conversation` maps to simulator termination. Turn/tool budgets and native
call grouping can differ from upstream parallel-order checks. Report results as
**ToolSandbox offline base / Sage RSI**, not the full 1,032-scenario leaderboard.

## Regenerate and test

```sh
evaluation_datasets/toolsandbox/.venv/bin/python -m evaluation_datasets.toolsandbox.export_dataset
evaluation_datasets/toolsandbox/.venv/bin/python -m pytest -q tests/sagents/v2/test_toolsandbox_rsi_dataset.py tests/sagents/v2/test_agent_dataset_mcp_isolation.py
```

Offline tests cover reproducible exports, family splits, official pass/fail
milestones, false success claims, JSON recovery, scorer processes, and stdio.
They do not establish model improvement. Reconfigure dependencies and absolute
paths on each machine; credentials and experiment history are not included.
