import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from sagents.agent.fibre.orchestrator import FibreOrchestrator


class _FakeSessionManager:
    def __init__(self, session):
        self._session = session

    def get_live_session(self, session_id):
        return self._session


class _FakeBackendClient:
    def __init__(self):
        self.create_agent_kwargs = None

    async def check_health(self):
        return True

    async def create_agent(self, **kwargs):
        self.create_agent_kwargs = kwargs
        return kwargs["agent_id"]


def test_spawn_agent_defaults_empty_name_to_display_name():
    session_context = SimpleNamespace(
        agent_config={
            "agent_mode": "fibre",
            "available_tools": [],
            "available_skills": [],
            "available_workflows": {},
            "max_loop_count": 3,
        },
        custom_sub_agents=[],
        system_context={},
        user_id="user_1",
    )
    parent_session = SimpleNamespace(session_context=session_context)
    backend_client = _FakeBackendClient()

    orchestrator = FibreOrchestrator.__new__(FibreOrchestrator)
    orchestrator.agent = SimpleNamespace(
        agent_name="主Agent", model=None, model_config={}
    )
    orchestrator.backend_client = backend_client  # pyright: ignore[reportAttributeAccessIssue]
    orchestrator.sub_session_manager = _FakeSessionManager(parent_session)  # pyright: ignore[reportAttributeAccessIssue]
    orchestrator.sub_agents = {}
    orchestrator._get_fibre_system_prompt_content = lambda **kwargs: kwargs[  # pyright: ignore[reportAttributeAccessIssue]
        "custom_system_prompt"
    ]

    with patch("sagents.agent.fibre.orchestrator.random.choice", return_value="x"):
        agent_id = asyncio.run(
            orchestrator.spawn_agent(
                parent_session_id="parent_session",
                agent_id="agent_test",
                name="",
                description="Python expert",
                system_prompt="You are a Python expert.",
            )
        )

    assert agent_id == "agent_test"
    assert backend_client.create_agent_kwargs["name"] == "主Agent的子Agentx"  # pyright: ignore[reportOptionalSubscript]
    assert orchestrator.sub_agents["agent_test"].name == "主Agent的子Agentx"
    assert session_context.system_context["available_sub_agents"] == [
        {
            "agent_id": "agent_test",
            "name": "主Agent的子Agentx",
            "description": "Python expert",
        }
    ]
