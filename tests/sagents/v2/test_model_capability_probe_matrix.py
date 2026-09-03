from __future__ import annotations

import asyncio

import pytest

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.model import (
    ModelCapabilityProbeStatus,
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    probe_model_capabilities,
)


class ProbeProvider:
    def __init__(self, *, fail_all: bool = False):
        self.fail_all = fail_all
        self.requests = []

    async def capabilities(self, model_binding):
        del model_binding
        raise AssertionError("the probe suite must test the configured route")

    async def _stream(self, request):
        self.requests.append(request)
        name = request.request_id
        if self.fail_all or "connection" in name:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="model.provider_permanent",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message="probe rejected",
                    provider_code="422",
                )
            )
        if "multimodal" in name:
            response = ModelResponse(
                response_id="response_image",
                text="red",
                finish_reason="stop",
            )
        elif "structured" in name:
            response = ModelResponse(
                response_id="response_json",
                text='{"ok":true}',
                finish_reason="stop",
            )
        elif "json_object" in name:
            response = ModelResponse(
                response_id="response_json_object",
                text='{"ok":true}',
                finish_reason="stop",
            )
        else:
            response = ModelResponse(
                response_id="response_tool",
                tool_calls=(
                    ModelToolCall(
                        tool_call_id="call_probe",
                        name="sage_capability_probe",
                        arguments={"value": "OK"},
                    ),
                ),
                finish_reason="tool_calls",
            )
        yield ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=response,
        )

    def stream(self, request):
        return self._stream(request)


@pytest.mark.asyncio
async def test_probe_suite_keeps_independent_results_after_one_rejection():
    provider = ProbeProvider()

    report = await probe_model_capabilities(
        provider,
        model_binding="primary",
    )

    assert report.valid is True
    assert report.successful_probes == (
        "multimodal",
        "structured_output",
        "json_object",
        "tool_calling",
    )
    assert report.failed_probes == ("connection",)
    assert report.skipped_probes == ("reasoning_control",)
    connection = report.outcome("connection")
    assert connection.status == ModelCapabilityProbeStatus.ERROR
    assert connection.provider_code == "422"
    assert report.supports_multimodal is True
    assert report.supports_structured_output is True
    assert report.supports_json_object is True
    assert report.supports_tools is True
    assert len(provider.requests) == 5


@pytest.mark.asyncio
async def test_multimodal_probe_keeps_raw_error_and_extracts_image_field_cause():
    class RejectedImageProvider(ProbeProvider):
        async def _stream(self, request):
            self.requests.append(request)
            if "multimodal" in request.request_id:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="model.provider_permanent",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                        message=(
                            "validation errors: ('ResponseInputImageParam', "
                            "'detail'), 'msg': 'Field required'"
                        ),
                        provider_code="400",
                    )
                )
            async for event in super()._stream(request):
                yield event

    report = await probe_model_capabilities(
        RejectedImageProvider(), model_binding="primary"
    )

    outcome = report.outcome("multimodal")
    assert "validation errors" in (outcome.error or "")
    assert outcome.metadata["diagnostic_error"] == (
        "Image payload lost a required Responses field during gateway validation "
        "(ResponseInputImageParam.detail: Field required). If this is a Chat "
        "Completions route, its Chat-to-Responses image conversion is "
        "incompatible; use the OpenAI Responses protocol for multimodal requests."
    )


@pytest.mark.asyncio
async def test_probe_suite_is_invalid_only_when_every_executable_probe_fails():
    provider = ProbeProvider(fail_all=True)

    report = await probe_model_capabilities(
        provider,
        model_binding="primary",
    )

    assert report.valid is False
    assert report.successful_probes == ()
    assert report.failed_probes == (
        "connection",
        "multimodal",
        "structured_output",
        "json_object",
        "tool_calling",
    )
    assert report.skipped_probes == ("reasoning_control",)
    assert len(provider.requests) == 5


@pytest.mark.asyncio
async def test_probe_suite_times_out_each_probe_without_blocking_the_report():
    class SlowProvider(ProbeProvider):
        async def _stream(self, request):
            self.requests.append(request)
            await asyncio.sleep(1)
            if False:
                yield

    provider = SlowProvider()

    report = await probe_model_capabilities(
        provider,
        model_binding="primary",
        timeout_seconds=0.01,
    )

    assert report.valid is False
    assert all(
        report.outcome(name).error_code == "model.probe_timeout"
        for name in (
            "connection",
            "multimodal",
            "structured_output",
            "json_object",
            "tool_calling",
        )
    )
    assert len(provider.requests) == 5


@pytest.mark.asyncio
async def test_reasoning_only_connection_does_not_claim_text_support():
    class ReasoningOnlyProvider(ProbeProvider):
        async def _stream(self, request):
            self.requests.append(request)
            yield ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="reasoning_only",
                    reasoning="internal reasoning",
                    finish_reason="stop",
                ),
            )

    report = await probe_model_capabilities(
        ReasoningOnlyProvider(),
        model_binding="primary",
    )

    assert report.outcome("connection").supported is True
    assert report.outcome("connection").metadata["has_text"] is False
    assert report.supports_text is False
