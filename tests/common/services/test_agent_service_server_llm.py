import pytest

from common.core import config
from common.core.exceptions import SageHTTPException
from common.models.agent import Agent
from common.services import agent_service


class _EmptyProviderDao:
    async def get_list(self, user_id=None):
        return []

    async def get_by_id(self, provider_id):
        return None


@pytest.mark.asyncio
async def test_server_prompt_optimization_model_resolution_does_not_use_global_client(
    monkeypatch,
):
    monkeypatch.setattr(
        agent_service,
        "_get_cfg",
        lambda: config.StartupConfig(app_mode="server"),
    )
    monkeypatch.setattr(agent_service, "LLMProviderDao", _EmptyProviderDao)
    monkeypatch.setattr(
        agent_service,
        "get_chat_client",
        lambda: pytest.fail("server must not use the global chat client"),
    )

    with pytest.raises(SageHTTPException) as raised:
        await agent_service._resolve_model_client("user-1")

    assert raised.value.message_key == "agent.provider_missing"


@pytest.mark.asyncio
async def test_server_agent_abilities_require_agent_provider(monkeypatch):
    agent = Agent(
        agent_id="agent-1",
        name="Agent",
        config={},
        user_id="user-1",
    )

    async def get_agent(agent_id, user_id):
        return agent

    monkeypatch.setattr(agent_service, "get_agent", get_agent)
    monkeypatch.setattr(agent_service, "LLMProviderDao", _EmptyProviderDao)
    monkeypatch.setattr(
        agent_service.config,
        "get_startup_config",
        lambda: config.StartupConfig(
            app_mode="server",
            default_llm_api_key="server-global-key",
        ),
    )

    with pytest.raises(SageHTTPException) as raised:
        await agent_service.generate_agent_abilities("agent-1", user_id="user-1")

    assert raised.value.message_key == "agent.provider_missing"
