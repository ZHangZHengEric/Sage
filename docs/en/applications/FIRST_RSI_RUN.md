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

**The model responses and scores are scripted.** The real SAgents v2 runtime executes the workflow, but this example does not demonstrate learned unit conversion or measure real-model improvement. No model API key is needed for this scripted example.

## 1. Prepare the Python environment

You need Git, Python **3.12 or newer**, and the repository's Python dependencies. Follow only the Install section of [Getting Started](GETTING_STARTED.md), then return here. You do not need its API-key setup or `quickstart.py` example.

Installation downloads dependencies and can take time. This is not a zero-install demo. Flutter, a Desktop installer, MySQL, and a model-service account are not required for this Python example.

Already have a configured checkout? Open a terminal in the repository root and use that checkout's Python environment.

## 2. Run the existing example

From the repository root, on macOS/Linux:

```bash
.venv/bin/python -m examples.sagents_v2_package_optimizer
```

On Windows, after creating the environment described in Getting Started:

```powershell
.venv\Scripts\python.exe -m examples.sagents_v2_package_optimizer
```

The [example source](https://github.com/ZHangZHengEric/Sage/blob/main/examples/sagents_v2_package_optimizer.py) supplies a `ScriptedModelProvider` for the target, tuner, and evaluator. Its agents have no enabled tools. It writes temporary Session data and removes the temporary directory when the program exits normally; it prints a JSON summary rather than saving a permanent report or activating an Agent.

## 3. Read the comparison

The script defines these responses and grades in advance. This table explains those source-defined guidance changes; the command prints a selection summary, not a package diff:

| Stage | Scripted guidance | Scripted score | Selection to look for |
| --- | --- | --- | --- |
| Baseline | No added guidance | 0.4 | Starting point |
| Round 1 | Verify units | 0.6 | Accepted |
| Round 2 | Be brief | 0.5 | Rejected |
| Round 3 | Verify units and arithmetic | 0.8 | Accepted |

The useful part is round 2: a new proposal does not automatically replace the retained best candidate. Its scripted score is below round 1's, so the comparison should reject it and retain the better version.

Here is an excerpt from a completed scripted run:

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
- `final_passed`: expected to be `true` under the scripted final check. This is not evidence of performance on real unseen tasks.

The unit-conversion questions provide the workflow's fixtures; the scripted target returns a guidance label, not a calculated conversion answer. Suite-audit and semantic-review approvals are scripted too.

**You have completed the walkthrough when you can find the rejected round and identify the selected candidate.** Nothing has been applied to your normal Agent configuration.

### What was verified

The excerpt was captured on 2026-10-12 from [commit `296cc3d`](https://github.com/ZHangZHengEric/Sage/blob/296cc3dec8f7ea11fa58a079df9b18709305fa89/examples/sagents_v2_package_optimizer.py), using Python 3.12.14 on Linux. The unmodified example exited successfully in a prepared Python environment with no API credentials. A Python-level test guard reported no attempted network or subprocess operations. This check covers the example, not a fresh full installation, Windows/macOS execution, or real-model quality.

## If it does not run

- A Python-version error: confirm the virtual environment was created with Python 3.12 or newer.
- `No module named examples...`: run from the repository root, where `examples/` is present.
- An import or missing-dependency error: use the same virtual environment for installation and execution; revisit the Install section of [Getting Started](GETTING_STARTED.md).

Keep the exact error and checkout revision when asking for help. Do not add an API key to troubleshoot this scripted example.

## Next: use your own Agent and evaluation

For a real model, follow the [RSI workflow guide](RSI.md) and [optimizer API reference](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/optimization/README.md). Those explain host bindings, authorized editable scope, test suites, candidate evidence, and failure handling. Real-model runs may incur provider charges; this demonstration's scripted grades are not a benchmark for them.
