# AgentBench DB for Sage RSI

This adapter includes official DB tasks, MySQL lifecycle management, SQL MCP,
a scorer, and the import dataset.

## Scope and scoring

- Source: [AgentBench](https://github.com/THUDM/AgentBench), commit
  `d1e4a10db08c87075c78972e48ecc182be03e2d5`. See `vendor/LICENSE` and `upstream.json`.
  This is DBBench at that commit, not an exact recreation of the 2023 paper setup.
- All 300 official `standard.jsonl` tasks are included. The 60-task `dev.jsonl`
  is retained for provenance but excluded from the default pool.
- Seed `20261023` splits table families into **234 train / 32 dev / 34 test**.
  Queries and write variants for one table stay together. These are internal splits.
- `execute_sql(query)` uses real MySQL and official 800-character result truncation.
  The first `commit_final_answer(answers: list[str])` ends the task. The SQL limit
  is 50, distinct from the upstream 15-model-round budget.
- Official `_build_init_sql` initializes TEXT columns; official `DBResultProcessor`
  grades answers. SELECT uses official normalization/comparison. Writes use official
  hashes of actual table contents. Scores are 0 or 1, independent of text claims.
- The adapter omits upstream AgentRL/Redis orchestration. A typing-only Database
  stub supports the official processor; mysql-connector-python 9.3.0 executes SQL.
  SQLite does not replace MySQL. Answers remain `list[str]` to avoid the upstream
  cleaner's string-eval branch.

## 1. Start MySQL

Install and start Docker Desktop/Engine. From the repository root, use a prepared
Python 3.12 environment; skip creation if `evaluation_datasets/agentbench_db/.venv` already exists:

```sh
python3.12 -m venv evaluation_datasets/agentbench_db/.venv
evaluation_datasets/agentbench_db/.venv/bin/python -m pip install -e '.[desktop,test]' -r evaluation_datasets/agentbench_db/requirements.txt
evaluation_datasets/agentbench_db/.venv/bin/python -m pip check
evaluation_datasets/agentbench_db/.venv/bin/python -m evaluation_datasets.agentbench_db.manage start
evaluation_datasets/agentbench_db/.venv/bin/python -m evaluation_datasets.agentbench_db.manage status
```

Start pulls Docker's official `mysql:8.0.36`, records the image ID, and runs real
SQL preflight. It uses 1 GB RAM, 2 CPUs, a 512 MB tmpfs, and a random loopback port.
This pins the patch version and reduces resources from the upstream setup.
GPU is not required.

The container is labeled `sage.rsi.dataset=agentbench-db`. A random benchmark-only
password is stored in gitignored `.runtime/connection.json` with mode 0600.
Do not use a production database or commit this file. Each replay creates a task
database and a user restricted to it, without FILE/global privileges, then removes
both. A process lock serializes rebuilds; the Agent never receives admin credentials.

Manage the service explicitly. The scorer does not start Docker. Missing services
and connection failures are errors, not fabricated zero scores. Forced termination
may leave task databases; stop/start clears the dedicated container:

```sh
evaluation_datasets/agentbench_db/.venv/bin/python -m evaluation_datasets.agentbench_db.manage stop
```

## 2. Configure Desktop

1. Add [mcp.example.json](mcp.example.json) as stdio MCP named **`AgentBenchDB`**.
2. Replace all repository/state paths and keep `SAGE_RSI_CASE_PROTOCOL=sage.rsi.case/v1`.
3. Create an Agent using [policy.md](policy.md) and this MCP's tools only.
4. Import `rsi.dataset.json`, then import and select `scorer.py` after self-tests pass.
5. Start with 6 training cases, 0 new cases per round, 1 round, concurrency 1, and 1 repeat.

MCP and `scorer.py` use this directory's `.venv`. Keep `scorer.runtime.json`
beside `scorer.py` when importing. Restart Desktop after updating Sage, and reimport
the scorer after changing its environment. See
[Python environments](../README.md#python-environments).

Each case/version/repeat has an isolated state directory. SQLite logs calls;
reconnects rebuild the official initial state and replay SQL. Execution without an
active case is rejected. Replaying each tool call is slower for long trajectories.
Nondeterministic SQL that cannot reproduce a result fails measurement.

The scorer reads canonical `final_items`, replays completed native calls, and checks
tool results. Denied calls, missing dependencies, and mismatches are errors, not
zero grades. MCP provides no references, scoring, reset, or dataset-query tools.
Keep hidden task files out of Agent file/Shell permissions. Only committed task IDs
are supported; keep test evidence separate from tuning and candidate selection.

## Regenerate and test

```sh
evaluation_datasets/agentbench_db/.venv/bin/python -m evaluation_datasets.agentbench_db.export_dataset
evaluation_datasets/agentbench_db/.venv/bin/python -m pytest -q tests/sagents/v2/test_world_rsi_datasets.py -k 'agentbench_db or db or mysql'
SAGE_TEST_DB_MYSQL=1 evaluation_datasets/agentbench_db/.venv/bin/python -m pytest -q tests/sagents/v2/test_world_rsi_datasets.py -k mysql
```

Scorer import tests check official SELECT pass/fail comparison without SQL.
Passing them does **not** prove MySQL readiness; run manage start/status separately.
The opt-in MySQL tests require Docker and cover real writes, missing-write failure,
replay isolation, and denied global-table access. Without Docker, those tests skip.
Run them on a Docker-capable machine before a full experiment. Adapter tests alone
do not establish official leaderboard equivalence or model improvement.
