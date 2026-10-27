"""Bounded model-facing training evidence; original report/journal stays lossless."""

from __future__ import annotations

import json


def training_feedback(result, *, include_reference_answer=False):
    data = result.model_dump(mode="json")
    if not include_reference_answer:
        data["case"].pop("reference_answer", None)

    trace_limit = 2048 if data.get("trials") else 8192
    output_limit = 1024 if data.get("trials") else 4096

    def observation(value):
        evidence = value["evidence"]
        summary = {
            key: evidence[key]
            for key in ("session_id", "run_id", "outcome", "generated_tool_audit")
            if key in evidence
        }
        # Host-provided compact execution trace retains tool arguments and the
        # end of long multi-turn episodes. It is still untrusted task evidence.
        trace = evidence.get("training_trace")
        if isinstance(trace, str):
            summary["training_trace"] = (trace if len(trace) <= trace_limit else
                                         trace[:trace_limit // 4] + "\n[... middle omitted ...]\n" + trace[-3 * trace_limit // 4:])
            summary["training_trace_truncated"] = len(trace) > trace_limit
        error = evidence.get("error")
        if isinstance(error, dict):
            summary["error"] = {
                key: error[key]
                for key in ("code", "category", "message")
                if key in error
            }
            diagnostic = (error.get("metadata") or {}).get("diagnostic_message")
            if diagnostic:
                summary["error"]["diagnostic_message"] = str(diagnostic)[:512]
        events = evidence.get("runtime_events") or []
        remaining = 2048
        tool_errors = []
        seen_errors = set()
        for event in reversed(events):
            data = event.get("data", {})
            item = (data.get("item") or {}).get("data", {})
            source = item if item.get("kind") == "tool_result" else data
            failure = source.get("error")
            if not isinstance(failure, dict):
                continue
            diagnostic = (failure.get("metadata") or {}).get("diagnostic_message")
            detail = {
                "tool_name": str(
                    data.get("tool_name") or source.get("tool_name") or ""
                )[:64],
                "code": str(failure.get("code", ""))[:64],
                "diagnostic": str(diagnostic or failure.get("message", ""))[:256],
            }
            identity = tuple(detail.values())
            if identity in seen_errors:
                continue
            seen_errors.add(identity)
            tool_errors.append(detail)
            remaining -= len(json.dumps(detail, ensure_ascii=False))
            if len(tool_errors) == 2:
                break
        summary["tool_errors"] = list(reversed(tool_errors))
        selected = []
        for event in reversed(events):
            if not remaining:
                break
            text = json.dumps(event.get("data", event), ensure_ascii=False)
            limit = min(512, remaining)
            selected.append(
                {
                    "type": event.get("type"),
                    "data_excerpt": text[:limit],
                    "truncated": len(text) > limit,
                }
            )
            remaining -= min(len(text), limit)
        summary["tool_events"] = list(reversed(selected))
        summary["evidence_summarized"] = True
        summary["recorded_event_count"] = len(events)
        value["evidence"] = summary
        if len(value["output"]) > output_limit:
            value["output"] = value["output"][:output_limit // 2] + "\n[... middle omitted ...]\n" + value["output"][-output_limit // 2:]
            value["output_truncated"] = True
        return value

    def trial(value):
        rationale = value.get("grade", {}).get("rationale", "")
        if len(rationale) > 2048:
            value["grade"]["rationale"] = excerpt(rationale, 2048)
            value["grade"]["rationale_truncated"] = True
        value["observation"] = observation(value["observation"])
        for turn in value.get("dialogue", []):
            turn["observation"] = observation(turn["observation"])
        return value

    trial(data)
    for item in data["trials"]:
        trial(item)
    return data


def excerpt(value, limit):
    if len(value) <= limit:
        return value
    marker = "\n[... omitted ...]\n"
    room = max(0, limit - len(marker))
    return value[:room // 3] + marker + (value[-(room - room // 3):] if room else "")


def training_feedback_summary(result):
    """Numeric history for file-reading tuners; full traces stay in their files."""
    return {"case": {"id": result.case.id, "split": result.case.split},
            "grade": {"score": result.grade.score, "passed": result.grade.passed},
            "objective_score": result.objective_score, "score_metrics": result.score_metrics,
            "trials": [{"grade": {"score": t.grade.score, "passed": t.grade.passed}}
                       for t in result.trials], "execution_omitted": True}


def minimal_feedback(value, *, include_context=True):
    case = {key: value["case"][key] for key in ("id", "split")}
    grade = {key: value["grade"][key] for key in ("score", "passed")}
    if include_context:
        for key in ("input", "rubric"):
            if key in value["case"]:
                case[key] = excerpt(value["case"][key], 128)
        grade["rationale"] = excerpt(value["grade"].get("rationale", ""), 256)
    return {"case": case, "grade": grade,
            "trials": [{"grade": {key: t["grade"][key] for key in ("score", "passed")}}
                       for t in value.get("trials", [])], "feedback_truncated": True}


def training_feedback_batch(results, *, max_chars=120000, include_reference_answer=False):
    """Budget the entire suite, keeping every case and every numeric trial grade.

    Failed cases receive more space. Truncation is explicit and affects only the
    model-facing copy; reports and the event journal retain original evidence.
    """
    values = [training_feedback(result, include_reference_answer=include_reference_answer) for result in results]
    if not values:
        return values
    weights = [2 if not value["grade"]["passed"] else 1 for value in values]
    total = sum(weights)
    for index, value in enumerate(values):
        budget = max_chars * weights[index] // total - 2
        if len(json.dumps(value, ensure_ascii=False)) <= budget:
            continue
        # The aggregate observation already represents the worst trial. Keep
        # every trial judgment, without repeating the same execution structures.
        for trial in value.get("trials", []):
            trial["observation"] = {
                "state": trial["observation"]["state"],
                "output": excerpt(trial["observation"]["output"], 256),
                "evidence_summarized": True,
            }
            trial["dialogue"] = [{"turn": turn["turn"], "grade": turn["grade"]}
                                for turn in trial.get("dialogue", [])]
        # Verbose event excerpts duplicate the compact host execution trace.
        def compact(item, string_limit):
            if isinstance(item, dict):
                return {key: ([] if key == "tool_events" else
                              val if key in ("id", "state", "split") else
                              compact(val, string_limit)) for key, val in item.items()}
            if isinstance(item, list):
                return [compact(val, string_limit) for val in item]
            if isinstance(item, str):
                return excerpt(item, string_limit)
            return item
        for limit in (1024, 512, 256, 128, 64):
            bounded = compact(value, limit)
            bounded["feedback_truncated"] = True
            if len(json.dumps(bounded, ensure_ascii=False)) <= budget:
                break
        else:
            # Very large trial/event structures still retain all scores, while
            # dropping duplicated execution structures in this model view.
            bounded = minimal_feedback(value)
        values[index] = bounded
    if len(json.dumps(values, ensure_ascii=False)) > max_chars:
        values = [minimal_feedback(value, include_context=False) for value in values]
        if len(json.dumps(values, ensure_ascii=False)) > max_chars:
            raise ValueError("training feedback budget cannot retain all case identities and trial grades")
    return values


def training_growth_feedback(decision):
    """Expose scheduling and training facts, never dev counts or gate reasons.

    Scheduling can depend on dev; its allowed flag is intentional indirect
    feedback, not evidence identifying which hidden measurements changed.
    Use an allowlist so new host diagnostic fields stay private by default.
    """
    return {key: decision[key] for key in (
        "enabled", "allowed", "previous_round", "training_passed",
        "training_total", "training_measured", "regressed_training",
    ) if key in decision}
