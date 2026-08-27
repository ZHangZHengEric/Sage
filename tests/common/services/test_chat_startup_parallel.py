import asyncio
import time
from types import SimpleNamespace

import pytest

from common.core import config
from common.schemas.chat import Message, StreamRequest
from common.services import chat_service


def _server_cfg():
    return config.StartupConfig(app_mode="server")


def _provider(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        base_url=f"http://{name}.local",
        api_key=f"{name}-key",
        model=f"{name}-model",
        max_tokens=None,
        temperature=0.2,
        top_p=0.8,
        presence_penalty=0.0,
        max_model_len=64000,
        supports_multimodal=True,
        supports_structured_output=True,
    )


@pytest.mark.asyncio
async def test_populate_looks_up_main_and_fast_providers_in_parallel(monkeypatch):
    monkeypatch.setattr(
        config, "_GLOBAL_STARTUP_CONFIG", _server_cfg(), raising=False
    )
    starts = {}
    overlap = asyncio.Event()

    class FakeAgentConfigDao:
        async def get_by_id(self, agent_id):
            return SimpleNamespace(
                name="Agent",
                user_id="owner",
                config={
                    "availableTools": [],
                    "availableSkills": [],
                    "maxLoopCount": 3,
                    "llm_provider_id": "provider_main",
                    "fast_llm_provider_id": "provider_fast",
                },
            )

    class FakeLLMProviderDao:
        async def get_by_id(self, provider_id):
            starts[provider_id] = time.perf_counter()
            if len(starts) == 2:
                overlap.set()
            await asyncio.sleep(0.05)
            return _provider(provider_id)

        async def get_default(self):
            raise AssertionError("default provider should not be used")

    async def noop(_request):
        return None

    monkeypatch.setattr(chat_service, "AgentConfigDao", FakeAgentConfigDao)
    monkeypatch.setattr(chat_service, "LLMProviderDao", FakeLLMProviderDao)
    monkeypatch.setattr(chat_service, "_register_extra_mcp_tools", noop)
    monkeypatch.setattr(chat_service, "_populate_custom_sub_agents", noop)
    monkeypatch.setattr(chat_service, "_merge_agent_workspace_skills", noop)

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        user_id="user_1",
        agent_id="agent_1",
        session_id="sess-parallel",
    )

    await chat_service.populate_request_from_agent_config(request)

    assert overlap.is_set()
    assert abs(starts["provider_main"] - starts["provider_fast"]) < 0.05
    assert request.llm_model_config["base_url"] == "http://provider_main.local"
    assert request.llm_model_config["fast_base_url"] == "http://provider_fast.local"


@pytest.mark.asyncio
async def test_populate_runs_workspace_skills_and_sub_agents_in_parallel(
    monkeypatch,
):
    monkeypatch.setattr(
        config, "_GLOBAL_STARTUP_CONFIG", _server_cfg(), raising=False
    )
    starts = {}
    overlap = asyncio.Event()

    class FakeAgentConfigDao:
        async def get_by_id(self, agent_id):
            return SimpleNamespace(
                name="Agent",
                user_id="owner",
                config={
                    "availableTools": [],
                    "availableSkills": [],
                    "maxLoopCount": 3,
                    "availableSubAgentIds": ["sub-1"],
                },
            )

    class FakeLLMProviderDao:
        async def get_default(self):
            return _provider("default")

    async def slow_merge(request):
        starts["skills"] = time.perf_counter()
        if "sub_agents" in starts:
            overlap.set()
        await asyncio.sleep(0.05)
        request.available_skills = ["workspace-skill"]

    async def slow_sub_agents(request):
        starts["sub_agents"] = time.perf_counter()
        if "skills" in starts:
            overlap.set()
        await asyncio.sleep(0.05)
        request.custom_sub_agents = ["sub-1"]

    async def noop(_request):
        return None

    monkeypatch.setattr(chat_service, "AgentConfigDao", FakeAgentConfigDao)
    monkeypatch.setattr(chat_service, "LLMProviderDao", FakeLLMProviderDao)
    monkeypatch.setattr(chat_service, "_merge_agent_workspace_skills", slow_merge)
    monkeypatch.setattr(chat_service, "_populate_custom_sub_agents", slow_sub_agents)
    monkeypatch.setattr(chat_service, "_register_extra_mcp_tools", noop)

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        user_id="user_1",
        agent_id="agent_1",
        session_id="sess-post",
    )

    await chat_service.populate_request_from_agent_config(request)

    assert overlap.is_set()
    assert abs(starts["skills"] - starts["sub_agents"]) < 0.05
    assert request.available_skills == ["workspace-skill"]
    assert request.custom_sub_agents == ["sub-1"]
