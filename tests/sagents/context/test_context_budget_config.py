import asyncio

from sagents.context.messages.context_budget import ContextBudgetManager
from sagents.context.session_context import SessionContext, SessionStatus
from sagents.session_runtime import Session


def test_overflow_budget_is_persisted_on_manager():
    manager = ContextBudgetManager(
        max_model_len=10,
        history_ratio=0.2,
        active_ratio=0.3,
        max_new_message_ratio=0.5,
    )

    budget = manager.calculate_budget({"large_config": "x" * 200})

    assert budget["active_budget"] == 0
    assert manager.budget_info == budget


def test_session_context_updates_reused_budget_config():
    context = SessionContext(
        session_id="s1",
        user_id="u1",
        agent_id="a1",
        session_root_space="/tmp",
        context_budget_config={"max_model_len": 40000},
    )

    context.update_context_budget_config({"max_model_len": 210000})

    manager = context.message_manager.context_budget_manager
    assert manager.max_model_len == 210000
    assert manager.budget_info is None
    assert context.context_budget_config["max_model_len"] == 210000


def test_session_persisted_state_restores_context_budget_config(tmp_path):
    context = SessionContext(
        session_id="s1",
        user_id="u1",
        agent_id="a1",
        session_root_space=str(tmp_path),
        context_budget_config={"max_model_len": 210000},
    )
    context.session_workspace = str(tmp_path)
    context.save(session_status=SessionStatus.COMPLETED)

    session = Session(session_id="s1", enable_obs=False)
    assert session.load_persisted_state(str(tmp_path)) is True

    manager = session.session_context.message_manager.context_budget_manager
    assert manager.max_model_len == 210000


def test_reused_session_context_uses_model_config_max_model_len():
    session = Session(session_id="s1", enable_obs=False)
    session.model_config = {"max_model_len": 40000}
    context = SessionContext(
        session_id="s1",
        user_id="u1",
        agent_id="a1",
        session_root_space="/tmp",
        context_budget_config={"max_model_len": 40000},
    )
    context.sandbox = object()
    session.session_context = context

    session.model_config = {"max_model_len": 64000}
    asyncio.run(session._ensure_session_context(
        session_id="s1",
        user_id="u1",
        system_context=None,
        context_budget_config=None,
        tool_manager=None,
        skill_manager=None,
    ))

    manager = session.session_context.message_manager.context_budget_manager
    assert manager.max_model_len == 64000


def test_reused_session_context_normalizes_camel_case_budget_config():
    session = Session(session_id="s1", enable_obs=False)
    session.model_config = {}
    context = SessionContext(
        session_id="s1",
        user_id="u1",
        agent_id="a1",
        session_root_space="/tmp",
        context_budget_config={"max_model_len": 40000},
    )
    context.sandbox = object()
    session.session_context = context

    asyncio.run(session._ensure_session_context(
        session_id="s1",
        user_id="u1",
        system_context=None,
        context_budget_config={"maxModelLen": 128000},
        tool_manager=None,
        skill_manager=None,
    ))

    manager = session.session_context.message_manager.context_budget_manager
    assert manager.max_model_len == 128000
