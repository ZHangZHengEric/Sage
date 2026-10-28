# tau2 retail for Sage RSI

Source: Sierra Research `tau2-bench`, commit
`fc0055dc4e0a316c3f83133267fbd6faaa770992`. Official Python code, retail data,
policies, tasks, splits, simulator instructions, and MIT license are included.
`upstream.json` records file hashes. Business rules and grading logic are unchanged.

The official split has 74 train and 40 test tasks. Seed `20261021` splits official
train into **62 RSI train / 12 dev**; the **40 official test** tasks stay independent.
`vendor/` holds upstream code; the other Python modules provide the Sage adapter.

## 1. Install and preflight

Use Python 3.12 or 3.13. Run from the Sage repository root; keep an existing
prepared environment rather than recreating it:

```sh
python3.13 -m venv evaluation_datasets/tau_bench/.venv
evaluation_datasets/tau_bench/.venv/bin/python -m pip install --upgrade pip
evaluation_datasets/tau_bench/.venv/bin/python -m pip install -e '.[desktop,tau-bench,test]' -r evaluation_datasets/tau_bench/requirements.txt
evaluation_datasets/tau_bench/.venv/bin/python -m pip check
evaluation_datasets/tau_bench/.venv/bin/python -c 'from evaluation_datasets.tau_bench.runtime import preflight; print(preflight())'
```

Use `python3.12` instead if needed. Preflight verifies pinned files and loads
**16 business tools and 114 tasks** without model calls. MCP is pinned to 1.28.1;
`httpx[socks]` supports SOCKS proxies. Voice assets and the full upstream
voice/Streamlit stack are not needed for retail text evaluation.

Offline checks need no model key. Process/stdio/scorer tests need local loopback access:

```sh
evaluation_datasets/tau_bench/.venv/bin/python -m pytest -q tests/sagents/v2/test_tau_repository_runtime.py tests/sagents/v2/test_tau_standard_dataset.py tests/sagents/v2/test_tau_mcp_isolation.py tests/sagents/v2/test_tau_standard_scorer.py
```

## 2. Configure Desktop and MCP

On macOS, install Flutter/Xcode build prerequisites, then start Desktop:

```sh
cd app/v2/desktop
flutter pub get
flutter run -d macos
```

Desktop's backend keeps its own environment. Configure your model endpoint,
credentials, protocol, and model ID in Settings, then verify a normal chat.
Keep credentials out of Git.

MCP and `scorer.py` use this directory's `.venv`. Keep `scorer.runtime.json`
beside `scorer.py` when importing. Restart Desktop after updating Sage, and reimport
the scorer after changing its environment. See
[Python environments](../README.md#python-environments).
The imported `user_simulator.py` uses the same environment through
`user_simulator.runtime.json`. Keep that file beside the source and reimport the
simulator after changing dependencies.

Add this stdio MCP connection, replacing **every** placeholder with an absolute
path on this machine. A `~` argument is not expanded by a shell:

```json
{
  "mcpServers": {
    "TauRetail": {
      "command": "/absolute/path/Sage/evaluation_datasets/tau_bench/.venv/bin/python",
      "args": ["-m", "evaluation_datasets.tau_bench.mcp_server", "--state", "/absolute/path/sage/runtime/tau-retail.sqlite3"],
      "env": {
        "PYTHONPATH": "/absolute/path/Sage",
        "SAGE_RSI_CASE_PROTOCOL": "sage.rsi.case/v1"
      }
    }
  }
}
```

In the MCP dialog, choose stdio and name it **`TauRetail`**. Command contains only
the interpreter path; Args receives the JSON array and Env receives the JSON object.
Empty Args/Env mean `[]`/`{}`. Do not paste a shell command or the full `mcpServers`
object into Args. Connect starts the subprocess. Saved connections can be edited
and rediscovered without changing their name or enabled state.

Verify 16 `mcp_TauRetail_*` tools, including official `calculate`. No scoring MCP,
reference-query tool, admin reset, or network-search tool is required.
SQLite preserves ordinary connection state. RSI instead binds isolated case and
candidate directories through `sage.rsi.case/v1`; the target cannot read scoring references.

## 3. Configure the baseline Agent

Create a retail Agent. Select your target model and, if configured, the fast model.
Use the full [retail policy](data/tau2/domains/retail/policy.md) with a short role
instruction, and enable all 16 business tools before opening RSI.

Optional Sage file, Shell, planning, and `load_skill` tools are extra baseline
capabilities, not official retail tools. Enable them explicitly only when required
by your experiment, and keep tool/permission settings fixed across comparisons.
Start with no skills. RSI must not silently add baseline capabilities.

## 4. Import and run

1. Import `rsi.dataset.json` in the Agent's RSI page.
2. Import `scorer.py`, wait for self-tests, and select it.
3. Set the goal, initial training count, increment, rounds, concurrency, and repeats.
4. Start RSI and inspect the frozen settings, baseline, and later rounds.

The initial target message is `Hello.`. Full scenario instructions stay in
`user_context` and are disclosed by the user simulator. `dialogue_completion=user`
requires user termination; matching database state early does not end the task.
Do not expose dialogue plans from `reason_for_call` to the target.

Start small, then scale while keeping evaluation settings fixed:

| Setting | Smoke run | Example larger run |
| --- | ---: | ---: |
| Initial training cases | 3 | 24 |
| New training cases per round | 1 | 4 |
| Rounds | 1 | 8 |
| Concurrency | 3 | 10 |
| Train/dev repeats | 1 | 2 |
| System characters | 20,000 | 20,000 |
| Characters per skill | 15,000 | 15,000 |
| Skill count | 2 | 2 |

The fixed import has 62 train, 12 dev, and 40 test tasks. Initial/increment settings
control training-pool use, not a relabeling of splits. Previous training cases stay
in later rounds; regression pauses expansion. After pool exhaustion, generation
may add training cases. Keep increments at 0 when only the official pool is allowed.
For smaller smoke evaluation sets, save a separate dataset retaining each split.
Report the measured subset, not a full-test score.

Test cases, conversations, scores, and diagnostics are human-only evidence, not
inputs to tuning or version selection. A 0.95 target needs the predefined mean over
all 40 test tasks; successful setup does not establish that result.

## Scoring and model access

`scorer.py` replays native `final_items` with pinned official `evaluate_simulation`.
It checks actual dialogue, calls, arguments, and results, not a supplied `tau_reward`.
Official `reward_basis` controls database, action, communication, and natural-language
checks. Database checks compare replayed state against standard actions.
Natural-language assertions use official judging prompts and parsing.

The scorer uses `get_model_provider()` from
`sagents.v2.optimization.scorer_runtime`. It reuses Sage's selected ModelProvider,
protocol adapters, and concurrency budget without receiving provider keys or extra
judging prompts. Only model transport is adapted; official reward logic is retained.

A prior integration used GPT-6.1 Sol instead of the pinned official default
`gpt-4.1-2025-04-14`. Disclose the chosen judge and any other protocol differences.
If a Responses gateway explicitly rejects the official temperature parameter, the
adapter removes it for one retry and records `details.model_calls[].transport_adjustments`.
Other errors remain failures.

Four import self-tests cover database and natural-language pass/fail cases using
offline ModelProvider responses. They do not bill a live model. Runtime model access
and complete UI experiments still need their own verification. Evaluation diagnoses
training executions but cannot alter the scorer's grade; dev feedback is anonymous
scores and test evidence stays human-only.

Parallel batches are reconstructed as one assistant batch and matching tool results
by `tool_call_id`, even when delivery order differs. Missing/duplicate IDs or results
fail. TauRetail also commits increasing effect receipts in its database transaction;
MCP `_meta` carries them as native `metadata.mcp_meta`. The scorer replays actual
batch execution order, including failed calls. Legacy records without receipts use
issued order and cannot prove historical commit order. Mixed or malformed receipts fail.

Reimport and select a new scorer after updates, then start a new experiment.
Existing experiments retain frozen source/dependency bindings and grades; do not
rewrite their scorer in place. Unchanged datasets need no reimport.

## User simulators and termination

Simulators are selected separately. The default is Sage's generic simulator; optional
`user_simulator_instructions` apply to train/dev/test and use only visible dialogue
and user context. Keep simulator settings fixed in comparisons.

To use the pinned official retail prompts and role handling, import
[user_simulator.py](user_simulator.py) through **Import user simulator** and select it.
Keep [scorer.py](scorer.py) selected separately. Dataset names do not switch simulators.

The adapter reuses official `UserSimulator.system_prompt`, `str(UserScenario)`,
`UserState.flip_roles()`, and `UserSimulator.is_stop()`. It generates one natural
language message at temperature 0, without tools or RSI JSON instructions, then
maps the output to the standard protocol:

| Official output | Stop reason | Scorer termination |
| --- | --- | --- |
| Ordinary message | Continue | — |
| `###STOP###` | `completed` | `user_finished` |
| `###TRANSFER###` | `transferred` | `user_transferred` |
| `###OUT-OF-SCOPE###` | `out_of_scope` | `user_out_of_scope` |
| `max_turns` reached | Host limit | `turn_limit` |

User stop does not imply a pass. The official evaluator receives `USER_STOP` for
user termination and `MAX_STEPS` for exhausted turns. Legacy requests without an
end reason retain their old interpretation and record
`termination_reason_source=legacy_assumed_user_stop`; they do not prove normal completion.

Four simulator self-tests use recorded responses for continuation and the three
stop markers. The adapter supports retail text tasks with no user tools, not
telecom user tools or voice. It preserves Sage's splits, execution, models, and
budgets, so results remain Sage RSI adapter results rather than the official leaderboard.
See [User simulators](../../sagents/v2/optimization/USER_SIMULATORS.md).

## Move to another machine

For a new experiment, clone the code, install dependencies, configure models/MCP/the
Agent, and import the dataset/scorer. No previous runtime directory is needed.

To preserve history, stop all Desktop clients and background experiments first,
then privately back up the entire `~/sage`. It contains credentials, catalogs,
SQLite databases, sessions, experiments, and skills. Do not commit it, copy only
`rsi.sqlite3`, or copy SQLite while it is being written.

Reinstall virtual environments and update all interpreter, state, workspace, and
PYTHONPATH paths. Do not migrate build caches or old sidecar registration/lock files.
Cross-machine resume must pass frozen configuration, engine, resource, and checkpoint
checks; old absolute paths may prevent it. Preserve old results and start a new run
if verification fails rather than rewriting JSON or bypassing digests.

Transient failures retry locally without replaying completed execution/scoring.
Exhausted retries retain a checkpoint. For completed optimization lacking human
tests, use **Continue tests** instead of restarting tuning. macOS source Desktop is
the documented setup here; verify other OS builds, process startup, and model access
on the destination machine.
