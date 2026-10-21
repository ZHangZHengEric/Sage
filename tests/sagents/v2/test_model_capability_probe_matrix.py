from __future__ import annotations

from typing import Callable, cast

from sagents.v2.model.provider import ModelProvider

import asyncio

import pytest

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.model import (
    ModelCapabilityProbeOutcome,
    ModelCapabilityProbeReport,
    ModelCapabilityProbeRequest,
    ModelCapabilityProbeStatus,
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    probe_model_capabilities,
)
from sagents.v2.model.capability_probe import probe_model_reasoning_controls


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
@pytest.mark.parametrize("supports_tools", [False, True])
async def test_reasoning_matrix_bounds_concurrency_and_preserves_order_and_dependencies(
    supports_tools,
):
    active = 0
    peak = 0
    ready = asyncio.Event()
    completed_text = set()
    calls = []

    class ReasoningProvider:
        def __init__(self, strategy=None, effort=None):
            self.key = (strategy, effort)

        async def stream(self, request):
            nonlocal active, peak
            _, effort = self.key
            if effort is None:
                yield ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id="base", text="323", finish_reason="stop"
                    ),
                )
                return
            phase = "tools" if request.tools else "text"
            calls.append((*self.key, phase))
            if request.tools:
                assert self.key in completed_text
            active += 1
            peak = max(peak, active)
            if active == 4:
                ready.set()
            try:
                await ready.wait()
                # Finish out of input order to exercise deterministic aggregation.
                for _ in range(2 if effort == "low" else 1):
                    await asyncio.sleep(0)
                if not request.tools:
                    completed_text.add(self.key)
                response = ModelResponse(
                    response_id="probe",
                    text="323" if effort != "max" else "",
                    reasoning="checked" if effort != "max" else "",
                    finish_reason="tool_calls" if request.tools else "stop",
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id="probe",
                            name="sage_capability_probe",
                            arguments={"value": "OK"},
                        ),
                    )
                    if request.tools
                    else (),
                )
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response)
            finally:
                active -= 1

    report = ModelCapabilityProbeReport(
        valid=True,
        supports_tools=supports_tools,
        outcomes=(ModelCapabilityProbeOutcome(name="json_object", status=cast('ModelCapabilityProbeStatus', "supported")),),
    )
    _, metadata = await asyncio.wait_for(
        probe_model_reasoning_controls(
            base_provider=cast(ModelProvider, ReasoningProvider()),
            provider_factory=cast(Callable[[str, str | None], ModelProvider], ReasoningProvider),
            report=report,
            request=ModelCapabilityProbeRequest(
                model_binding="primary",
                route_fingerprint="probe",
                reasoning_efforts=("low", "high", "max"),
            ),
            max_output_tokens=128,
            disable_strategies=(),
            effort_strategies=("reasoning_effort", "chat_template_reasoning_effort"),
        ),
        timeout=1,
    )

    assert peak == 4
    assert active == 0
    assert len(calls) == (10 if supports_tools else 6)
    results = metadata["effort_strategy_outcomes"]
    assert list(results) == ["reasoning_effort", "chat_template_reasoning_effort"]
    for result in results.values():
        assert list(result["outcomes"]) == ["low", "high", "max"]
        assert result["supported"] == ["low", "high"]
        assert result["text_only"] == ["low", "high"]
        assert result["unsupported"] == ["max"]
        assert "with_tools" not in result["outcomes"]["max"]


@pytest.mark.asyncio
async def test_reasoning_matrix_cancellation_drains_active_and_queued_probes():
    active = 0
    started = 0
    ready = asyncio.Event()
    blocked = asyncio.Event()

    class BlockedProvider:
        def __init__(self, strategy=None, effort=None):
            self.effort = effort

        async def stream(self, request):
            nonlocal active, started
            if self.effort is None:
                yield ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id="base", text="323", finish_reason="stop"
                    ),
                )
                return
            active += 1
            started += 1
            if active == 4:
                ready.set()
            try:
                await blocked.wait()
            finally:
                active -= 1

    task = asyncio.create_task(
        probe_model_reasoning_controls(
            base_provider=cast(ModelProvider, BlockedProvider()),
            provider_factory=cast(Callable[[str, str | None], ModelProvider], BlockedProvider),
            report=ModelCapabilityProbeReport(
                valid=True,
                outcomes=(
                    ModelCapabilityProbeOutcome(name="json_object", status=cast('ModelCapabilityProbeStatus', "supported")),
                ),
            ),
            request=ModelCapabilityProbeRequest(
                model_binding="primary",
                route_fingerprint="probe",
            ),
            max_output_tokens=128,
            disable_strategies=(),
            effort_strategies=("reasoning_effort", "chat_template_reasoning_effort"),
        )
    )
    try:
        await asyncio.wait_for(ready.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert active == 0
    assert started == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize(
    ("probe", "message", "status_code", "expected"),
    [
        (
            "structured_output",
            "This response_format type is unavailable now",
            400,
            "unsupported",
        ),
        (
            "structured_output",
            "unsupported response_format: json_schema",
            422,
            "unsupported",
        ),
        (
            "structured_output",
            "'json_schema' is not supported with this model",
            400,
            "unsupported",
        ),
        ("json_object", "This model does not support json_object", 400, "unsupported"),
        (
            "structured_output",
            "Invalid JSON schema: unsupported keyword const",
            400,
            "error",
        ),
        ("structured_output", "response_format: invalid schema", 422, "error"),
        (
            "structured_output",
            "This response_format type is unavailable now",
            401,
            "error",
        ),
        (
            "structured_output",
            "This response_format type is unavailable now",
            500,
            "error",
        ),
        (
            "structured_output",
            "This response_format type is unavailable now",
            None,
            "error",
        ),
        ("structured_output", "max_tokens exceeds model limit", 400, "error"),
        ("connection", "unsupported response_format: json_schema", 400, "error"),
    ],
)
async def test_output_probe_distinguishes_format_rejections_from_errors(
    wrapped, probe, message, status_code, expected
):
    class RejectedFormatProvider(ProbeProvider):
        async def _stream(self, request):
            if probe == "structured_output":
                target = request.response_schema is not None
            elif probe == "json_object":
                target = request.response_format == "json_object"
            else:
                target = "connection" in request.request_id
            if target:
                if wrapped:
                    raise SageV2Error(
                        RuntimeErrorInfo(
                            code="model.provider_permanent",
                            category=ErrorCategory.PROVIDER_PERMANENT,
                            message=message,
                            provider_code=str(status_code)
                            if status_code is not None
                            else None,
                        )
                    )
                error = RuntimeError(message)
                setattr(error, 'status_code', status_code)
                raise error
            async for event in super()._stream(request):
                yield event

    report = await probe_model_capabilities(
        cast(ModelProvider, RejectedFormatProvider()), model_binding="primary"
    )
    outcome = report.outcome(probe)
    assert outcome.status.value == expected
    assert outcome.error == message
    assert outcome.provider_code == (
        str(status_code) if status_code is not None else None
    )
    assert outcome.metadata["diagnostic_error"] == message
    if probe == "structured_output":
        assert report.supports_json_object is True


@pytest.mark.asyncio
async def test_probe_suite_keeps_independent_results_after_one_rejection():
    provider = ProbeProvider()

    report = await probe_model_capabilities(
        cast(ModelProvider, provider),
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
async def test_multimodal_probe_keeps_raw_error_without_inferring_another_protocol():
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
        cast(ModelProvider, RejectedImageProvider()), model_binding="primary"
    )

    outcome = report.outcome("multimodal")
    assert "validation errors" in (outcome.error or "")
    assert "validation errors" in outcome.metadata["diagnostic_error"]
    assert "use the OpenAI Responses protocol" not in outcome.metadata[
        "diagnostic_error"
    ]


@pytest.mark.asyncio
async def test_probe_suite_is_invalid_only_when_every_executable_probe_fails():
    provider = ProbeProvider(fail_all=True)

    report = await probe_model_capabilities(
        cast(ModelProvider, provider),
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
        cast(ModelProvider, provider),
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
        cast(ModelProvider, ReasoningOnlyProvider()),
        model_binding="primary",
    )

    assert report.outcome("connection").supported is True
    assert report.outcome("connection").metadata["has_text"] is False
    assert report.supports_text is False


@pytest.mark.asyncio
async def test_tool_probe_does_not_require_force_or_strict_mode():
    class ThinkingToolsProvider(ProbeProvider):
        async def _stream(self, request):
            if request.tools:
                assert request.tool_choice == 'auto'
                assert all(tool.strict is None for tool in request.tools)
            async for event in super()._stream(request):
                yield event
    report = await probe_model_capabilities(cast(ModelProvider, ThinkingToolsProvider()), model_binding='primary')
    assert report.supports_tools
