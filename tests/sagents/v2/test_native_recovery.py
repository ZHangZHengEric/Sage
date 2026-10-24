import json

import pytest

from sagents.v2.optimization.evaluation_files import evaluation_response
from sagents.v2.optimization.native_recovery import RevalidatingOptimizationRecovery
from sagents.v2.optimization.recovery import OptimizationRecoveryRequired


def journal(
    tmp_path,
    *,
    tools=("file_read", "file_write"),
    error="model.empty_semantic_response",
):
    events = [
        {
            "event": "operation_started",
            "data": {
                "internal_agents": {
                    "evaluator": {
                        "package": {"manifest": {"agents": {"eval": {"tools": tools}}}}
                    }
                }
            },
        }
    ]
    starts = []
    for number in (1, 2):
        request = json.dumps(
            {
                "data": {
                    "protocol": "sage.rsi.evaluation-files/v1",
                    "sha256": str(number),
                }
            }
        )
        start = dict(
            call_id=str(number),
            role="evaluation",
            phase="optimization",
            round=1,
            trial=1,
            case_id=None,
            request=request,
        )
        starts.append(start)
        evidence = {"evaluation_record": '{"summary":"valid repair"}'}
        if number == 1:
            evidence.update(
                error={"code": error},
                evaluation_record_error="Incomplete evidence read",
            )
        events.extend(
            [
                {"event": "agent_call_started", "data": start},
                {
                    "event": "agent_call_completed",
                    "data": {
                        "call_id": str(number),
                        "observation": {
                            "state": "suspended" if number == 1 else "completed",
                            "output": "",
                            "evidence": evidence,
                        },
                    },
                },
            ]
        )
        if number == 1:
            events.append(
                {"event": "evaluation_response_rejected", "data": {"call_id": "1"}}
            )
    path = tmp_path / "journal.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path, [{k: v for k, v in s.items() if k != "call_id"} for s in starts]


def test_recovery_revalidates_rejected_native_response_before_consuming_its_repair(
    tmp_path,
):
    path, requests = journal(tmp_path)
    original = path.read_bytes()
    recovery = RevalidatingOptimizationRecovery(path, local_file_evaluator=True)
    invalid = recovery.completed_call(**requests[0])
    assert invalid.state == "suspended"
    with pytest.raises(ValueError, match="Incomplete evidence read"):
        evaluation_response(invalid, True)
    repaired = recovery.completed_call(**requests[1])
    assert json.loads(evaluation_response(repaired, True)) == {
        "summary": "valid repair"
    }
    assert recovery.completed_call(**requests[1]) is None
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "options,tools,error",
    [
        ({}, ("file_read", "file_write"), "model.empty_semantic_response"),
        (
            {"local_file_evaluator": True},
            ("file_read", "file_write", "shell"),
            "model.empty_semantic_response",
        ),
        ({"local_file_evaluator": True}, ("file_read", "file_write"), "model.timeout"),
    ],
)
def test_local_response_replay_needs_host_grant_safe_tools_and_exact_interruption(
    tmp_path, options, tools, error
):
    path, requests = journal(tmp_path, tools=tools, error=error)
    if not options or "shell" in tools:
        with pytest.raises(OptimizationRecoveryRequired, match="tool access"):
            RevalidatingOptimizationRecovery(path, **options)
        return
    recovery = RevalidatingOptimizationRecovery(path, **options)
    with pytest.raises(ValueError, match="request differs"):
        recovery.completed_call(**requests[0])
