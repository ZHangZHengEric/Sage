from sagents.v2.optimization.audit import generated_tool_audit


def test_incomplete_trace_cannot_establish_clean_tool_execution():
    assert not generated_tool_audit({})["passed"]
    assert not generated_tool_audit(
        {"runtime_events": [], "runtime_events_truncated": True}
    )["passed"]
    assert generated_tool_audit(
        {"runtime_events": [], "runtime_events_truncated": False}
    )["passed"]


def test_generated_failures_are_deduplicated_and_native_failures_are_separate():
    call = {"tool_name": "rsi_rule", "tool_call_id": "one"}
    evidence = {
        "runtime_events_truncated": False,
        "runtime_events": [
            {
                "data": {
                    **call,
                    "kind": "tool",
                    "state": "failed",
                    "error": {"message": "Bad expression"},
                }
            },
            {
                "data": {
                    "item": {
                        "data": {
                            **call,
                            "kind": "tool_result",
                            "error": {"message": "Bad expression"},
                        }
                    }
                }
            },
            {
                "data": {
                    "tool_name": "file_read",
                    "kind": "tool",
                    "state": "failed",
                    "error": {"message": "Missing file"},
                }
            },
        ],
    }
    result = generated_tool_audit(evidence)
    assert result["complete"] and not result["passed"]
    assert result["failure_count"] == 1
    assert result["failures"][0]["tool_name"] == "rsi_rule"
