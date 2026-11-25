---
layout: default
title: Your first RSI run
parent: Applications
nav_order: 5
lang: en
ref: v2-applications-FIRST_RSI_RUN
---

{% include lang_switcher.html %}

# Inspect your first RSI run

RSI means Recursive Self-Improvement. See how Sage compares Agent-package candidates, rejects a worse proposal, and returns a selected version without activating it. This walkthrough uses the existing Python example, not the Desktop app.

**The model responses and scores are scripted.** The real SAgents runtime executes the workflow, but this example does not demonstrate learned unit conversion or measure real-model improvement. No model API key is needed for this scripted example.

## 1. Prepare the Python environment

You need Git, Python **3.12 or newer**, and the repository's Python dependencies. Follow only the Install section of [Getting Started](GETTING_STARTED.md), then return here. You do not need its API-key setup or `quickstart.py` example.

Installation downloads dependencies and can take time. This is not a zero-install demo. Flutter, a Desktop installer, MySQL, and a model-service account are not required for this Python example.

Already have a configured checkout? Open a terminal in the repository root and use that checkout's Python environment.

## 2. Run the existing example

From the repository root, on macOS/Linux:

```bash
.venv/bin/python -m examples.v2.package_optimizer
```

On Windows, after creating the environment described in Getting Started:

```powershell
.venv\Scripts\python.exe -m examples.v2.package_optimizer
```

The [example source](https://github.com/ZHangZHengEric/Sage/blob/main/examples/v2/package_optimizer.py) supplies a `ScriptedModelProvider` for the target, tuner, and evaluator. Its agents have no enabled tools. It writes temporary Session data and removes the temporary directory when the program exits normally; it prints a JSON summary rather than saving a permanent report or activating an Agent.

## 3. Read the comparison

The script defines these responses and grades in advance. This table explains those source-defined guidance changes; the command prints a selection summary, not a package diff:

| Stage | Scripted guidance | Scripted score | Selection to look for |
| --- | --- | --- | --- |
| Baseline | No added guidance | 0.4 | Starting point |
| Round 1 | Verify units | 0.6 | Accepted |
| Round 2 | Be brief | 0.5 | Rejected |
| Round 3 | Verify units and arithmetic | 0.8 | Accepted |

The useful part is round 2: a new proposal does not automatically replace the retained best candidate. Its scripted score is below round 1's, so the comparison should reject it and retain the better version.

### Current result contract

With the corrected example, inspect `baseline_score: 0.4`, `selected_score: 0.8`, `goal_verified: false`, and round acceptance `true`, `false`, `true`. Round 2 is rejected with `Insufficient validation improvement`. An improved retained candidate is not the same as convergence: the default target is 0.95 with stable passes, which this scripted run does not meet.

The fixture now declares an experiment using the retained parent hash and measured training evidence supplied in each tuner request. Repairs reuse the same round's proposal and training evidence; production experiment validation remains enabled.

An excerpt of the current command's output, captured on 2026-11-25 from [commit `26fc3a3`](https://github.com/ZHangZHengEric/Sage/blob/26fc3a39190ec947baabcc051c335955d5ef80d5/examples/v2/package_optimizer.py) with Python 3.12.3 on Linux (`original_hash` and `candidate_hash` omitted):

```json
{
  "baseline_score": 0.4,
  "selected_score": 0.8,
  "goal_verified": false,
  "training_questions": 1,
  "rounds": [
    {
      "round": 1,
      "accepted": true,
      "reason": "Validation quality improved 0.4000 -> 0.6000; on 1 validation cases; 0 new training cases not backtested; 0 case regressions retained for follow-up"
    },
    {
      "round": 2,
      "accepted": false,
      "reason": "Insufficient validation improvement"
    },
    {
      "round": 3,
      "accepted": true,
      "reason": "Validation quality improved 0.6000 -> 0.8000; on 1 validation cases; 0 new training cases not backtested; 0 case regressions retained for follow-up"
    }
  ]
}
```

The retained candidate improves from 0.4 to 0.8, but 0.8 is below the convergence target, so `goal_verified` stays `false`. Compare your own output with this excerpt, not with the historical one below.

### Historical output (not the current schema)

The following captured output belongs to the 2026-10-12 revision, not the current command:

```json
{
  "baseline_score": 0.4,
  "selected_score": 0.8,
  "final_passed": true,
  "rounds": [
    {
      "round": 1,
      "accepted": true,
      "reason": "Non-saturated splits improved; no case regressions"
    },
    {
      "round": 2,
      "accepted": false,
      "reason": "Regression on case: km"
    },
    {
      "round": 3,
      "accepted": true,
      "reason": "Non-saturated splits improved; no case regressions"
    }
  ]
}
```

In your printed JSON, inspect:

- `baseline_score` and `selected_score`: the scripted validation values, expected to be `0.4` and `0.8`.
- `rounds`: three entries with `accepted` values expected to be `true`, `false`, and `true`; read each `reason`.
- `original_hash` and `candidate_hash`: identifiers for the original and selected package. They should differ because candidate guidance changed.
- `goal_verified`: expected to be `false`. The candidate improves, but the convergence target remains unmet. `final_passed` appears only in the historical output above. Neither result measures real-model performance.

The unit-conversion questions provide the workflow's fixtures; the scripted target returns a guidance label, not a calculated conversion answer. Suite-audit and semantic-review approvals are scripted too.

**You have completed the walkthrough when you can find the rejected round and identify the selected candidate.** Nothing has been applied to your normal Agent configuration.

### Historical verification

The excerpt was captured on 2026-10-12 from [commit `296cc3d`](https://github.com/ZHangZHengEric/Sage/blob/296cc3dec8f7ea11fa58a079df9b18709305fa89/examples/sagents_v2_package_optimizer.py), using Python 3.12.14 on Linux. The unmodified example exited successfully in a prepared Python environment with no API credentials. A Python-level test guard reported no attempted network or subprocess operations. This check covers the example, not a fresh full installation, Windows/macOS execution, or real-model quality.

### Current fixture verification

On 2026-11-19, the corrected fixture was tested in an isolated macOS snapshot based on `1d3d1dd65857a4903ceaedf3ccaea81f1c3666f9`, using Python 3.12.13 and existing dependencies. The documented module command exited 0 without API credentials under a network/subprocess guard and produced the current result contract above. This is verification of the fixture change on that base, not a claim that the unmodified base works, nor a fresh-install or Windows test. The offline regression test also exercises a forced same-round repair.

## If it does not run

- A Python-version error: confirm the virtual environment was created with Python 3.12 or newer.
- `No module named examples...`: run from the repository root, where `examples/` is present.
- An import or missing-dependency error: use the same virtual environment for installation and execution; revisit the Install section of [Getting Started](GETTING_STARTED.md).

Keep the exact error and checkout revision when asking for help. Do not add an API key to troubleshoot this scripted example.

## Next: use your own Agent and evaluation

For a real model, follow the [RSI workflow guide](RSI.md) and [optimizer API reference](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/optimization/README.md). Those explain host bindings, authorized editable scope, test suites, candidate evidence, and failure handling. Real-model runs may incur provider charges; this demonstration's scripted grades are not a benchmark for them.

## Optional: make a first Sage PR

If you want to contribute without a model API key, documentation improvements or offline tests are welcome. Browse the [open good first issues](https://github.com/ZHangZHengEric/Sage/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) and read the [contribution guide](https://github.com/ZHangZHengEric/Sage/blob/main/CONTRIBUTING.md) before making changes.

Before starting work on an issue, check its comments and linked pull requests—an unassigned issue may already have an active PR. Leave a comment or open a draft PR if you want early feedback.
