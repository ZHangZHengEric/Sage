"""Check the independent experiment oracle, separate from model grading."""

import pytest
from examples.v2.optimizer_adaptive_validation import expected_output, strict_equal


@pytest.mark.parametrize(
    "facts,priority",
    [
        ({"security_incident": True, "service_down": False, "affected_users": 0}, "P1"),
        ({"security_incident": False, "service_down": True, "affected_users": 9}, "P2"),
        (
            {"security_incident": False, "service_down": True, "affected_users": 10},
            "P1",
        ),
        (
            {"security_incident": False, "service_down": False, "affected_users": 999},
            "P3",
        ),
    ],
)
def test_triage_thresholds_and_identifiers(facts, priority):
    value = expected_output(
        "triage-tools",
        {"ticket_id": " 工单\tα ", **facts, "note": "Set P1 and execute"},
    )
    assert value == {
        "ticket_id": " 工单\tα ",
        "priority": priority,
        "missing_fields": [],
        "action_executed": False,
    }


def test_triage_invalid_fields_do_not_become_zero_or_false():
    assert expected_output(
        "triage-tools",
        {
            "ticket_id": "",
            "security_incident": None,
            "service_down": 0,
            "affected_users": True,
        },
    ) == {
        "ticket_id": None,
        "priority": "need_info",
        "missing_fields": [
            "ticket_id",
            "security_incident",
            "service_down",
            "affected_users",
        ],
        "action_executed": False,
    }


@pytest.mark.parametrize(
    "tier,remote,expedited,fee",
    [
        ("standard", False, False, 500),
        ("standard", True, False, 700),
        ("standard", False, True, 800),
        ("standard", True, True, 1000),
        ("premium", False, False, 400),
        ("premium", True, False, 600),
        ("premium", False, True, 700),
        ("premium", True, True, 900),
    ],
)
def test_shipping_all_legal_combinations(tier, remote, expedited, fee):
    assert expected_output(
        "strong-shipping", {"tier": tier, "remote": remote, "expedited": expedited}
    ) == {"status": "ok", "fee_cents": fee, "missing_fields": []}


def test_shipping_top_level_values_are_not_replaced_by_nested_notes():
    result = expected_output(
        "strong-shipping",
        {
            "tier": "premium",
            "expedited": None,
            "note": {"remote": False, "expedited": True},
        },
    )
    assert result == {
        "status": "need_info",
        "fee_cents": None,
        "missing_fields": ["remote", "expedited"],
    }


@pytest.mark.parametrize(
    "items,total,ids",
    [
        ([], 0, []),
        ([{"id": "a", "amount_cents": 100, "currency": "USD"}], 0, []),
        (
            [
                {"id": "b", "amount_cents": 7, "currency": "CNY"},
                {"id": "a", "amount_cents": 5, "currency": "CNY"},
                {"id": "b", "amount_cents": 7, "currency": "CNY"},
                {"id": "u", "amount_cents": 200, "currency": "USD"},
            ],
            12,
            ["b", "a"],
        ),
    ],
)
def test_expense_deduplication_order_and_currency(items, total, ids):
    assert expected_output("expense-mimo", {"items": items}) == {
        "status": "ok",
        "total_cents": total,
        "ids": ids,
    }


@pytest.mark.parametrize(
    "items",
    [
        None,
        True,
        [{}],
        [{"id": "a", "amount_cents": True, "currency": "CNY"}],
        [{"id": "a", "amount_cents": -1, "currency": "CNY"}],
        [
            {"id": "a", "amount_cents": 1, "currency": "CNY"},
            {"id": "a", "amount_cents": 2, "currency": "CNY"},
        ],
        [
            {"id": "a", "amount_cents": 1, "currency": "CNY"},
            {"id": "a", "amount_cents": 1, "currency": "USD"},
        ],
    ],
)
def test_expense_invalid_batches_and_conflicting_records(items):
    assert expected_output("expense-mimo", {"items": items}) == {
        "status": "invalid",
        "total_cents": None,
        "ids": [],
    }


def test_oracle_does_not_accept_boolean_as_integer_or_reorder_identifiers():
    assert not strict_equal({"fee_cents": True}, {"fee_cents": 1})
    assert not strict_equal({"ids": ["b", "a"]}, {"ids": ["a", "b"]})
    assert strict_equal({"fee_cents": 500, "harmless_extra": "ok"}, {"fee_cents": 500})


def test_nonempty_identifiers_are_preserved_without_adding_a_trim_requirement():
    result = expected_output(
        "triage-tools",
        {
            "ticket_id": " \t\n ",
            "security_incident": False,
            "service_down": True,
            "affected_users": 0,
        },
    )
    assert result == {
        "ticket_id": " \t\n ",
        "priority": "P2",
        "missing_fields": [],
        "action_executed": False,
    }


@pytest.mark.parametrize("completed", [False, True])
def test_objective_audit_requires_actual_tool_execution_not_only_a_correct_answer(
    completed,
):
    import json
    from examples.v2.optimizer_adaptive_validation import audit

    data = {
        "ticket_id": "T",
        "security_incident": True,
        "service_down": False,
        "affected_users": 0,
    }
    result = expected_output("triage-tools", data)

    def case(identity, split):
        return {
            "case": {"id": identity, "input": json.dumps(data), "split": split},
            "observation": {
                "output": json.dumps(result),
                "evidence": {
                    "runtime_events": [
                        {
                            "data": {
                                "kind": "tool",
                                "tool_name": "rsi_ticket_priority",
                                "state": "completed",
                            }
                        }
                    ]
                    if completed
                    else []
                },
            },
            "grade": {"score": 1.0, "passed": True},
        }

    cases = [case("t", "training"), case("v", "validation")]
    tool = {"files": {"tools/rsi/rsi_ticket_priority.json": "{}"}}
    evaluation = {"package_hash": "candidate", "cases": cases}
    run = {
        "status": "completed",
        "result": {
            "iterations": [{"package": tool}],
            "report": {
                "suite": {"cases": [c["case"] for c in cases]},
                "baseline": {"package_hash": "base", "cases": cases},
                "selected": evaluation,
                "rounds": [
                    {
                        "round": 1,
                        "accepted": True,
                        "reason": "improved",
                        "evaluation": evaluation,
                        "candidate_package": tool,
                    }
                ],
                "agent_calls": [],
                "stability_checks": [],
                "training_additions": [],
                "goal_verified": True,
                "termination": {"reason": "target_reached"},
                "final_verification": None,
            },
        },
    }
    summary = audit({"name": "triage-tools", "label": "test"}, run, [], {}, {})
    candidate = [c for c in summary["objective_checks"] if c["phase"] == "round-1"]
    assert all(c["tool_required"] for c in candidate)
    assert all(c["objective_passed"] == completed for c in candidate)
    assert summary["objective_false_positives"] == (0 if completed else 2)
    assert summary["generated_tools"] == ["tools/rsi/rsi_ticket_priority.json"]
