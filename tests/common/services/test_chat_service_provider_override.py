import asyncio
from types import SimpleNamespace

from common.core import config
from app.server.routers import chat as chat_router
from common.schemas.chat import ChatRequest, Message, StreamRequest
from common.services import chat_service


def test_chat_request_accepts_provider_id():
    request = ChatRequest(
        messages=[Message(role="user", content="hi")],
        agent_id="agent_1",
        provider_id="provider_1",
    )

    assert request.provider_id == "provider_1"


def test_provider_override_is_trimmed_on_plain_request():
    request = ChatRequest(
        messages=[Message(role="user", content="hi")],
        agent_id="agent_1",
        provider_id=" provider_1 ",
    )
    http_request = SimpleNamespace(
        state=SimpleNamespace(user_claims={"userid": "user_1"})
    )

    chat_router.validate_and_prepare_request(request, http_request)

    assert request.provider_id == "provider_1"


def test_stream_request_provider_override_is_preserved():
    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        provider_id="provider_1",
    )
    http_request = SimpleNamespace(
        state=SimpleNamespace(
            user_claims={"userid": "user_1"},
        )
    )

    chat_router.validate_and_prepare_request(request, http_request)

    assert request.provider_id == "provider_1"


def test_chat_endpoint_preserves_provider_override(monkeypatch):
    captured = {}

    async def fake_populate_request_from_agent_config(request, require_agent_id):
        captured["request"] = request
        captured["require_agent_id"] = require_agent_id

    async def fake_prepare_session(request):
        return object(), asyncio.Lock()

    async def fake_execute_chat_session(stream_service):
        if False:
            yield ""

    async def fake_guard_request_multimodal_images(request):
        return None

    monkeypatch.setattr(
        chat_router.chat_service,
        "mark_request_execution",
        lambda request, request_source: None,
    )
    monkeypatch.setattr(
        chat_router.chat_service,
        "populate_request_from_agent_config",
        fake_populate_request_from_agent_config,
    )
    monkeypatch.setattr(
        chat_router.chat_service,
        "prepare_session",
        fake_prepare_session,
    )
    monkeypatch.setattr(
        chat_router.chat_service,
        "execute_chat_session",
        fake_execute_chat_session,
    )
    monkeypatch.setattr(
        chat_router,
        "_guard_request_multimodal_images",
        fake_guard_request_multimodal_images,
    )

    request = ChatRequest(
        messages=[Message(role="user", content="hi")],
        agent_id="agent_1",
        provider_id="provider_1",
    )
    http_request = SimpleNamespace(
        state=SimpleNamespace(
            user_claims={"userid": "user_1"},
        )
    )

    asyncio.run(chat_router.chat(request, http_request))

    inner_request = captured["request"]
    assert inner_request.provider_id == "provider_1"
    assert captured["require_agent_id"] is True


def test_explicit_provider_override_takes_priority(monkeypatch):
    monkeypatch.setattr(
        config,
        "_GLOBAL_STARTUP_CONFIG",
        config.StartupConfig(app_mode="server"),
        raising=False,
    )
    agent = SimpleNamespace(
        name="Agent",
        user_id="owner_user",
        config={
            "llm_provider_id": "provider_agent",
            "availableTools": [],
            "availableSkills": [],
            "maxLoopCount": 3,
        },
    )

    providers = {
        "provider_request": SimpleNamespace(
            base_url="http://request.local",
            api_key="request-key",
            model="request-model",
            max_tokens=None,
            temperature=0.2,
            top_p=0.8,
            presence_penalty=0.0,
            max_model_len=64000,
            supports_multimodal=True,
            supports_structured_output=True,
        ),
        "provider_agent": SimpleNamespace(
            base_url="http://agent.local",
            api_key="agent-key",
            model="agent-model",
            max_tokens=None,
            temperature=0.3,
            top_p=0.9,
            presence_penalty=0.0,
            max_model_len=32000,
            supports_multimodal=False,
            supports_structured_output=False,
        ),
    }

    class FakeAgentConfigDao:
        async def get_by_id(self, agent_id):
            return agent

    class FakeLLMProviderDao:
        async def get_by_id(self, provider_id):
            return providers.get(provider_id)

        async def get_default(self):
            return providers["provider_agent"]

    async def noop(request):
        return None

    monkeypatch.setattr(chat_service, "AgentConfigDao", FakeAgentConfigDao)
    monkeypatch.setattr(chat_service, "LLMProviderDao", FakeLLMProviderDao)
    monkeypatch.setattr(chat_service, "_register_extra_mcp_tools", noop)
    monkeypatch.setattr(chat_service, "_populate_custom_sub_agents", noop)

    request = StreamRequest(
        messages=[Message(role="user", content="hi")],
        user_id="user_1",
        agent_id="agent_1",
        provider_id="provider_request",
    )

    asyncio.run(chat_service.populate_request_from_agent_config(request))

    assert request.llm_model_config["base_url"] == "http://request.local"
    assert request.llm_model_config["api_key"] == "request-key"
    assert request.llm_model_config["model"] == "request-model"
