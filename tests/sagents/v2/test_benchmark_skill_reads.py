from copy import deepcopy

import pytest

from evaluation_datasets import _interactive


class World:
    task = staticmethod(lambda context: context)
    tools = staticmethod(_interactive.tools)
    validate = staticmethod(_interactive.validate)
    replay = staticmethod(lambda context, actions: ([{}, {"done": True}], 1))


def request():
    value = _interactive.fixture_request("World", "t", ["go"], [{}, {"done": True}])
    evidence = value["observation"]["evidence"]
    evidence["run_id"] = "run"
    evidence["session_id"] = "session"
    call = {
        "kind": "tool_call",
        "tool_call_id": "skill",
        "tool_name": "load_skill",
        "arguments": {"skill_name": "procedure", "session_id": "session"},
    }
    result = {
        "kind": "tool_result",
        "tool_call_id": "skill",
        "error": None,
        "content": [{"kind": "text", "text": "Skill procedure loaded."}],
        "metadata": {
            "skill_name": "procedure",
            "content_hash": "a" * 64,
            "active_skills": ["procedure"],
        },
    }
    evidence["final_items"].extend(
        [
            {
                "item_id": "skill-call",
                "run_id": "run",
                "step_id": "step",
                "status": "completed",
                "data": call,
            },
            {
                "item_id": "skill-result",
                "run_id": "run",
                "step_id": "step",
                "status": "completed",
                "data": result,
            },
        ]
    )
    evidence["runtime_events"] = [
        {
            "run_id": "run",
            "step_id": "step",
            "type": "tool.call.proposed",
            "data": {
                "tool_call_id": "skill",
                "tool_name": "load_skill",
                "arguments": call["arguments"],
                "operation_id": "op",
            },
        },
        {
            "run_id": "run",
            "step_id": "step",
            "type": "tool.call.succeeded",
            "data": {
                "tool_call_id": "skill",
                "result_item_id": "skill-result",
                "state": "completed",
                "error": None,
                "operation_id": "op",
            },
        },
    ]
    return value


def score(value):
    return _interactive.evaluate(
        World, "World", {"format_version": "world.reference/v1", "task_id": "t"}, value
    )


def test_native_enabled_skill_read_does_not_change_official_reward_or_action_budget():
    value = request()
    original = deepcopy(value)
    result = score(value)
    assert result["grade"]["score"] == 1
    assert result["details"]["actions"] == 1
    assert value == original


@pytest.mark.parametrize(
    "defect",
    [
        "declined",
        "foreign_tool",
        "missing_receipt",
        "wrong_operation",
        "wrong_result",
        "wrong_skill",
        "truncated",
    ],
)
def test_auxiliary_read_never_accepts_denied_or_unbound_tools(defect):
    value = request()
    evidence = value["observation"]["evidence"]
    call, result = evidence["final_items"][-2:]
    if defect == "declined":
        result["data"]["error"] = {"code": "tool.policy_denied"}
    elif defect == "foreign_tool":
        call["data"]["tool_name"] = "file_read"
    elif defect == "missing_receipt":
        evidence["runtime_events"].pop()
    elif defect == "wrong_operation":
        evidence["runtime_events"][-1]["data"]["operation_id"] = "other"
    elif defect == "wrong_result":
        evidence["runtime_events"][-1]["data"]["result_item_id"] = "other"
    elif defect == "wrong_skill":
        result["data"]["metadata"]["skill_name"] = "other"
    else:
        evidence["runtime_events_truncated"] = True
    with pytest.raises(ValueError, match="Only this benchmark MCP"):
        score(value)
