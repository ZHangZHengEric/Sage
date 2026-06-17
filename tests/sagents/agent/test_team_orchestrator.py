import asyncio
from types import SimpleNamespace

from sagents.agent.fibre.agent_definition import AgentDefinition
from sagents.agent.team.orchestrator import TeamOrchestrator
from sagents.agent.team.tools import TeamTools
from sagents.context.messages.message import MessageChunk, MessageRole
from sagents.context.session_context import SessionContext
from sagents.skill.skill_schema import SkillSchema
from sagents.tool import ToolManager


def test_team_orchestrator_rejects_spawn_agent():
    orchestrator = TeamOrchestrator.__new__(TeamOrchestrator)
    result = asyncio.run(
        orchestrator.spawn_agent(
            parent_session_id="parent_session",
            name="New Agent",
            description="Should not be created",
            system_prompt="You should not exist.",
        )
    )

    assert "does not allow creating new agents" in result


def test_team_orchestrator_loads_existing_members_without_backend_creation():
    orchestrator = TeamOrchestrator.__new__(TeamOrchestrator)
    orchestrator.backend_client = None
    orchestrator.sub_agents = {}

    session_context = SimpleNamespace(
        custom_sub_agents=[
            {
                "agent_id": "writer",
                "name": "Writer",
                "description": "Writes scripts",
                "system_prompt": "You write scripts.",
            }
        ],
        agent_config={"agent_id": "leader"},
        system_context={},
        user_id="user_1",
    )

    asyncio.run(orchestrator._load_team_members(session_context))

    assert list(orchestrator.sub_agents) == ["writer"]
    assert session_context.system_context["available_sub_agents"] == [
        {
            "agent_id": "writer",
            "name": "Writer",
            "description": "Writes scripts",
        }
    ]


def test_team_orchestrator_manual_empty_members_does_not_fallback_to_backend():
    class BackendShouldNotBeCalled:
        async def check_health(self):
            raise AssertionError(
                "empty team member selection must not list backend agents"
            )

    orchestrator = TeamOrchestrator.__new__(TeamOrchestrator)
    orchestrator.backend_client = BackendShouldNotBeCalled()
    orchestrator.sub_agents = {}

    session_context = SimpleNamespace(
        custom_sub_agents=[],
        agent_config={"agent_id": "leader"},
        system_context={},
        user_id="user_1",
    )

    asyncio.run(orchestrator._load_team_members(session_context))

    assert orchestrator.sub_agents == {}
    assert session_context.system_context["available_sub_agents"] == []


def test_team_tools_use_distinct_names_without_spawn():
    manager = ToolManager(is_auto_discover=False, isolated=True)
    manager.register_tools_from_object(TeamTools())

    tool_names = set(manager.list_all_tools_name())

    assert "sys_team_delegate_task" in tool_names
    assert "sys_delegate_task" not in tool_names
    assert "sys_spawn_agent" not in tool_names


class _FakeTeamSession:
    def __init__(self, session_id, session_context=None):
        self.session_id = session_id
        self.session_context = session_context
        self.child_session_ids = set()
        self.interrupt_reason = None

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
        self.child_session_ids.add(session_id)

    def set_status(self, status):
        self.status = status

    def should_interrupt(self):
        return False

    def get_status(self):
        return getattr(self, "status", None)

    async def run_stream_with_flow(self, **kwargs):
        self.run_stream_kwargs = kwargs
        yield [
            MessageChunk(
                role=MessageRole.ASSISTANT.value,
                content="done",
                session_id=self.session_id,
            )
        ]


class _FakeTeamSessionManager:
    session_root_space = "/tmp/sage-test-sessions"

    def __init__(self, parent_session):
        self.parent_session = parent_session
        self.created = {}

    def get_live_session(self, session_id):
        if session_id == "parent":
            return self.parent_session
        return self.created.get(session_id)

    def get_or_create(self, session_id, session_space):
        session = _FakeTeamSession(session_id)
        self.created[session_id] = session
        return session


def _build_parent_team_session():
    tool_manager = ToolManager(is_auto_discover=False, isolated=True)
    tool_manager.register_tools_from_object(TeamTools())
    context = SessionContext(
        session_id="parent",
        user_id="user_1",
        agent_id="leader",
        session_root_space="/tmp/sage-test-sessions",
        sandbox_agent_workspace="/tmp/team-workspace",
        system_context={},
        tool_manager=tool_manager,
    )
    context.set_agent_config(
        model="model",
        model_config={},
        system_prefix="",
        available_tools=["sys_team_delegate_task"],
        available_skills=[],
        system_context={},
        available_workflows={},
        deep_thinking=False,
        agent_mode="team",
        more_suggest=False,
        max_loop_count=3,
        agent_id="leader",
    )
    return _FakeTeamSession("parent", context)


class _FakeSkillManager:
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


def test_team_member_without_mode_defaults_to_simple_not_leader_team():
    parent_session = _build_parent_team_session()
    orchestrator = TeamOrchestrator.__new__(TeamOrchestrator)
    orchestrator.agent = SimpleNamespace(model="model", model_config={})
    orchestrator.session_manager = _FakeTeamSessionManager(parent_session)
    orchestrator.sub_agents = {
        "writer": AgentDefinition(
            agent_id="writer",
            name="Writer",
            system_prompt="Write.",
            description="Writer",
            system_context={},
        )
    }

    sub_session = asyncio.run(
        orchestrator._get_or_create_sub_session(
            session_id="child", agent_id="writer", parent_session_id="parent"
        )
    )

    assert sub_session.session_context.agent_config["agent_mode"] == "simple"
    assert sub_session.session_context.sandbox_agent_workspace == (
        parent_session.session_context.sandbox_agent_workspace
    )


def test_team_member_uses_its_own_explicit_mode():
    parent_session = _build_parent_team_session()
    orchestrator = TeamOrchestrator.__new__(TeamOrchestrator)
    orchestrator.agent = SimpleNamespace(model="model", model_config={})
    orchestrator.session_manager = _FakeTeamSessionManager(parent_session)
    orchestrator.sub_agents = {
        "builder": AgentDefinition(
            agent_id="builder",
            name="Builder",
            system_prompt="Build.",
            description="Builder",
            system_context={"agent_mode": "fibre"},
        )
    }

    sub_session = asyncio.run(
        orchestrator._get_or_create_sub_session(
            session_id="child", agent_id="builder", parent_session_id="parent"
        )
    )

    assert sub_session.session_context.agent_config["agent_mode"] == "fibre"


def test_team_member_skills_resolve_from_leader_skill_manager_only():
    parent_session = _build_parent_team_session()
    parent_session.session_context.skill_manager = _FakeSkillManager(["video-script"])
    orchestrator = TeamOrchestrator.__new__(TeamOrchestrator)
    orchestrator.agent = SimpleNamespace(model="model", model_config={})
    orchestrator.session_manager = _FakeTeamSessionManager(parent_session)
    orchestrator.sub_agents = {
        "writer": AgentDefinition(
            agent_id="writer",
            name="Writer",
            system_prompt="Write.",
            description="Writer",
            available_skills=["video-script", "missing-skill"],
            system_context={},
        )
    }

    sub_session = asyncio.run(
        orchestrator._get_or_create_sub_session(
            session_id="child", agent_id="writer", parent_session_id="parent"
        )
    )

    assert sub_session.session_context.skill_manager.list_skills() == ["video-script"]
    assert sub_session.session_context.agent_config["available_skills"] == [
        "video-script"
    ]


def test_team_delegate_prompt_does_not_force_task_workspace(monkeypatch):
    parent_session = _build_parent_team_session()
    orchestrator = TeamOrchestrator.__new__(TeamOrchestrator)
    orchestrator.agent = SimpleNamespace(model="model", model_config={})
    orchestrator.session_manager = _FakeTeamSessionManager(parent_session)
    orchestrator.sub_session_manager = orchestrator.session_manager
    orchestrator.sub_agents = {
        "writer": AgentDefinition(
            agent_id="writer",
            name="Writer",
            system_prompt="Write.",
            description="Writer",
            system_context={},
        )
    }

    async def fake_summarize_subtask_history(**kwargs):
        return "summary"

    monkeypatch.setattr(
        "sagents.agent.team.orchestrator.summarize_subtask_history",
        fake_summarize_subtask_history,
    )
    orchestrator.output_queue = asyncio.Queue()

    result = asyncio.run(
        orchestrator._delegate_task_internal(
            agent_id="writer",
            content="Create projects/video_project/script.md",
            session_id="child",
            caller_session_id="parent",
            task_name="script",
            original_task="Create a script",
        )
    )

    sub_session = orchestrator.session_manager.created["child"]
    streamed_chunks = orchestrator.output_queue.get_nowait()
    prompt = sub_session.run_stream_kwargs["input_messages"][0].content
    assert result == "summary"
    assert streamed_chunks[0].session_id == "child"
    assert streamed_chunks[0].content == "done"
    assert "【Team 共享工作空间】" in prompt
    assert "【子任务工作目录】" not in prompt
    assert "/results/" not in prompt
    assert "/execution/" not in prompt
