import pytest

from app.v2.desktop.backend.catalog import DesktopModelProviderRecord
from app.v2.desktop.backend.model_probe import (
    _probe_diagnostic,
    probe_model_provider_capabilities,
)
from sagents.v2.model import (
    ModelCapabilityProbeOutcome,
    ModelCapabilityProbeStatus,
    ModelCapabilityProfile,
)


def test_chat_multimodal_diagnostic_stays_within_chat_protocol() -> None:
    diagnostic = _probe_diagnostic(
        protocol="openai-chat-completions",
        name="multimodal",
        raw_error=(
            "247 validation errors: ('ResponseInputImageParam', 'detail'), "
            "'msg': 'Field required'"
        ),
        fallback="raw provider error",
    )

    assert diagnostic == (
        "openai-chat-completions image_url probe rejected during provider "
        "validation (image_url.detail: Field required)"
    )
    assert "use the OpenAI Responses protocol" not in diagnostic


def test_non_chat_probe_does_not_use_chat_diagnostic() -> None:
    assert (
        _probe_diagnostic(
            protocol="openai-responses",
            name="multimodal",
            raw_error=(
                "validation errors: ('ResponseInputImageParam', 'detail'), "
                "'msg': 'Field required'"
            ),
            fallback="responses provider error",
        )
        == "responses provider error"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("protocol", "schema_supported", "object_supported", "json_supported"),
    [
        ("openai-chat-completions", True, True, True),
        ("openai-chat-completions", False, True, True),
        ("openai-chat-completions", True, False, True),
        ("openai-chat-completions", False, False, False),
        ("openai-responses", False, True, False),
    ],
)
async def test_desktop_delegates_capability_detection_to_the_selected_plugin(
    protocol, schema_supported, object_supported, json_supported
):
    calls = []

    class PluginProvider:
        raw_client = None

        async def probe_capabilities(self, request):
            calls.append(request)
            outcomes = tuple(
                ModelCapabilityProbeOutcome(
                    name=name,
                    status=(
                        ModelCapabilityProbeStatus.UNSUPPORTED
                        if (name == "structured_output" and not schema_supported)
                        or (name == "json_object" and not object_supported)
                        else ModelCapabilityProbeStatus.SUPPORTED
                    ),
                    response="ok",
                )
                for name in (
                    "connection",
                    "multimodal",
                    "structured_output",
                    "json_object",
                    "tool_calling",
                    "reasoning_control",
                )
            )
            return ModelCapabilityProfile(
                plugin_id=f"sage.model.{protocol}",
                plugin_version="3.0.0",
                protocol=protocol,
                route_fingerprint=request.route_fingerprint,
                effective_max_output_tokens=512,
                outcomes=outcomes,
                invocation_strategy={
                    "max_output_tokens_field": "max_tokens",
                    "image_detail_mode": "omit",
                    "supports_json_object": object_supported,
                    "auxiliary_json_compatible": True,
                },
            )

    record = DesktopModelProviderRecord(
        id="deepseek_vision",
        user_id="user_1",
        name="DeepSeek Vision",
        protocol=protocol,
        model="DeepSeek-V4-Flash-Vision-Exp",
        base_url="https://example.invalid/v1",
        api_key="secret",
        max_tokens=8_192,
    )
    result = await probe_model_provider_capabilities(
        record,
        provider_factory=lambda *args, **kwargs: PluginProvider(),
        compatibility_fingerprint=lambda value: "sha256:route",
        output_token_fallbacks=(4_096, 512),
        reasoning_disable_extras={"omit": {}},
        reasoning_efforts=("low",),
    )

    assert len(calls) == 1
    assert calls[0].model_binding == "deepseek_vision"
    assert result["supports_multimodal"] is True
    assert result["supports_structured_output"] is json_supported
    assert result["supports_json_object"] is object_supported
    assert result["structured_output"]["supported"] is schema_supported
    assert result["effective_max_output_tokens"] == 512
    profile = result["compatibility_profile"]["plugin_profile"]
    assert profile["plugin_id"] == f"sage.model.{protocol}"
    assert profile["invocation_strategy"]["image_detail_mode"] == "omit"
