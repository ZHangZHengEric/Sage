"""Read saved τ-bench evidence without model calls or task-file access."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path


def anonymous_summary(value):
    return (
        isinstance(value, dict)
        and set(value) == {"score", "passed", "total", "items"}
        and all(set(item) == {"index", "score"} for item in value["items"])
        and [item["index"] for item in value["items"]] == list(range(1, value["total"] + 1))
    )


def inspect_tuning_request(request, validation_inputs, test_ids):
    """Check actual serialized tuner payloads, including prior training feedback."""
    data = request["data"]
    text = json.dumps(data, ensure_ascii=False)
    # Match the exact opaque routing input, rather than incidental digit strings.
    forbidden = [*validation_inputs, *(json.dumps({"tau_task_id": i}) for i in test_ids)]
    return (
        anonymous_summary(data["validation"])
        and all("round" in v and anonymous_summary({k: item for k, item in v.items() if k != "round"})
                for v in data["validation_history"])
        and not any(json.dumps(value)[1:-1] in text for value in forbidden)
    )


def paired_scores(rows, task_ids):
    pairs = {}
    for row in rows:
        if row["phase"] not in {"test-baseline", "test-candidate"} or row.get("trial", 0) != 0:
            continue
        key = (row["phase"], row["task"])
        if key in pairs:
            raise ValueError("duplicate scored test observation")
        pairs[key] = row["reward"]
    ready = [i for i in task_ids if all(("test-" + side, i) in pairs for side in ("baseline", "candidate"))]
    if not ready:
        return {"paired_tasks": 0, "complete": False}
    baseline = [pairs[("test-baseline", i)] for i in ready]
    candidate = [pairs[("test-candidate", i)] for i in ready]
    return {
        "paired_tasks": len(ready), "complete": len(ready) == len(task_ids),
        "baseline": sum(baseline) / len(ready), "candidate": sum(candidate) / len(ready),
        "delta_percentage_points": 100 * (sum(candidate) - sum(baseline)) / len(ready),
        "improved_tasks": sum(b < c for b, c in zip(baseline, candidate)),
        "regressed_tasks": sum(b > c for b, c in zip(baseline, candidate)),
        "both_passed": sum(b == c == 1 for b, c in zip(baseline, candidate)),
        "both_failed": sum(b == c == 0 for b, c in zip(baseline, candidate)),
    }


def repeated_scores(rows, task_ids, trials, *, labels=("baseline", "candidate")):
    """Official pass^k estimator: C(successes, k) / C(trials, k).

    Only complete paired tasks are summarized during progress; final completeness
    is explicit. Infrastructure failures remain in the audit, never fake zeros.
    """
    if trials not in (1, 4):
        raise ValueError("trials must be 1 or 4")
    if not task_ids or len(set(task_ids)) != len(task_ids):
        raise ValueError("task plan must contain unique tasks")
    if not labels or len(set(labels)) != len(labels):
        raise ValueError("measurement labels must be unique")
    observed = {}
    for row in rows:
        if row["phase"] not in {"test-" + label for label in labels}:
            continue
        key = (row["phase"], row["task"], row.get("trial", 0))
        if key in observed:
            raise ValueError("duplicate scored test trial")
        if row["task"] not in task_ids or not 0 <= key[2] < trials:
            raise ValueError("observation outside precommitted task/trial plan")
        if row["reward"] not in (0, 1):
            raise ValueError("pass^k requires binary official success")
        observed[key] = row["reward"]
    ready = [task for task in task_ids if all(("test-" + side, task, trial) in observed
        for side in labels for trial in range(trials))]
    result = {"trials": trials, "paired_tasks": len(ready), "expected_tasks": len(task_ids),
        "complete": bool(task_ids) and len(ready) == len(task_ids)}
    for side in labels:
        counts = [sum(observed[("test-" + side, task, trial)] == 1 for trial in range(trials)) for task in ready]
        result[side] = {f"pass^{k}": (sum(math.comb(n, k) / math.comb(trials, k) for n in counts) / len(counts)
            if counts else None) for k in (1, 4) if k <= trials}
    return result


def assess(root):
    def read(name):
        return json.loads((root / name).read_text())
    metadata = read("experiment.json")
    episodes = read("episodes.json") if (root / "episodes.json").exists() else []
    suite = read("suite.json")
    validation_inputs = [c["input"] for c in suite["cases"] if c["split"] == "validation"]
    tests = set(metadata["partition"]["test"])
    calls = [json.loads(p.read_text()) for p in (root / "internal-calls").glob("*-tuner.json")]
    result = {
        "completed_episodes": len(episodes),
        "reused_baseline_episodes": sum(bool(e.get("reused")) for e in episodes),
        "new_model_episodes": sum(not e.get("reused") for e in episodes),
        "phases": dict(Counter(e["phase"] for e in episodes)),
        "tuning_calls_checked": len(calls),
        "tuner_received_only_anonymous_validation": all(inspect_tuning_request(c["request"], validation_inputs, tests) for c in calls),
        "test_tasks_absent_from_rsi_execution": not any(e["task"] in tests for e in episodes if e["phase"] == "rsi"),
        "native_tools": len(metadata["native_tools"]), "domain_tools": len(metadata["domain_tools"]),
        "web_search_enabled": any(n in metadata["native_tools"] + metadata["domain_tools"] for n in ("web_search", "web_fetch", "search_web")),
        "failed_attempts": len(list((root / "episodes").glob("*/failure.json"))),
        "implementation_adjustments": read("implementation-adjustments.json")
            if (root / "implementation-adjustments.json").exists() else [],
        "test": paired_scores(episodes, metadata["partition"]["test"]),
        "reliability": repeated_scores(episodes, metadata["partition"]["test"], metadata.get("test_trials", 1),
            labels=("reference",) if metadata.get("reference_only") else ("baseline", "candidate")),
    }
    if (root / "frozen.json").exists():
        freeze = read("frozen.json")
        result["frozen"] = freeze
        tests_rows = [r for r in episodes if r["phase"].startswith("test-")]
        result["frozen_test_conditions_match"] = all(
            r["task"] in tests
            and r["package_hash"] == freeze["baseline" if r["phase"] in {"test-baseline", "test-reference"} else "candidate"]
            and r.get("seed", metadata["seed"]) == metadata["seed"] + r.get("trial", 0)
            for r in tests_rows
        )
        result["candidate_differs_from_baseline"] = freeze["baseline"] != freeze["candidate"]
    if (root / "rsi-result.json").exists():
        report = read("rsi-result.json")["report"]
        def means(evaluation):
            return {split: sum(c["grade"]["score"] for c in evaluation["cases"] if c["case"]["split"] == split)
                    / sum(c["case"]["split"] == split for c in evaluation["cases"])
                    for split in ("training", "validation")}
        result["rsi"] = {"baseline": means(report["baseline"]), "goal_verified": report["goal_verified"],
            "termination": report["termination"],
            "rounds": [{"round": r["round"], "accepted": r["accepted"], "reason": r["reason"],
                        "overall_before": r.get("overall_before"), "overall_after": r.get("overall_after"),
                        "regression_count": len(r.get("regressions", [])),
                        "scores": means(r["evaluation"]) if r["evaluation"] else None} for r in report["rounds"]],
            "training_counts": [{"round": a["round"], "count": len(a["cases"])} for a in report["training_additions"]]}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    assessment = assess(args.output)
    (args.output / "assessment.json").write_text(json.dumps(assessment, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(assessment, ensure_ascii=False, indent=2))
