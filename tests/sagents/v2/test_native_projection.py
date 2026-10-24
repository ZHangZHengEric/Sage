from copy import deepcopy
import json

import pytest

from sagents.v2.optimization.contracts import OptimizationObservation
from sagents.v2.optimization.native_projection import (
    PROTOCOL,
    project_mcp_execution_order,
)


def observation():
    items, events = [], []
    for i, name in enumerate(("first", "second")):
        base = {"run_id": "run", "step_id": "step"}
        items.append(
            {
                **base,
                "item_id": "call-item-" + name,
                "data": {
                    "kind": "tool_call",
                    "tool_call_id": name,
                    "tool_name": "mcp_World_step",
                    "arguments": {"action": name},
                },
            }
        )
        items.append(
            {
                **base,
                "item_id": "result-" + name,
                "data": {
                    "kind": "tool_result",
                    "tool_call_id": name,
                    "content": [{"kind": "text", "text": name}],
                    "error": None,
                    "metadata": {
                        "mcp_server": "World",
                        "mcp_tool": "step",
                        "mcp_result_received": True,
                    },
                },
            }
        )
        events.extend(
            [
                {
                    **base,
                    "type": "tool.call.proposed",
                    "data": {
                        "tool_call_id": name,
                        "tool_name": "mcp_World_step",
                        "arguments": {"action": name},
                        "operation_id": "op-" + name,
                    },
                },
                {
                    **base,
                    "event_id": "receipt-" + name,
                    "type": "tool.call.succeeded",
                    "run_sequence": 20 - i,
                    "data": {
                        "tool_call_id": name,
                        "operation_id": "op-" + name,
                        "state": "completed",
                        "result_item_id": "result-" + name,
                        "error": None,
                    },
                },
            ]
        )
    return OptimizationObservation(
        state="completed",
        output="Unchanged",
        evidence={"run_id": "run", "final_items": items, "runtime_events": events},
    )


def test_projection_uses_durable_receipt_order_without_changing_any_item():
    original = observation()
    before = original.model_dump(mode="json")
    projected = project_mcp_execution_order(original)
    calls = [
        i["data"]["tool_call_id"]
        for i in projected.evidence["final_items"]
        if i["data"]["kind"] == "tool_call"
    ]
    assert calls == ["second", "first"]
    assert original.model_dump(mode="json") == before
    assert sorted(map(json.dumps, original.evidence["final_items"])) == sorted(
        map(json.dumps, projected.evidence["final_items"])
    )
    assert projected.state == original.state and projected.output == original.output
    proof = projected.evidence["execution_projection"]
    assert proof["protocol"] == PROTOCOL
    assert proof["steps"][0]["proposal_order"] == ["first", "second"]
    assert proof["steps"][0]["receipt_order"] == ["second", "first"]
    assert project_mcp_execution_order(projected) == projected


def test_server_effect_order_takes_priority_over_later_receipt_delivery():
    original = observation()
    for number, index in enumerate((1, 3), 1):
        original.evidence["final_items"][index]["data"]["metadata"]["mcp_meta"] = {
            "sage_rsi_effect_order": {
                "protocol": "sage.rsi.mcp-effect-order/v1",
                "case_instance": "same-case",
                "sequence": number,
            }
        }
    assert project_mcp_execution_order(original) == original
    for index in (1, 3):
        order = original.evidence["final_items"][index]["data"]["metadata"]["mcp_meta"][
            "sage_rsi_effect_order"
        ]
        order["sequence"] = 3 - order["sequence"]
    original.evidence["runtime_events"][1]["run_sequence"] = 10
    original.evidence["runtime_events"][3]["run_sequence"] = 20
    projected = project_mcp_execution_order(original)
    assert (
        projected.evidence["execution_projection"]["steps"][0]["ordering_basis"]
        == "server_effect_sequence"
    )
    assert projected.evidence["final_items"][0]["data"]["tool_call_id"] == "second"


@pytest.mark.parametrize("defect", ["mixed", "duplicate", "scope", "bool"])
def test_conflicting_server_order_never_falls_back_to_guessing_from_receipts(defect):
    value = observation()
    for number, index in enumerate((1, 3), 1):
        value.evidence["final_items"][index]["data"]["metadata"]["mcp_meta"] = {
            "sage_rsi_effect_order": {
                "protocol": "sage.rsi.mcp-effect-order/v1",
                "case_instance": "same-case",
                "sequence": number,
            }
        }
    meta = value.evidence["final_items"][3]["data"]["metadata"]["mcp_meta"]
    if defect == "mixed":
        meta.clear()
    elif defect == "duplicate":
        meta["sage_rsi_effect_order"]["sequence"] = 1
    elif defect == "scope":
        meta["sage_rsi_effect_order"]["case_instance"] = "other-case"
    else:
        meta["sage_rsi_effect_order"]["sequence"] = True
    assert project_mcp_execution_order(value) == value


@pytest.mark.parametrize(
    "change",
    [
        "truncated",
        "missing",
        "wrong_run",
        "wrong_step",
        "wrong_operation",
        "wrong_result",
        "wrong_arguments",
        "wrong_tool",
        "error",
        "not_received",
        "duplicate",
        "duplicate_sequence",
    ],
)
def test_incomplete_or_conflicting_proof_never_invents_a_reordered_execution(change):
    raw = observation().model_dump(mode="json")
    e = raw["evidence"]
    receipt = e["runtime_events"][1]
    if change == "truncated":
        e["runtime_events_truncated"] = True
    elif change == "missing":
        e["runtime_events"].pop(1)
    elif change == "wrong_run":
        receipt["run_id"] = "other"
    elif change == "wrong_step":
        receipt["step_id"] = "other"
    elif change == "wrong_operation":
        receipt["data"]["operation_id"] = "other"
    elif change == "wrong_result":
        receipt["data"]["result_item_id"] = "other"
    elif change == "wrong_arguments":
        e["runtime_events"][0]["data"]["arguments"] = {"action": "other"}
    elif change == "wrong_tool":
        e["runtime_events"][0]["data"]["tool_name"] = "other"
    elif change == "error":
        e["final_items"][1]["data"]["error"] = {"code": "denied"}
    elif change == "not_received":
        e["final_items"][1]["data"]["metadata"]["mcp_result_received"] = False
    elif change == "duplicate":
        e["runtime_events"].append(deepcopy(receipt))
    elif change == "duplicate_sequence":
        e["runtime_events"][3]["run_sequence"] = receipt["run_sequence"]
    value = OptimizationObservation.model_validate(raw)
    assert project_mcp_execution_order(value) == value
