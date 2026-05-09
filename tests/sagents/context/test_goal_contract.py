from app.cli.services.runtime import build_run_request


def test_build_run_request_injects_goal_tags_into_system_context():
    request = build_run_request(
        task="Ship the runtime goal contract",
        goal={
            "objective": "Ship the runtime goal contract",
            "status": "active",
            "clear": False,
        },
    )

    assert request.goal is None
    assert request.system_context["goal_mode"] == "true"
    assert request.system_context["active_goal"] == "Ship the runtime goal contract"
    assert request.system_context["goal_status"] == "active"


def test_build_run_request_omits_goal_tags_when_clearing_goal():
    request = build_run_request(
        task="Reset the current objective",
        goal={"clear": True},
    )

    assert request.goal is None
    assert request.system_context["response_language"] == "zh-CN"
    assert "goal_mode" not in request.system_context
    assert "active_goal" not in request.system_context
    assert "goal_status" not in request.system_context


def test_build_run_request_omits_goal_tags_without_objective():
    request = build_run_request(
        task="Mark the goal complete",
        goal={
            "objective": None,
            "status": "completed",
            "clear": False,
        },
    )

    assert request.goal is None
    assert request.system_context["response_language"] == "zh-CN"
    assert "goal_mode" not in request.system_context
    assert "active_goal" not in request.system_context
    assert "goal_status" not in request.system_context
