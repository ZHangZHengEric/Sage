import asyncio
from types import SimpleNamespace

import pytest

from common.services.agent_service import enforce_required_tools
from sagents.agent.fibre.agent_definition import AgentDefinition
from sagents.agent.fibre.orchestrator import FibreOrchestrator
from sagents.agent.fibre.tools import FibreTools
from sagents.agent.team.orchestrator import TeamOrchestrator
from sagents.agent.team.tools import TeamTools
from sagents.context.session_context import SessionContext
from sagents.skill.skill_schema import SkillSchema
from sagents.tool import ToolManager, ToolProxy
from sagents.tool.tool_base import tool


class FileLikeTools:
    @tool()
    def file_read(self, path: str) -> str:
        return path


class FakeSkillManager:
    skill_dirs = []

    def __init__(self, skills):
        self.skills = {
            name: SkillSchema(
                name=name,
                description=f"{name} skill",
                path=f"/tmp/skills/{name}",
            )
            for name in skills
        }

    def list_skills(self):
        return list(self.skills)


class FakeSession:
    def __init__(self, session_id, session_context=None):
        self.session_id = session_id
        self.session_context = session_context
        self.child_session_ids = []

    def configure_runtime(self, **kwargs):
        self.runtime_kwargs = kwargs

    async def _ensure_session_context(self, **kwargs):
        context = SessionContext(
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            agent_id=kwargs["session_id"],
            session_root_space="/tmp/sage-test-sessions",
            sandbox_agent_workspace=self.runtime_kwargs.get("sandbox_agent_workspace"),
            system_context=kwargs.get("system_context"),
            tool_manager=kwargs.get("tool_manager"),
            skill_manager=kwargs.get("skill_manager"),
            parent_session_id=kwargs.get("parent_session_id"),
        )
        self.session_context = context
        return context

    def add_child_session(self, session_id):
        self.child_session_ids.append(session_id)


class FakeSessionManager:
    session_root_space = "/tmp/sage-test-sessions"

    def __init__(self, parent_session):
        self.parent_session = parent_session
        self.created = {}

    def get_live_session(self, session_id):
        if session_id == "parent":
            return self.parent_session
        return self.created.get(session_id)

    def get_or_create(self, session_id, session_space):
        session = FakeSession(session_id)
        self.created[session_id] = session
        return session


def _parent_session(mode, workspace, skills=None):
    context = SessionContext(
        session_id="parent",
        user_id="user_1",
        agent_id="leader",
        session_root_space="/tmp/sage-test-sessions",
        sandbox_agent_workspace=workspace,
        system_context={},
        tool_manager=ToolManager(is_auto_discover=False, isolated=True),
        skill_manager=FakeSkillManager(skills or []),
    )
    context.set_agent_config(
        model="model",
        model_config={},
        system_prefix="",
        available_tools=["sys_spawn_agent", "sys_delegate_task"]
        if mode == "fibre"
        else ["sys_team_delegate_task"],
        available_skills=skills or [],
        system_context={},
        available_workflows={},
        deep_thinking=False,
        agent_mode=mode,
        more_suggest=False,
        max_loop_count=3,
        agent_id="leader",
    )
    return FakeSession("parent", context)


def _child_session(orchestrator_cls, parent_mode, child_mode=None, child_skills=None):
    parent_workspace = f"/tmp/{parent_mode}-workspace"
    parent_session = _parent_session(
        parent_mode,
        parent_workspace,
        skills=["leader-skill", "shared-skill"],
    )
    orchestrator = orchestrator_cls.__new__(orchestrator_cls)
    orchestrator.agent = SimpleNamespace(model="model", model_config={})
    orchestrator.session_manager = FakeSessionManager(parent_session)
    system_context = {}
    if child_mode is not None:
        system_context["agent_mode"] = child_mode
    orchestrator.sub_agents = {
        "member": AgentDefinition(
            agent_id="member",
            name="Member",
            system_prompt="Do work.",
            description="Member",
            available_skills=child_skills or [],
            system_context=system_context,
        )
    }

    sub_session = asyncio.run(
        orchestrator._get_or_create_sub_session(
            session_id="child", agent_id="member", parent_session_id="parent"
        )
    )
    return parent_session, sub_session


@pytest.mark.parametrize(
    (
        "orchestrator_cls",
        "parent_mode",
        "child_mode",
        "expected_mode",
        "workspace_policy",
    ),
    [
        (TeamOrchestrator, "team", None, "simple", "same_as_parent"),
        (TeamOrchestrator, "team", "simple", "simple", "same_as_parent"),
        (TeamOrchestrator, "team", "fibre", "fibre", "same_as_parent"),
        (TeamOrchestrator, "team", "team", "team", "same_as_parent"),
        (FibreOrchestrator, "fibre", None, "simple", "private_child"),
        (FibreOrchestrator, "fibre", "simple", "simple", "private_child"),
        (FibreOrchestrator, "fibre", "fibre", "fibre", "private_child"),
        (FibreOrchestrator, "fibre", "team", "team", "private_child"),
    ],
)
def test_child_mode_and_workspace_matrix(
    orchestrator_cls,
    parent_mode,
    child_mode,
    expected_mode,
    workspace_policy,
):
    parent_session, sub_session = _child_session(
        orchestrator_cls,
        parent_mode,
        child_mode=child_mode,
    )

    assert sub_session.session_context.agent_config["agent_mode"] == expected_mode
    if workspace_policy == "same_as_parent":
        assert (
            sub_session.session_context.sandbox_agent_workspace
            == parent_session.session_context.sandbox_agent_workspace
        )
    else:
        assert (
            sub_session.session_context.sandbox_agent_workspace
            != parent_session.session_context.sandbox_agent_workspace
        )
        assert sub_session.session_context.sandbox_agent_workspace.endswith(
            "/.sage/fibre_subagents/member/child"
        )


@pytest.mark.parametrize(
    ("child_skills", "expected_skills"),
    [
        ([], ["leader-skill", "shared-skill"]),
        (["shared-skill"], ["shared-skill"]),
        (["member-only-skill"], []),
        (["shared-skill", "member-only-skill"], ["shared-skill"]),
    ],
)
def test_team_member_skill_matrix_uses_leader_skill_pool(
    child_skills,
    expected_skills,
):
    _, sub_session = _child_session(
        TeamOrchestrator,
        "team",
        child_skills=child_skills,
    )

    assert sub_session.session_context.skill_manager.list_skills() == expected_skills
    assert (
        sub_session.session_context.agent_config["available_skills"] == expected_skills
    )


@pytest.mark.parametrize(
    ("mode", "expected_present", "expected_absent"),
    [
        (
            "simple",
            {"file_read"},
            {
                "sys_spawn_agent",
                "sys_delegate_task",
                "sys_team_delegate_task",
            },
        ),
        (
            "fibre",
            {"file_read", "sys_spawn_agent", "sys_delegate_task"},
            {"sys_team_delegate_task"},
        ),
        (
            "team",
            {"file_read", "sys_team_delegate_task"},
            {"sys_spawn_agent", "sys_delegate_task"},
        ),
    ],
)
def test_runtime_tool_restriction_matrix(mode, expected_present, expected_absent):
    system_manager = ToolManager(is_auto_discover=False, isolated=True)
    system_manager.register_tools_from_object(FibreTools())
    system_manager.register_tools_from_object(TeamTools())
    normal_manager = ToolManager(is_auto_discover=False, isolated=True)
    normal_manager.register_tools_from_object(FileLikeTools())
    context = SessionContext(
        session_id="session",
        user_id="user",
        agent_id="agent",
        session_root_space="/tmp/sage-test-sessions",
        tool_manager=ToolProxy([system_manager, normal_manager]),
    )

    context.restrict_tools_for_mode(mode)

    tool_names = set(context.tool_manager.list_all_tools_name())
    assert expected_present <= tool_names
    assert not (expected_absent & tool_names)


@pytest.mark.parametrize(
    ("mode", "expected_present", "expected_absent"),
    [
        (
            "simple",
            {"file_read"},
            {
                "sys_spawn_agent",
                "sys_delegate_task",
                "sys_team_delegate_task",
            },
        ),
        (
            "fibre",
            {"file_read", "sys_spawn_agent", "sys_delegate_task"},
            {"sys_team_delegate_task"},
        ),
        (
            "team",
            {"file_read", "sys_team_delegate_task"},
            {
                "sys_spawn_agent",
                "sys_delegate_task",
            },
        ),
    ],
)
def test_persisted_agent_tool_enforcement_matrix(
    mode,
    expected_present,
    expected_absent,
):
    config = enforce_required_tools(
        {
            "agentMode": mode,
            "availableTools": [
                "file_read",
                "sys_spawn_agent",
                "sys_delegate_task",
                "sys_team_delegate_task",
            ],
        }
    )

    tool_names = set(config["availableTools"])
    assert expected_present <= tool_names
    assert not (expected_absent & tool_names)
