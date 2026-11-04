"""Small Desktop polling views; durable execution evidence remains untouched."""
from __future__ import annotations

import json


def execution_transcript(items):
    """Bounded visible projection; never ship reasoning or provider state."""
    result = []

    def preview(value):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return text if len(text) <= 6000 else text[:6000] + '\n…'

    for row in items if isinstance(items, list) else []:
        if not isinstance(row, dict) or row.get('visibility') in {'audit', 'diagnostic'}:
            continue
        data = row.get('data', {})
        kind = data.get('kind')
        entry = {'id': f"{row.get('run_id', '')}:{row.get('item_id', '')}", 'kind': kind}
        if kind == 'message' and data.get('role') in {'user', 'assistant'}:
            entry.update(role=data['role'], text=preview(''.join(
                block.get('text', '') for block in data.get('content', []) if block.get('kind') == 'text')))
        elif kind in {'tool_call', 'tool_result'}:
            entry.update(role='tool', call_id=f"{row.get('run_id', '')}:{data.get('tool_call_id', '')}")
            if kind == 'tool_call':
                entry.update(tool_name=data.get('tool_name'), text=preview(data.get('arguments') or data.get('arguments_json') or {}))
            else:
                from sagents.v2.optimization.execution_records import message_content
                entry.update(text=preview(message_content(data.get('content'))),
                             state='failed' if data.get('error') else 'completed')
                if data.get('error'):
                    error = data['error']
                    entry['error'] = preview(error.get('message', error) if isinstance(error, dict) else error)
        else:
            continue
        result.append(entry)
    return result


def compact_rsi_payload(value):
    if isinstance(value, list):
        return [compact_rsi_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    if (value.get("state") in ("completed", "failed", "cancelled", "suspended")
            and isinstance(value.get("output"), str) and isinstance(value.get("evidence"), dict)):
        heavy = {"runtime_events", "final_items", "training_trace"}
        evidence = {key: item for key, item in value["evidence"].items() if key not in heavy}
        transcript = execution_transcript(value['evidence'].get('final_items'))
        if transcript:
            evidence['execution_transcript'] = transcript
        if heavy.intersection(value["evidence"]):
            evidence["execution_details_omitted"] = True
        return {**value, "evidence": evidence}
    if value.get("event") == "agent_call_started" and isinstance(value.get("data"), dict):
        return {key: compact_rsi_payload({k: v for k, v in item.items() if k != "request"}
                                        if key == "data" else item)
                for key, item in value.items()}
    is_agent_call = isinstance(value.get("role"), str) and isinstance(value.get("observation"), dict)
    # These are user/package data, not report envelopes. Never rewrite their
    # contents even when a literal happens to resemble an execution record.
    literal_keys = {"manifest", "files", "tool_definitions", "skill_definitions", "input_schema",
                    "expression", "case", "user_context", "reference_answer"}
    return {key: item if key in literal_keys else compact_rsi_payload(item) for key, item in value.items()
            if not (is_agent_call and key == "request")}


def summarize_grade(grade):
    if not isinstance(grade, dict):
        return grade
    result = {k: grade[k] for k in ("score", "passed") if k in grade}
    details = grade.get("scorer_details")
    if isinstance(details, dict):
        result["scorer_details"] = {
            k: {field: details[k][field] for field in fields if field in details[k]}
            for k, fields in (
                ("pairwise", ("outcome", "reference", "pending")),
                ("pairwise_summary", ("wins", "ties", "losses", "pairs")),
            )
            if isinstance(details.get(k), dict)
        }
        if details.get("pairwise_pending"):
            result["scorer_details"]["pairwise_pending"] = True
    return result


def summarize_human_tests(checkpoints):
    return [
        {**{k: v for k, v in checkpoint.items() if k != "cases"}, "cases": [
            {**{k: v for k, v in case.items() if k != "trials"},
             "human_part": [checkpoint_index, case_index],
             "trials": [{**{k: trial[k] for k in ("trial", "status") if k in trial},
                         "grade": summarize_grade(trial.get("grade"))}
                        for trial in case.get("trials", [])]}
            for case_index, case in enumerate(checkpoint.get("cases", []))
        ]}
        for checkpoint_index, checkpoint in enumerate(checkpoints)
    ]


def summarize_live_event(value):
    """Keep live scoring and short previews without returning raw transcripts."""
    if isinstance(value, list):
        return [summarize_live_event(item) for item in value]
    if not isinstance(value, dict):
        return value
    if isinstance(value.get("output"), str) and isinstance(value.get("evidence"), dict):
        return {k: (item[:6000] if k == "output" else item) for k, item in value.items() if k != "evidence"}
    if value.get("event") == "agent_call_started" and isinstance(value.get("data"), dict):
        return {**value, "data": summarize_live_event({k: v for k, v in value["data"].items() if k != "request"})}
    return {
        k: item if k in {"case", "files", "manifest"}
        else summarize_grade(item) if k in {"grade", "model_grade"}
        else {"splits": item.get("splits", {})} if k == "comparison" and isinstance(item, dict)
        else summarize_live_event(item)
        for k, item in value.items() if k not in {"agent_calls"}
    }


def summarize_version_record(record):
    evaluation = record.get("evaluation") or {}
    comparison = record.get("comparison") or {}
    return {
        "evaluation": {"cases": [
            {"case": {"id": entry["case"]["id"], "split": entry["case"]["split"]},
             "grade": summarize_grade(entry["grade"])}
            for entry in evaluation.get("cases", [])
        ]},
        "comparison": {"splits": comparison.get("splits", {})},
    }
