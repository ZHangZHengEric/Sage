from types import SimpleNamespace

import pytest

from sagents.context.session_context import SessionContext
from sagents.session_runtime import Session
import sagents.session_runtime as session_runtime


@pytest.mark.asyncio
async def test_child_session_inherits_parent_runtime_environment(monkeypatch, tmp_path):
    registrar = object()
    parent_context = SimpleNamespace(
        runtime_env_vars={"TOKEN": "parent"},
        runtime_resource_registrar=registrar,
    )
    parent_session = SimpleNamespace(session_context=parent_context)
    manager = SimpleNamespace(
        get_live_session=lambda session_id: (
            parent_session if session_id == "parent" else None
        )
    )

    async def init_more(self, session_root_space=None):
        return None

    monkeypatch.setattr(session_runtime, "get_global_session_manager", lambda: manager)
    monkeypatch.setattr(SessionContext, "init_more", init_more)

    child = Session("parent:child", enable_obs=False)
    child.configure_runtime(
        session_root_space=str(tmp_path),
        sandbox_agent_workspace=str(tmp_path),
        agent_id="agent",
    )
    context = await child._ensure_session_context(
        session_id="parent:child",
        user_id="user",
        system_context=None,
        context_budget_config=None,
        tool_manager=None,
        skill_manager=None,
        parent_session_id="parent",
    )

    assert context.runtime_env_vars == {"TOKEN": "parent"}
    assert context.runtime_resource_registrar is registrar


@pytest.mark.asyncio
async def test_runtime_env_refresh_disposes_previous_untracked_sandbox(tmp_path):
    calls = []

    class Sandbox:
        async def kill(self):
            calls.append("kill")

    sandbox = Sandbox()
    session = Session("session", enable_obs=False)
    session.session_context = SimpleNamespace(sandbox=sandbox)

    session.configure_runtime(
        session_root_space=str(tmp_path),
        sandbox_agent_workspace=str(tmp_path),
        runtime_env_vars={"TOKEN": "new"},
        runtime_env_refresh=True,
    )
    await session._dispose_stale_runtime_sandbox()

    assert calls == ["kill"]
    assert session.session_context.sandbox is None


@pytest.mark.asyncio
async def test_failed_runtime_resource_registration_kills_new_sandbox():
    calls = []

    class Sandbox:
        async def kill(self):
            calls.append("kill")

    async def reject_registration(resource, session_id):
        assert session_id == "session"
        assert resource is sandbox
        raise RuntimeError("revoking")

    sandbox = Sandbox()
    context = SessionContext.__new__(SessionContext)
    context.session_id = "session"
    context.sandbox = sandbox
    context.runtime_resource_registrar = reject_registration

    with pytest.raises(RuntimeError, match="revoking"):
        await context._register_runtime_resource(sandbox)

    assert calls == ["kill"]
    assert context.sandbox is None
