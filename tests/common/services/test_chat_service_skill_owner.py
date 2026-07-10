import asyncio
from pathlib import Path
from types import SimpleNamespace

from common.core import config
from common.core.context import set_request_context
from common.schemas.chat import Message, StreamRequest
from common.services import chat_service


def _server_cfg(tmp_path: Path) -> config.StartupConfig:
    root = tmp_path / "sage"
    cfg = config.StartupConfig(
        app_mode="server",
        logs_dir=str(root / "logs"),
        session_dir=str(root / "sessions"),
        agents_dir=str(root / "agents"),
        skill_dir=str(root / "skills"),
        user_dir=str(root / "users"),
    )
    Path(cfg.agents_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.skill_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.user_dir).mkdir(parents=True, exist_ok=True)
    return cfg


def _write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} description\n---\n",
        encoding="utf-8",
    )


def test_sage_stream_service_uses_caller_workspace_and_agent_owner_skills(
    tmp_path, monkeypatch
):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)

    recorded = {}

    monkeypatch.setattr(chat_service, "create_tool_proxy", lambda tools: object())

    def fake_create_skill_proxy(available_skills, user_id=None, agent_workspace=None):
        recorded["available_skills"] = available_skills
        recorded["user_id"] = user_id
        recorded["agent_workspace"] = agent_workspace
        return object(), None

    monkeypatch.setattr(chat_service, "create_skill_proxy", fake_create_skill_proxy)
    monkeypatch.setattr(chat_service, "create_model_client", lambda cfg: object())
    monkeypatch.setattr(chat_service, "SAgent", lambda **kwargs: object())

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        user_id="caller_user",
        agent_owner_user_id="owner_user",
        agent_id="agent_1",
        available_tools=[],
        available_skills=["schedule-management"],
        llm_model_config={"model": "test-model"},
        max_loop_count=1,
    )

    service = chat_service.SageStreamService(request)

    expected_workspace = Path(cfg.agents_dir) / "caller_user" / "agent_1"
    assert Path(service.agent_workspace) == expected_workspace
    assert recorded == {
        "available_skills": ["schedule-management"],
        "user_id": "owner_user",
        "agent_workspace": str(expected_workspace),
    }


def test_create_conversation_title_fallback_uses_request_locale():
    set_request_context("test", None, locale="en-US")
    try:
        request = StreamRequest(messages=[])

        title = asyncio.run(chat_service.create_conversation_title(request))
    finally:
        set_request_context("test-reset", None, locale=None)

    assert title == "New conversation"


def test_populate_request_records_agent_owner_user_id(tmp_path, monkeypatch):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)

    agent = SimpleNamespace(
        name="Ling",
        user_id="owner_user",
        config={
            "availableSkills": ["schedule-management"],
            "availableTools": [],
            "maxLoopCount": 3,
        },
    )
    provider = SimpleNamespace(
        base_url="http://model.local",
        api_key="key",
        model="model",
        max_tokens=None,
        temperature=0.3,
        top_p=0.9,
        presence_penalty=0.0,
        max_model_len=64000,
        supports_multimodal=True,
        supports_structured_output=False,
    )

    class FakeAgentConfigDao:
        async def get_by_id(self, agent_id):
            return agent

    class FakeLLMProviderDao:
        async def get_default(self):
            return provider

    async def fake_register_extra_mcp_tools(request):
        return None

    async def fake_populate_custom_sub_agents(request):
        return None

    monkeypatch.setattr(chat_service, "AgentConfigDao", FakeAgentConfigDao)
    monkeypatch.setattr(chat_service, "LLMProviderDao", FakeLLMProviderDao)
    monkeypatch.setattr(
        chat_service, "_register_extra_mcp_tools", fake_register_extra_mcp_tools
    )
    monkeypatch.setattr(
        chat_service, "_populate_custom_sub_agents", fake_populate_custom_sub_agents
    )

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        user_id="caller_user",
        agent_id="agent_1",
    )

    asyncio.run(chat_service.populate_request_from_agent_config(request))

    assert request.agent_owner_user_id == "owner_user"
    assert request.user_id == "caller_user"


def test_populate_request_merges_only_current_user_workspace_skills(
    tmp_path, monkeypatch
):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)
    caller_skills = Path(cfg.agents_dir) / "caller_user" / "agent_1" / "skills"
    owner_skills = Path(cfg.agents_dir) / "owner_user" / "agent_1" / "skills"
    _write_skill(caller_skills, "caller-local-skill")
    _write_skill(owner_skills, "owner-local-skill")

    agent = SimpleNamespace(
        name="Shared Agent",
        user_id="owner_user",
        config={
            "availableSkills": [],
            "availableTools": [],
            "maxLoopCount": 3,
        },
    )
    provider = SimpleNamespace(
        base_url="http://model.local",
        api_key="key",
        model="model",
        max_tokens=None,
        temperature=0.3,
        top_p=0.9,
        presence_penalty=0.0,
        max_model_len=64000,
        supports_multimodal=True,
        supports_structured_output=False,
    )

    class FakeAgentConfigDao:
        async def get_by_id(self, agent_id):
            return agent

    class FakeLLMProviderDao:
        async def get_default(self):
            return provider

    async def fake_register_extra_mcp_tools(request):
        return None

    async def fake_populate_custom_sub_agents(request):
        return None

    monkeypatch.setattr(chat_service, "AgentConfigDao", FakeAgentConfigDao)
    monkeypatch.setattr(chat_service, "LLMProviderDao", FakeLLMProviderDao)
    monkeypatch.setattr(
        chat_service, "_register_extra_mcp_tools", fake_register_extra_mcp_tools
    )
    monkeypatch.setattr(
        chat_service, "_populate_custom_sub_agents", fake_populate_custom_sub_agents
    )

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        user_id="caller_user",
        agent_id="agent_1",
    )

    asyncio.run(chat_service.populate_request_from_agent_config(request))

    assert request.available_skills == ["caller-local-skill"]
    assert request.available_tools is not None
    assert "load_skill" in request.available_tools
    assert agent.config["availableSkills"] == []


def test_populate_request_preserves_team_manual_empty_sub_agents(tmp_path, monkeypatch):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)
    agent = SimpleNamespace(
        agent_id="leader",
        user_id="owner_user",
        name="Team Leader",
        config={
            "name": "Team Leader",
            "agentMode": "team",
            "maxLoopCount": 100,
            "subAgentSelectionMode": "manual",
            "availableSubAgentIds": [],
        },
    )
    provider = SimpleNamespace(
        base_url="http://model.local",
        api_key="key",
        model="model",
        max_tokens=None,
        temperature=0.3,
        top_p=0.9,
        presence_penalty=0.0,
        max_model_len=64000,
        supports_multimodal=True,
        supports_structured_output=False,
    )

    class FakeAgentConfigDao:
        async def get_by_id(self, agent_id):
            return agent

        async def get_all(self):
            raise AssertionError("manual empty selection must not auto-populate")

    class FakeLLMProviderDao:
        async def get_default(self):
            return provider

    async def fake_register_extra_mcp_tools(request):
        return None

    async def fake_populate_custom_sub_agents(request):
        return None

    monkeypatch.setattr(chat_service, "AgentConfigDao", FakeAgentConfigDao)
    monkeypatch.setattr(chat_service, "LLMProviderDao", FakeLLMProviderDao)
    monkeypatch.setattr(
        chat_service, "_register_extra_mcp_tools", fake_register_extra_mcp_tools
    )
    monkeypatch.setattr(
        chat_service, "_populate_custom_sub_agents", fake_populate_custom_sub_agents
    )

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        user_id="caller_user",
        agent_id="leader",
    )

    asyncio.run(chat_service.populate_request_from_agent_config(request))

    assert request.agent_mode == "team"
    assert request.available_sub_agent_ids == []


def test_populate_request_auto_all_populates_team_sub_agents(tmp_path, monkeypatch):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)
    agent = SimpleNamespace(
        agent_id="leader",
        user_id="owner_user",
        name="Team Leader",
        config={
            "name": "Team Leader",
            "agentMode": "team",
            "maxLoopCount": 100,
            "subAgentSelectionMode": "auto_all",
        },
    )
    provider = SimpleNamespace(
        base_url="http://model.local",
        api_key="key",
        model="model",
        max_tokens=None,
        temperature=0.3,
        top_p=0.9,
        presence_penalty=0.0,
        max_model_len=64000,
        supports_multimodal=True,
        supports_structured_output=False,
    )

    class FakeAgentConfigDao:
        async def get_by_id(self, agent_id):
            return agent

        async def get_all(self):
            return [
                SimpleNamespace(agent_id="leader"),
                SimpleNamespace(agent_id="member_1"),
            ]

    class FakeLLMProviderDao:
        async def get_default(self):
            return provider

    async def fake_register_extra_mcp_tools(request):
        return None

    async def fake_populate_custom_sub_agents(request):
        return None

    monkeypatch.setattr(chat_service, "AgentConfigDao", FakeAgentConfigDao)
    monkeypatch.setattr(chat_service, "LLMProviderDao", FakeLLMProviderDao)
    monkeypatch.setattr(
        chat_service, "_register_extra_mcp_tools", fake_register_extra_mcp_tools
    )
    monkeypatch.setattr(
        chat_service, "_populate_custom_sub_agents", fake_populate_custom_sub_agents
    )

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        user_id="caller_user",
        agent_id="leader",
    )

    asyncio.run(chat_service.populate_request_from_agent_config(request))

    assert request.available_sub_agent_ids == ["member_1"]


def test_populate_custom_sub_agents_does_not_inject_member_skill_workspace(
    tmp_path, monkeypatch
):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)

    member = SimpleNamespace(
        agent_id="member_1",
        name="Member",
        user_id="member_owner",
        config={
            "description": "Uses its own skill",
            "availableSkills": ["video-script"],
            "availableTools": ["file_read"],
            "availableWorkflows": {},
            "systemContext": {"agent_mode": "simple"},
            "agentMode": "simple",
        },
    )

    class FakeAgentConfigDao:
        async def get_by_ids(self, agent_ids):
            assert agent_ids == ["member_1"]
            return [member]

    monkeypatch.setattr(chat_service, "AgentConfigDao", FakeAgentConfigDao)

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        user_id="leader_user",
        agent_id="leader",
        available_sub_agent_ids=["member_1"],
    )

    asyncio.run(chat_service._populate_custom_sub_agents(request))

    assert request.custom_sub_agents
    member_config = request.custom_sub_agents[0]
    assert member_config.available_skills == ["video-script"]
    assert member_config.agent_mode == "simple"
    assert "team_member_skill_workspace" not in member_config.system_context


def test_populate_request_prefers_agent_response_language_over_request(
    tmp_path, monkeypatch
):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)

    agent = SimpleNamespace(
        name="Ling",
        user_id="owner_user",
        config={
            "availableTools": [],
            "maxLoopCount": 3,
            "systemContext": {
                "response_language": "zh-CN",
                "business_key": "agent_value",
            },
        },
    )
    provider = SimpleNamespace(
        base_url="http://model.local",
        api_key="key",
        model="model",
        max_tokens=None,
        temperature=0.3,
        top_p=0.9,
        presence_penalty=0.0,
        max_model_len=64000,
        supports_multimodal=True,
        supports_structured_output=False,
    )

    class FakeAgentConfigDao:
        async def get_by_id(self, agent_id):
            return agent

    class FakeLLMProviderDao:
        async def get_default(self):
            return provider

    async def fake_register_extra_mcp_tools(request):
        return None

    monkeypatch.setattr(chat_service, "AgentConfigDao", FakeAgentConfigDao)
    monkeypatch.setattr(chat_service, "LLMProviderDao", FakeLLMProviderDao)
    monkeypatch.setattr(
        chat_service, "_register_extra_mcp_tools", fake_register_extra_mcp_tools
    )

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        user_id="caller_user",
        agent_id="agent_1",
        system_context={
            "response_language": "en-US",
            "business_key": "request_value",
        },
    )

    asyncio.run(chat_service.populate_request_from_agent_config(request))

    assert request.system_context["response_language"] == "zh-CN"  # pyright: ignore[reportOptionalSubscript]
    assert request.system_context["business_key"] == "request_value"  # pyright: ignore[reportOptionalSubscript]


def test_populate_request_uses_agent_response_language_when_request_omits_it(
    tmp_path, monkeypatch
):
    cfg = _server_cfg(tmp_path)
    monkeypatch.setattr(config, "_GLOBAL_STARTUP_CONFIG", cfg, raising=False)

    agent = SimpleNamespace(
        name="Ling",
        user_id="owner_user",
        config={
            "availableTools": [],
            "maxLoopCount": 3,
            "systemContext": {
                "response_language": "zh-CN",
                "business_key": "agent_value",
            },
        },
    )
    provider = SimpleNamespace(
        base_url="http://model.local",
        api_key="key",
        model="model",
        max_tokens=None,
        temperature=0.3,
        top_p=0.9,
        presence_penalty=0.0,
        max_model_len=64000,
        supports_multimodal=True,
        supports_structured_output=False,
    )

    class FakeAgentConfigDao:
        async def get_by_id(self, agent_id):
            return agent

    class FakeLLMProviderDao:
        async def get_default(self):
            return provider

    async def fake_register_extra_mcp_tools(request):
        return None

    monkeypatch.setattr(chat_service, "AgentConfigDao", FakeAgentConfigDao)
    monkeypatch.setattr(chat_service, "LLMProviderDao", FakeLLMProviderDao)
    monkeypatch.setattr(
        chat_service, "_register_extra_mcp_tools", fake_register_extra_mcp_tools
    )

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        user_id="caller_user",
        agent_id="agent_1",
        system_context={
            "business_key": "request_value",
        },
    )

    asyncio.run(chat_service.populate_request_from_agent_config(request))

    assert request.system_context["response_language"] == "zh-CN"  # pyright: ignore[reportOptionalSubscript]
    assert request.system_context["business_key"] == "request_value"  # pyright: ignore[reportOptionalSubscript]
