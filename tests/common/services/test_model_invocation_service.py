from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from common.core.exceptions import SageHTTPException
from common.schemas.model_invocation import DirectModelInvokeRequest
from common.services import model_invocation_service as service


class FakeProvider:
    def __init__(
        self,
        provider_id: str,
        *,
        model: str,
        user_id: str = "user_1",
        supports_multimodal: bool = True,
        supports_structured_output: bool = True,
    ) -> None:
        self.id = provider_id
        self.name = provider_id
        self.base_url = f"https://example.com/{provider_id}"
        self.api_keys = [f"key-{provider_id}"]
        self.model = model
        self.max_tokens = 1000
        self.temperature = 0.7
        self.top_p = None
        self.presence_penalty = None
        self.max_model_len = None
        self.supports_multimodal = supports_multimodal
        self.supports_structured_output = supports_structured_output
        self.user_id = user_id

    @property
    def api_key(self) -> str:
        return self.api_keys[0]


class FakeDao:
    def __init__(self, providers: dict[str, FakeProvider]) -> None:
        self.providers = providers

    async def get_by_id(self, provider_id: str):
        return self.providers.get(provider_id)

    async def get_default(self, user_id=None):
        return self.providers.get("default")


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeUsage:
    def model_dump(self, mode="json"):
        return {
            "prompt_tokens": 12,
            "completion_tokens": 5,
            "total_tokens": 17,
        }


class FakeCompletion:
    usage = FakeUsage()

    def model_dump(self, mode="json"):
        return {
            "id": "chatcmpl_test",
            "object": "chat.completion",
            "model": "fake-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": '{"ok":true}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": self.usage.model_dump(mode=mode),
        }


class FakeChunk:
    def __init__(self, content: str = "", usage=None) -> None:
        self.usage = usage
        self._content = content

    def model_dump(self, mode="json"):
        data = {
            "id": "chatcmpl_chunk",
            "object": "chat.completion.chunk",
            "model": "fake-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": self._content},
                    "finish_reason": None,
                }
            ],
        }
        if self.usage is not None:
            data["usage"] = self.usage.model_dump(mode=mode)
        return data


def _patch_common(monkeypatch, providers):
    dao = FakeDao(providers)
    captured: dict[str, object] = {}
    fake_client = FakeClient()

    monkeypatch.setattr(service, "LLMProviderDao", lambda: dao)
    monkeypatch.setattr(service, "create_model_client", lambda config: fake_client)

    async def fake_record_execution_payload(**kwargs):
        captured["usage_record"] = kwargs
        return True

    monkeypatch.setattr(
        service.token_usage_service,
        "record_execution_payload",
        fake_record_execution_payload,
    )
    return captured, fake_client


@pytest.mark.asyncio
async def test_provider_id_takes_priority_and_request_stays_openai_shaped(monkeypatch):
    providers = {
        "provider_1": FakeProvider("provider_1", model="gpt-5-mini"),
        "agent_provider": FakeProvider("agent_provider", model="gpt-4o"),
    }
    captured, fake_client = _patch_common(monkeypatch, providers)

    async def fake_get_agent(agent_id, user_id):
        return SimpleNamespace(
            agent_id=agent_id,
            config={"llm_provider_id": "agent_provider"},
        )

    async def fake_completion(client, **kwargs):
        captured["completion_kwargs"] = kwargs
        return FakeCompletion()

    monkeypatch.setattr(service.agent_service, "get_agent", fake_get_agent)
    monkeypatch.setattr(
        service, "create_chat_completion_with_fallback", fake_completion
    )

    request = DirectModelInvokeRequest(
        agent_id="agent_1",
        provider_id="provider_1",
        task="ling_file_semantic_classification",
        messages=[
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "noop", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": "ok",
            },
            {"role": "user", "content": "hi", "name": "tester"},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=50,
        seed=7,
        model="should-not-pass-through",
        api_key="should-not-pass-through",
    )

    result = await service.invoke_model(request, user_id="user_1")

    kwargs = captured["completion_kwargs"]
    assert kwargs["model"] == "gpt-5-mini"
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0.1
    assert kwargs["max_tokens"] == 50
    assert kwargs["seed"] == 7
    assert kwargs["model_type"] == "standard"
    assert kwargs["extra_body"]["reasoning_effort"] == "low"
    assert kwargs["messages"][0]["tool_calls"][0]["id"] == "call_1"
    assert kwargs["messages"][1]["tool_call_id"] == "call_1"
    assert kwargs["messages"][2]["name"] == "tester"
    assert "api_key" not in kwargs
    assert "base_url" not in kwargs
    assert result["object"] == "chat.completion"
    assert result["provider_id"] == "provider_1"
    assert captured["usage_record"]["request_source"] == (
        "ling_file_semantic_classification"
    )
    assert fake_client.closed is True


@pytest.mark.asyncio
async def test_agent_fast_model_uses_agent_fast_provider(monkeypatch):
    providers = {
        "standard": FakeProvider(
            "standard",
            model="gpt-4o",
            supports_multimodal=True,
            supports_structured_output=True,
        ),
        "fast": FakeProvider(
            "fast",
            model="gpt-4o-mini",
            supports_multimodal=False,
            supports_structured_output=False,
        ),
    }
    captured, _ = _patch_common(monkeypatch, providers)

    async def fake_get_agent(agent_id, user_id):
        return SimpleNamespace(
            agent_id=agent_id,
            config={
                "llm_provider_id": "standard",
                "fast_llm_provider_id": "fast",
            },
        )

    async def fake_completion(client, **kwargs):
        captured["completion_kwargs"] = kwargs
        return FakeCompletion()

    monkeypatch.setattr(service.agent_service, "get_agent", fake_get_agent)
    monkeypatch.setattr(
        service, "create_chat_completion_with_fallback", fake_completion
    )

    request = DirectModelInvokeRequest(
        agent_id="agent_1",
        model_type="fast",
        task="title_generation",
        messages=[{"role": "user", "content": "hi"}],
    )

    await service.invoke_model(request, user_id="user_1")

    assert captured["completion_kwargs"]["model"] == "gpt-4o-mini"
    assert captured["completion_kwargs"]["model_type"] == "fast"
    assert captured["completion_kwargs"]["model_config"]["supports_multimodal"] is False
    assert (
        captured["completion_kwargs"]["model_config"]["supports_structured_output"]
        is False
    )


@pytest.mark.asyncio
async def test_thinking_level_controls_reasoning_effort(monkeypatch):
    providers = {"provider_1": FakeProvider("provider_1", model="gpt-5-mini")}
    captured, _ = _patch_common(monkeypatch, providers)

    async def fake_completion(client, **kwargs):
        captured["completion_kwargs"] = kwargs
        return FakeCompletion()

    monkeypatch.setattr(
        service, "create_chat_completion_with_fallback", fake_completion
    )

    request = DirectModelInvokeRequest(
        provider_id="provider_1",
        task="semantic_summary",
        messages=[{"role": "user", "content": "hi"}],
        deep_thinking=True,
        thinking_level="high",
    )

    await service.invoke_model(request, user_id="user_1")

    assert captured["completion_kwargs"]["extra_body"]["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_stream_model_emits_openai_style_sse_and_records_usage(monkeypatch):
    providers = {"provider_1": FakeProvider("provider_1", model="gpt-4o")}
    captured, _ = _patch_common(monkeypatch, providers)

    async def fake_completion(client, **kwargs):
        captured["completion_kwargs"] = kwargs

        async def stream():
            yield FakeChunk("he")
            yield FakeChunk("llo", usage=FakeUsage())

        return stream()

    monkeypatch.setattr(
        service, "create_chat_completion_with_fallback", fake_completion
    )

    request = DirectModelInvokeRequest(
        provider_id="provider_1",
        task="tag_extract",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )

    events = [event async for event in service.stream_model(request, user_id="user_1")]

    assert captured["completion_kwargs"]["stream"] is True
    assert captured["completion_kwargs"]["stream_options"] == {"include_usage": True}
    assert events[-1] == "data: [DONE]\n\n"
    first_payload = json.loads(events[0].removeprefix("data: ").strip())
    assert first_payload["object"] == "chat.completion.chunk"
    assert first_payload["provider_id"] == "provider_1"
    assert captured["usage_record"]["token_usage"]["total_info"]["total_tokens"] == 17


def test_task_or_metadata_is_required():
    with pytest.raises(ValueError):
        DirectModelInvokeRequest(messages=[{"role": "user", "content": "hi"}])

    with pytest.raises(ValueError):
        DirectModelInvokeRequest(task="empty_messages", messages=[])

    with pytest.raises(ValueError):
        DirectModelInvokeRequest(
            metadata={"opaque": "value"},
            messages=[{"role": "user", "content": "hi"}],
        )


@pytest.mark.asyncio
async def test_metadata_attribution_is_recorded_when_task_is_absent(monkeypatch):
    providers = {"provider_1": FakeProvider("provider_1", model="gpt-4o")}
    captured, _ = _patch_common(monkeypatch, providers)

    async def fake_completion(client, **kwargs):
        captured["completion_kwargs"] = kwargs
        return FakeCompletion()

    monkeypatch.setattr(
        service, "create_chat_completion_with_fallback", fake_completion
    )

    request = DirectModelInvokeRequest(
        provider_id="provider_1",
        metadata={"request_source": "ling_tags"},
        messages=[{"role": "user", "content": "hi"}],
    )

    result = await service.invoke_model(request, user_id="user_1")

    assert result["request_source"] == "ling_tags"
    assert captured["usage_record"]["request_source"] == "ling_tags"
    assert captured["completion_kwargs"]["extra_body"]["_step_name"] == "ling_tags"


def test_metadata_log_sanitizer_redacts_sensitive_values():
    sanitized = service._sanitize_for_log(
        {
            "request_source": "ling_tags",
            "access_token": "secret-token",
            "nested": {
                "password": "secret-password",
                "image": "data:image/png;base64,AAAA",
            },
        }
    )

    assert sanitized["request_source"] == "ling_tags"
    assert sanitized["access_token"] == "<redacted>"
    assert sanitized["nested"]["password"] == "<redacted>"
    assert sanitized["nested"]["image"] == "<redacted data URL; base64_len=4>"


@pytest.mark.asyncio
async def test_provider_permission_is_enforced(monkeypatch):
    providers = {
        "provider_1": FakeProvider(
            "provider_1",
            model="gpt-4o",
            user_id="other_user",
        )
    }
    _patch_common(monkeypatch, providers)
    request = DirectModelInvokeRequest(
        provider_id="provider_1",
        task="summary",
        messages=[{"role": "user", "content": "hi"}],
    )

    with pytest.raises(SageHTTPException) as exc_info:
        await service.invoke_model(request, user_id="user_1")

    assert exc_info.value.status_code == 403
