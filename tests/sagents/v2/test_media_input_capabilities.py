from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from sagents.v2.agent.step_request import (
    DefaultAgentStepRequestBuilder,
    tools_for_model_inputs,
)
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import AudioBlock, FileBlock, TextBlock
from sagents.v2.model import (
    AnthropicMessagesConfig,
    AnthropicMessagesModelProvider,
    OpenAIChatCompletionsConfig,
    OpenAIChatCompletionsModelProvider,
    OpenAIResponsesConfig,
    OpenAIResponsesModelProvider,
)
from sagents.v2.model.contracts import ModelEventKind, ModelMessage, ModelRequest
from sagents.v2.model.plugins.gemini_generate_content import (
    GeminiGenerateContentConfig,
    GeminiGenerateContentModelProvider,
)
from sagents.v2.model.protocols import create_registered_model_provider
from sagents.v2.model.wire_diagnostics import WireCapture, wire_capture
from sagents.v2.package.manifest.models import ModelCapabilityDeclaration, ModelRoute
from sagents.v2.tool import DirectToolSelectionPolicy, ToolDefinition
from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog
from tests.sagents.v2.model_fixture import FULL_MODEL_CAPABILITIES

if TYPE_CHECKING:
    from sagents.v2.context.assembler import ContextAssembler
    from sagents.v2.contracts.commands import RunConfig

AUDIO_DATA = "UklGRg=="
VIDEO_DATA = "AAAAIGZ0eXA="
AUDIO = AudioBlock(uri=f"data:audio/wav;base64,{AUDIO_DATA}", mime_type="audio/wav")
VIDEO = FileBlock(
    uri=f"data:video/mp4;base64,{VIDEO_DATA}", name="clip.mp4", mime_type="video/mp4"
)


def _caps(**changes):
    return FULL_MODEL_CAPABILITIES.model_copy(update=changes)


def _request() -> ModelRequest:
    return ModelRequest(
        request_id="request_1",
        run_id="run_1",
        model_binding="primary",
        messages=(
            ModelMessage(role="user", content=(TextBlock(text="listen"), AUDIO, VIDEO)),
        ),
    )


def _chat(capabilities):
    return OpenAIChatCompletionsModelProvider(
        OpenAIChatCompletionsConfig(
            base_url="https://gw.invalid/v1", model="m", capabilities=capabilities
        ),
        client=object(),
    )


def _gemini(capabilities):
    return GeminiGenerateContentModelProvider(
        GeminiGenerateContentConfig(model="g", capabilities=capabilities),
        client=object(),
    )


BOTH = {"supports_audio_input": True, "supports_video_input": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        (_gemini(_caps()), (True, True)),
        (_gemini(_caps(supports_multimodal_input=False)), (False, False)),
        (_gemini(_caps(supports_video_input=False)), (True, False)),
        (_chat(_caps()), (False, False)),
        (_chat(_caps(supports_audio_input=True)), (True, False)),
        (
            OpenAIResponsesModelProvider(
                OpenAIResponsesConfig(model="m", capabilities=_caps(**BOTH)),
                client=object(),
            ),
            (False, False),
        ),
        (
            AnthropicMessagesModelProvider(
                AnthropicMessagesConfig(model="m", capabilities=_caps(**BOTH)),
                client=object(),
            ),
            (False, False),
        ),
    ],
    ids=[
        "gemini-default",
        "gemini-text-only",
        "gemini-video-off",
        "chat-default",
        "chat-audio",
        "responses-ignored",
        "anthropic-ignored",
    ],
)
async def test_protocol_defaults_resolve_media_inputs(provider, expected):
    declared = provider.config.capabilities

    capabilities = await provider.capabilities("primary")

    assert (capabilities.supports_audio_input, capabilities.supports_video_input) == expected
    assert provider.config.capabilities is declared


@pytest.mark.asyncio
async def test_manifest_declaration_reaches_registered_provider():
    provider = create_registered_model_provider(
        ModelRoute(
            provider="openai-chat-completions",
            base_url="https://gw.invalid/v1",
            model="qwen-omni",
            capabilities=ModelCapabilityDeclaration(multimodal=True, video_input=True),
        ),
        client=object(),
    )

    capabilities = await provider.capabilities("primary")

    assert capabilities.supports_video_input is True
    assert capabilities.supports_audio_input is False


@pytest.mark.parametrize(
    "provider",
    [
        OpenAIChatCompletionsModelProvider(
            OpenAIChatCompletionsConfig(
                base_url="https://gw.invalid/v1", model="m", capabilities=_caps()
            ),
            client=object(),
        ),
        OpenAIResponsesModelProvider(
            OpenAIResponsesConfig(model="m", capabilities=_caps()), client=object()
        ),
        AnthropicMessagesModelProvider(
            AnthropicMessagesConfig(model="m", capabilities=_caps()), client=object()
        ),
        GeminiGenerateContentModelProvider(
            GeminiGenerateContentConfig(
                model="g",
                capabilities=_caps(
                    supports_audio_input=False, supports_video_input=False
                ),
            ),
            client=object(),
        ),
    ],
    ids=["chat", "responses", "anthropic", "gemini-disabled"],
)
def test_unsupported_media_degrades_to_notice_without_payload(provider):
    wire = json.dumps(provider.diagnostic_request(_request()))

    assert AUDIO_DATA not in wire and VIDEO_DATA not in wire
    assert "Audio attachment omitted" in wire
    assert "Video attachment omitted" in wire


def test_unsupported_media_passes_validation_on_text_only_models():
    provider = AnthropicMessagesModelProvider(
        AnthropicMessagesConfig(
            model="m", capabilities=_caps(supports_multimodal_input=False)
        ),
        client=object(),
    )

    assert "Audio attachment omitted" in json.dumps(provider.diagnostic_request(_request()))


def test_chat_completions_sends_native_media_when_declared():
    provider = OpenAIChatCompletionsModelProvider(
        OpenAIChatCompletionsConfig(
            base_url="https://gw.invalid/v1",
            model="qwen-omni",
            capabilities=_caps(supports_audio_input=True, supports_video_input=True),
        ),
        client=object(),
    )

    parts = provider.diagnostic_request(_request())["messages"][0]["content"]

    assert parts[1] == {
        "type": "input_audio",
        "input_audio": {"data": AUDIO_DATA, "format": "wav"},
    }
    assert parts[2] == {"type": "video_url", "video_url": {"url": VIDEO.uri}}


async def test_chat_video_storage_publishes_local_media_and_keeps_each_prompt(monkeypatch):
    from sagents.v2.model.plugins import openai_compatible

    remote = "https://media.example/second.mp4"
    uploads = []

    async def publish(config, videos, *, required=()):
        assert config.bucket == "private-video"
        assert videos == {VIDEO.uri: "video/mp4"}
        url = f"https://storage.example/first.mp4?signature=temporary-{len(uploads)}"
        uploads.append(url)
        return {VIDEO.uri: url}

    monkeypatch.setattr(openai_compatible, "publish_videos", publish)
    sent = []

    async def create(**kwargs):
        sent.append(kwargs)

        async def chunks():
            yield {"id": "_test", "choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}

        return chunks()

    provider = create_registered_model_provider(
        ModelRoute.model_validate({
            "provider": "openai-chat-completions",
            "base_url": "https://gw.example/v1",
            "model": "gemini-4-argon",
            "capabilities": {"multimodal": True, "video_input": True},
            "request": {"extra": {
                "video_url_format": "image_url",
                "video_storage": {"bucket": "private-video"},
                "max_inline_images": 0,
            }},
        }),
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    request = _request().model_copy(update={"messages": (
        ModelMessage(role="user", content=(TextBlock(text="Describe the first"), VIDEO)),
        ModelMessage(role="user", content=(
            TextBlock(text="Describe the second"), VIDEO.model_copy(update={"uri": remote}),
        )),
    )})
    capture = WireCapture()
    token = wire_capture.set(capture)
    try:
        for _ in range(2):
            events = [event async for event in provider.stream(request)]
            assert events[-1].kind == ModelEventKind.COMPLETED
    finally:
        wire_capture.reset(token)

    assert len(uploads) == 2
    for call, signed_url in zip(sent, uploads, strict=True):
        assert "extra_body" not in call
        assert [message["content"] for message in call["messages"]] == [
            [{"type": "text", "text": "Describe the first"},
             {"type": "image_url", "image_url": {"url": signed_url}}],
            [{"type": "text", "text": "Describe the second"},
             {"type": "image_url", "image_url": {"url": remote}}],
        ]
    assert request.messages[0].content[1] == VIDEO
    captured = json.dumps(capture.events)
    assert "signature=temporary" not in captured
    assert "first.mp4?[redacted]" in captured


async def test_gemini_video_storage_sends_signed_file_data_and_redacts_diagnostics(monkeypatch):
    import httpx

    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.model.plugins import gemini_generate_content

    remote = "https://media.example/second.mp4"
    signed_url = "https://storage.example/first.mp4?signature=temporary"

    async def publish(config, videos, *, required=()):
        assert config.bucket == "private-video"
        assert videos == {VIDEO.uri: "video/mp4"}
        return {VIDEO.uri: signed_url}

    monkeypatch.setattr(gemini_generate_content, "publish_videos", publish)
    sent = []

    def handler(wire):
        sent.append(json.loads(wire.content))
        if len(sent) == 2:
            return httpx.Response(400, text=f"cannot fetch {signed_url}")
        return httpx.Response(
            200,
            text="data: " + json.dumps({"candidates": [{
                "content": {"role": "model", "parts": [{"text": "done"}]},
                "finishReason": "STOP",
            }]}) + "\n\n",
            headers={"content-type": "text/event-stream"},
        )

    provider = create_registered_model_provider(
        ModelRoute.model_validate({
            "provider": "gemini-generate-content",
            "base_url": "https://gemini.example/v1beta",
            "model": "gemini-4-argon",
            "capabilities": {"multimodal": True},
            "request": {"extra": {"video_storage": {"bucket": "private-video"}}},
        }),
        client=httpx.AsyncClient(
            base_url="https://gemini.example/v1beta/", transport=httpx.MockTransport(handler)
        ),
    )
    request = _request().model_copy(update={"messages": (
        ModelMessage(role="user", content=(
            TextBlock(text="Compare"), VIDEO, VIDEO.model_copy(update={"uri": remote}),
        )),
    )})
    capture = WireCapture()
    token = wire_capture.set(capture)
    try:
        events = [event async for event in provider.stream(request)]
        assert events[-1].kind == ModelEventKind.COMPLETED
        with pytest.raises(SageV2Error) as failure:
            [event async for event in provider.stream(request)]
    finally:
        wire_capture.reset(token)

    assert sent[0]["contents"][0]["parts"] == [
        {"text": "Compare"},
        {"fileData": {"mimeType": "video/mp4", "fileUri": signed_url}},
        {"fileData": {"mimeType": "video/mp4", "fileUri": remote}},
    ]
    assert request.messages[0].content[1] == VIDEO
    observed = json.dumps(capture.events) + failure.value.info.model_dump_json()
    assert "signature=temporary" not in observed
    assert "first.mp4?[redacted]" in observed
    assert failure.value.__cause__ is None


async def test_gemini_video_storage_skips_videos_evicted_by_the_inline_cap(monkeypatch):
    import base64

    import httpx

    from sagents.v2.model.plugins import gemini_generate_content

    videos = [
        VIDEO.model_copy(update={
            "uri": "data:video/mp4;base64," + base64.b64encode(f"clip-{index}".encode()).decode()
        })
        for index in range(3)
    ]

    async def publish(config, inline, *, required=()):
        if videos[0].uri in inline:
            raise AssertionError("evicted video must not be uploaded")
        return {uri: f"https://storage.example/{index}.mp4?signature=s" for index, uri in enumerate(inline)}

    monkeypatch.setattr(gemini_generate_content, "publish_videos", publish)
    sent = []

    def handler(wire):
        sent.append(json.loads(wire.content))
        return httpx.Response(
            200,
            text="data: " + json.dumps({"candidates": [{
                "content": {"role": "model", "parts": [{"text": "done"}]},
                "finishReason": "STOP",
            }]}) + "\n\n",
            headers={"content-type": "text/event-stream"},
        )

    provider = create_registered_model_provider(
        ModelRoute.model_validate({
            "provider": "gemini-generate-content",
            "base_url": "https://gemini.example/v1beta",
            "model": "gemini-4-argon",
            "capabilities": {"multimodal": True},
            "request": {"extra": {
                "video_storage": {"bucket": "private-video"}, "max_inline_videos": 2,
            }},
        }),
        client=httpx.AsyncClient(
            base_url="https://gemini.example/v1beta/", transport=httpx.MockTransport(handler)
        ),
    )
    request = _request().model_copy(update={"messages": tuple(
        ModelMessage(role="user", content=(TextBlock(text=f"clip {index}"), video))
        for index, video in enumerate(videos)
    )})
    events = [event async for event in provider.stream(request)]

    assert events[-1].kind == ModelEventKind.COMPLETED
    parts = [part for content in sent[0]["contents"] for part in content["parts"]]
    assert not any("inlineData" in part for part in parts)
    assert [part["fileData"]["fileUri"] for part in parts if "fileData" in part] == [
        "https://storage.example/0.mp4?signature=s",
        "https://storage.example/1.mp4?signature=s",
    ]


async def test_private_chat_video_object_is_reused_and_signed_with_the_aws_sdk(monkeypatch):
    boto3 = pytest.importorskip("boto3")
    from urllib.parse import parse_qs, urlsplit

    from botocore.config import Config
    from botocore.stub import ANY, Stubber

    from sagents.v2.model.plugins._shared.video_storage import (
        S3VideoStorageConfig,
        publish_videos,
    )

    client = boto3.session.Session(
        aws_access_key_id="test-key", aws_secret_access_key="test-secret", region_name="us-east-1"
    ).client("s3", config=Config(signature_version="s3v4"))
    monkeypatch.setattr(boto3.session, "Session", lambda: SimpleNamespace(client=lambda *a, **kw: client))
    video = {VIDEO.uri: "video/mp4"}
    config = S3VideoStorageConfig(bucket="private-video", url_ttl_seconds=300)
    expected_put = {
        "Bucket": "private-video", "Key": ANY, "Body": b"\x00\x00\x00 ftyp",
        "ContentType": "video/mp4", "IfNoneMatch": "*",
    }
    expected_head = {"Bucket": "private-video", "Key": ANY}
    with Stubber(client) as stub:
        stub.add_client_error(
            "head_object", service_error_code="403", http_status_code=403,
            expected_params=expected_head,
        )
        stub.add_response("put_object", {}, expected_put)
        stub.add_response("head_object", {}, expected_head)
        stub.add_client_error(
            "head_object", service_error_code="404", http_status_code=404,
            expected_params=expected_head,
        )
        stub.add_client_error(
            "put_object", service_error_code="PreconditionFailed", http_status_code=412,
            expected_params=expected_put,
        )
        first = urlsplit((await publish_videos(config, video))[VIDEO.uri])
        replay = urlsplit((await publish_videos(config, video))[VIDEO.uri])
        concurrent = urlsplit((await publish_videos(config, video))[VIDEO.uri])
        stub.assert_no_pending_responses()

    assert first.path == replay.path == concurrent.path
    assert first.path.startswith("/sage/model-video/") and first.path.endswith(".mp4")
    query = parse_qs(replay.query)
    assert query["X-Amz-Expires"] == ["300"]
    assert query["X-Amz-Signature"]


async def test_video_storage_skips_failed_history_but_fails_the_current_video(monkeypatch):
    boto3 = pytest.importorskip("boto3")
    from botocore.config import Config
    from botocore.stub import ANY, Stubber

    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.model.plugins._shared.video_storage import (
        S3VideoStorageConfig,
        publish_videos,
    )

    client = boto3.session.Session(
        aws_access_key_id="test-key", aws_secret_access_key="test-secret", region_name="us-east-1"
    ).client("s3", config=Config(signature_version="s3v4"))
    monkeypatch.setattr(boto3.session, "Session", lambda: SimpleNamespace(client=lambda *a, **kw: client))
    history = "data:video/mp4;base64,aGlzdG9yeQ=="
    videos = {history: "video/mp4", VIDEO.uri: "video/mp4"}
    config = S3VideoStorageConfig(bucket="private-video")
    head = {"Bucket": "private-video", "Key": ANY}
    with Stubber(client) as stub:
        stub.add_client_error("head_object", http_status_code=503, expected_params=head)
        stub.add_response("head_object", {}, head)
        signed = await publish_videos(config, videos, required={VIDEO.uri})
        stub.add_client_error("head_object", http_status_code=503, expected_params=head)
        with pytest.raises(SageV2Error) as failure:
            await publish_videos(config, {VIDEO.uri: "video/mp4"}, required={VIDEO.uri})
        stub.assert_no_pending_responses()

    assert list(signed) == [VIDEO.uri]
    assert failure.value.info.code == "model.video_storage_failed"
    assert failure.value.info.retryable is True


async def test_missing_storage_sdk_only_fails_requests_with_current_videos(monkeypatch):
    import sys

    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.model.plugins._shared.video_storage import (
        S3VideoStorageConfig,
        publish_videos,
    )

    monkeypatch.setitem(sys.modules, "boto3", None)
    config = S3VideoStorageConfig(bucket="private-video")
    videos = {VIDEO.uri: "video/mp4"}

    assert await publish_videos(config, videos) == {}
    with pytest.raises(SageV2Error, match="sage\\[s3-video\\]"):
        await publish_videos(config, videos, required={VIDEO.uri})


@pytest.mark.parametrize("protocol", ["openai-chat-completions", "gemini-generate-content"])
async def test_history_video_upload_failure_is_omitted_not_fatal(monkeypatch, protocol):
    import base64

    import httpx

    from sagents.v2.model.plugins import gemini_generate_content, openai_compatible
    from sagents.v2.model.plugins._shared.video_storage import STORAGE_OMITTED_TEXT

    history = VIDEO.model_copy(update={
        "uri": "data:video/mp4;base64," + base64.b64encode(b"history").decode()
    })
    current_url = "https://storage.example/current.mp4?signature=s"
    calls = []

    async def publish(config, videos, *, required=()):
        calls.append((set(videos), set(required)))
        return {VIDEO.uri: current_url}

    monkeypatch.setattr(openai_compatible, "publish_videos", publish)
    monkeypatch.setattr(gemini_generate_content, "publish_videos", publish)
    request = _request().model_copy(update={"messages": (
        ModelMessage(role="user", content=(TextBlock(text="Earlier"), history)),
        ModelMessage(role="assistant", content=(TextBlock(text="Seen"),)),
        ModelMessage(role="user", content=(TextBlock(text="Now"), VIDEO)),
    )})
    extra = {"video_storage": {"bucket": "private-video"}}
    sent = []
    if protocol == "openai-chat-completions":
        extra["video_url_format"] = "image_url"

        async def create(**kwargs):
            sent.append(kwargs)

            async def chunks():
                yield {"id": "_test", "choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}

            return chunks()

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    else:
        def handler(wire):
            sent.append(json.loads(wire.content))
            return httpx.Response(
                200,
                text="data: " + json.dumps({"candidates": [{
                    "content": {"role": "model", "parts": [{"text": "done"}]},
                    "finishReason": "STOP",
                }]}) + "\n\n",
                headers={"content-type": "text/event-stream"},
            )

        client = httpx.AsyncClient(
            base_url="https://gw.example/v1beta/", transport=httpx.MockTransport(handler)
        )
    provider = create_registered_model_provider(
        ModelRoute.model_validate({
            "provider": protocol,
            "base_url": "https://gw.example/v1beta",
            "model": "gemini-4-argon",
            "capabilities": {"multimodal": True, "video_input": True},
            "request": {"extra": extra},
        }),
        client=client,
    )
    capture = WireCapture()
    token = wire_capture.set(capture)
    try:
        events = [event async for event in provider.stream(request)]
    finally:
        wire_capture.reset(token)

    assert events[-1].kind == ModelEventKind.COMPLETED
    assert calls == [({history.uri, VIDEO.uri}, {VIDEO.uri})]
    if protocol == "openai-chat-completions":
        first, _, last = (message["content"] for message in sent[0]["messages"])
        assert first[1] == {"type": "text", "text": STORAGE_OMITTED_TEXT}
        assert last[1] == {"type": "image_url", "image_url": {"url": current_url}}
    else:
        first, _, last = (content["parts"] for content in sent[0]["contents"])
        assert first[1] == {"text": STORAGE_OMITTED_TEXT}
        assert last[1] == {"fileData": {"mimeType": "video/mp4", "fileUri": current_url}}
    assert {"diagnostic_event": "video_storage_omitted", "videos": 1} in capture.events


def test_chat_completions_maps_mpeg_audio_to_mp3_format():
    provider = OpenAIChatCompletionsModelProvider(
        OpenAIChatCompletionsConfig(
            base_url="https://gw.invalid/v1",
            model="gpt-audio",
            capabilities=_caps(supports_audio_input=True),
        ),
        client=object(),
    )
    request = _request().model_copy(update={"messages": (
        ModelMessage(role="user", content=(
            AudioBlock(uri="data:audio/mpeg;base64,SUQz", mime_type="audio/mpeg"),
        )),
    )})

    content = provider.diagnostic_request(request)["messages"][0]["content"]

    assert content[0]["input_audio"] == {"data": "SUQz", "format": "mp3"}


class _CapabilityModel:
    def __init__(self, capabilities=None, error=None):
        self._capabilities = capabilities
        self._error = error
        self.bindings: list[str] = []

    async def capabilities(self, model_binding):
        self.bindings.append(model_binding)
        if self._error is not None:
            raise self._error
        return self._capabilities


def _tool(name: str, *inputs: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=name,
        input_schema={"type": "object", "properties": {}},
        required_model_inputs=inputs,
    )


TOOLS = (_tool("read_file"), _tool("analyze_audio", "audio"), _tool("analyze_video", "video"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (None, {"read_file", "analyze_audio", "analyze_video"}),
        (_CapabilityModel(_caps(supports_audio_input=True)), {"read_file", "analyze_audio"}),
        (_CapabilityModel(_caps()), {"read_file"}),
        (_CapabilityModel(error=RuntimeError("unavailable")), {"read_file"}),
    ],
    ids=["no-model", "audio-only", "unset", "lookup-fails"],
)
async def test_media_tools_follow_model_inputs(model, expected):
    visible = await tools_for_model_inputs(TOOLS, model, "primary")

    assert {tool.name for tool in visible} == expected


class _PassthroughContextAssembler:
    async def prepare_messages(self, command, messages, *, run_id=None, reservation=None):
        return messages


@pytest.mark.asyncio
async def test_step_request_hides_media_tools_for_primary_binding():
    model = _CapabilityModel(_caps(supports_video_input=True))
    builder = DefaultAgentStepRequestBuilder(
        context_assembler=cast("ContextAssembler", _PassthroughContextAssembler()),
        tool_catalog=InMemoryToolCatalog(TOOLS),
        tool_selection_policy=DirectToolSelectionPolicy(),
        model=model,
    )
    command = StartRun(
        agent_id="agent_1",
        input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
        config=cast("RunConfig", {"model_bindings": {"primary": "model.omni"}}),
        resolved_spec_hash="sha256:spec",
        idempotency_key="start_1",
    )

    prepared = await builder.prepare(
        command=command,
        run_id="run_1",
        turn_id="turn_1",
        step_id="step_1",
        messages=(),
        pending_continuation_reason=None,
        language="en",
    )

    assert {tool.name for tool in prepared.request.tools} == {"read_file", "analyze_video"}
    assert model.bindings == ["model.omni"]
