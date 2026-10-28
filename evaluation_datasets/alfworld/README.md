# ALFWorld text tasks for Sage RSI

This directory includes the pinned text environment, 168 games, dataset, MCP server,
and scorer. Normal runs do not download models, trajectories, or AI2-THOR assets.

## Scope and scoring

- Source: [ALFWorld](https://github.com/alfworld/alfworld), commit
  `aaba6870f86c5be6a08a491f32a50b906227bc3e`. See `vendor/LICENSE` and `upstream.json`.
- Games come from release `0.4.2`, `json_2.1.3_tw-pddl.zip`. Archive details and
  hashes are in `resources.json`; the selected original games are committed.
- `data/tasks.json` fixes 6 task types: 20 train, 4 seen, and 4 unseen tasks per type.
  The split is **120 training / 24 validation / 24 test**, selected with seed
  `20261023`. Each problem has one trial; only solvable, non-movable, non-sliced
  tasks are included. Dev uses official seen tasks; test uses official unseen tasks.
- TextWorld 1.7.0 uses the official `AlfredDemangler`, without shuffled object names
  or expert hints. `observe` returns the current observation and valid actions;
  `step(action)` acts in the world, with a 200-action limit.
- The scorer replays native tool calls in a fresh official environment and scores
  `state['won']`: 1 for success, 0 otherwise. Text claims do not count. Official
  walkthroughs are used only by evaluator self-tests, never exposed to the Agent.

This is a fixed RSI subset, not the full official benchmark or a completed model
optimization result. Keep test evidence separate from tuning and version selection.

## 1. Create the local environment

Keep ALFWorld dependencies separate from the Sage backend:

```text
Sage/
├── .venv/                         # Existing Sage Desktop backend
└── evaluation_datasets/alfworld/
    ├── .venv/                     # Python 3.12: MCP and scorer
    ├── mcp.example.json
    ├── scorer.py
    ├── scorer.runtime.json        # Selects this directory's Python
    └── rsi.dataset.json
```

Run from the **Sage repository root**, with Python 3.12 installed:

```sh
python3.12 --version
python3.12 -m venv evaluation_datasets/alfworld/.venv
PATH="$PWD/evaluation_datasets/alfworld/.venv/bin:$PATH" \
  evaluation_datasets/alfworld/.venv/bin/python -m pip install --no-binary=fast-downward-textworld -e '.[desktop]' -r evaluation_datasets/alfworld/requirements.txt
evaluation_datasets/alfworld/.venv/bin/python -m pip check
evaluation_datasets/alfworld/.venv/bin/python -m evaluation_datasets.alfworld.runtime
```

Success ends with `"tasks": 168` and `"ready": true`. Preflight checks source/game
hashes and resets a real task without model calls. Pass it before starting RSI.
The PATH prefix makes native builds use this Python rather than Anaconda or another
installation. No activation or change to the root `.venv` is needed.

TextWorld and fast-downward need C/C++ build tools. On macOS, install Command Line
Tools with `xcode-select --install`; on Linux, install the corresponding toolchain.
GPU, Java, Docker, and the upstream training dependencies are not required.
On Windows, use `.venv/Scripts/python.exe`; verify native installation and preflight
on that machine before running experiments.

### Apple Silicon architecture errors

If `libdownward.so` is x86_64 but Python needs arm64, rebuild with the local Python
first in PATH, from a native terminal:

```sh
PATH="$PWD/evaluation_datasets/alfworld/.venv/bin:$PATH" \
  evaluation_datasets/alfworld/.venv/bin/python -m pip install --force-reinstall --no-deps --no-cache-dir --no-binary=fast-downward-textworld fast-downward-textworld==20.6.4
evaluation_datasets/alfworld/.venv/bin/python -m evaluation_datasets.alfworld.runtime
```

## 2. Configure MCP

Restart Desktop after updating to code that supports `scorer.runtime.json`.
In **Settings → MCP**, add the stdio connection in [mcp.example.json](mcp.example.json):

- Name: **`ALFWorld`**, with this exact spelling.
- Command: `<absolute-Sage-path>/evaluation_datasets/alfworld/.venv/bin/python`.
- State path: a writable absolute path, such as `/Users/your-name/sage/runtime/alfworld.sqlite3`.
- `PYTHONPATH`: the absolute Sage repository root.
- Keep `SAGE_RSI_CASE_PROTOCOL=sage.rsi.case/v1` and replace every placeholder path.

On Windows, use the Scripts interpreter path. After connecting, verify that
`observe` and `step` are discovered. Execution requires an active RSI case;
ordinary chat calls without case binding are rejected.

## 3. Configure the target Agent

1. Create an ALFWorld Agent and select a model.
2. Use [policy.md](policy.md) as the system instruction.
3. Enable only ALFWorld `observe` and `step` for the initial instruction-only run.
4. Set the Agent loop limit to `256`, allowing room for the 200 environment actions.
5. Do not grant repository file/Shell access that could expose hidden references.

## 4. Import and run

In the Agent's RSI page:

1. Import **`rsi.dataset.json`**.
2. Import **`scorer.py` from this directory**, keeping **`scorer.runtime.json`** beside it.
3. Wait for both scoring self-tests to pass, then select the scorer.
4. Start with these settings:

| Setting | First run |
| --- | --- |
| Optimization scope | System instructions |
| Initial training cases | 6 |
| New cases per round | 0 |
| Rounds | 1 |
| Dev cases | 6 |
| Test cases | 0 |
| Concurrency | 1 |
| Evaluation repeats | 1 |

Example goal: improve official ALFWorld completion rate using general observation,
planning, and action strategies. Starting RSI invokes the configured model.
For a larger evaluation, use 24 dev and 24 test cases, and report how many of the
120 training cases were actually measured. View experiments through RSI history;
internal workspaces are hidden from the ordinary project list.

## Scorer environment and upgrades

`scorer.runtime.json` resolves Python relative to the scorer source directory.
Do not copy only `scorer.py` elsewhere before importing. Desktop keeps its original
backend Python; scorer self-tests and train/dev/test scoring use the ALFWorld Python.

Missing declared Python is an import error, with no host fallback. Interpreter,
package versions, and dependencies are frozen per imported version. Reimport the
scorer and start a new experiment after changing them. Other scorers without a
runtime declaration keep using the host Python. API imports can set an absolute
`python_executable` path.

Each case/version/repeat has an isolated state directory. SQLite records calls;
stdio reconnects replay actions from the official initial state. The configured
ordinary state path is not the active RSI case store.

The scorer verifies native `final_items` and tool results. Denied calls, missing
dependencies, or replay mismatches fail measurement rather than produce a zero.
MCP exposes no scoring, reference, reset, or dataset-query tools. Only committed
task IDs are supported; keep new training cases at 0 unless using the remaining pool.

RSI can optimize instructions and skills. Verified native `load_skill` receipts
are auxiliary reads, not environment actions or rewards. Rejected, forged, or
unverified calls remain invalid measurements. Older scorer bindings stay frozen.

## Execution limits

Successful, nontruncated native results from this MCP with boolean `done=true`
end the target run before another model request (`terminal_on_done: true`).
This does not establish success; the official replay must still report `won`.

Each call has a transaction-committed effect sequence. Scoring uses it to preserve
actual action order. Already-dispatched sibling calls after termination receive
the unchanged terminal snapshot and consume no further environment actions.
The 200th action ends the episode; an unsolved task scores 0. Forged or altered
terminal results fail validation.

`native-v3` can also close a single-turn episode stopped by a native loop guard
when complete, successful native receipts exist. The Run stays `suspended`;
closure alone adds no reward or retry. See [Native episodes](../../sagents/v2/optimization/NATIVE_EPISODES.md).

For long tasks, the RSI API accepts `call_timeout_seconds` (default 240).
Provider timeouts, Agent steps, and the 200-action environment budget remain separate.
Replay restarts from the initial state on each call; begin with concurrency 1.

## Regenerate and test

```sh
evaluation_datasets/alfworld/.venv/bin/python -m evaluation_datasets.alfworld.export_dataset
evaluation_datasets/alfworld/.venv/bin/python -m pip install -e '.[test]'
evaluation_datasets/alfworld/.venv/bin/python -m pytest -q tests/sagents/v2/test_world_rsi_datasets.py -k 'alfworld or exports'
```

`prepare_data.py --archive /path/json_2.1.3_tw-pddl.zip` restores games after checking
archive/game hashes. Exporting needs no download. Tests cover official success and
failure replay, denied calls, altered observations, scorer processes, and stdio isolation.
