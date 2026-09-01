"""Reusable, provider-backed model capability probes.

The suite deliberately exercises the configured ``ModelProvider`` rather than
reconstructing provider wire payloads. Each probe is independent: one rejected
parameter combination is evidence about that capability only, not evidence
that the whole model route is invalid.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from sagents.v2.contracts.common import StrictModel, new_id
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolDefinition,
)
from sagents.v2.model.provider import ModelProvider


_PROBE_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAIAAAAC64paAAAAG0lEQVR4nGP8z0A+"
    "YKJA76jmUc2jmkc1U0EzACKcASc1hNCeAAAAAElFTkSuQmCC"
)
_RED_MARKERS = ("red", "红色", "红", "赤", "绯", "朱", "丹", "绛")
ProbeName = Literal[
    "connection",
    "multimodal",
    "structured_output",
    "json_object",
    "tool_calling",
    "reasoning_control",
]


class ModelCapabilityProbeStatus(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    ERROR = "error"
    SKIPPED = "skipped"


class ModelCapabilityProbeOutcome(StrictModel):
    name: ProbeName
    status: ModelCapabilityProbeStatus
    response: str | None = None
    error: str | None = None
    error_code: str | None = None
    error_category: str | None = None
    provider_code: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def supported(self) -> bool:
        return self.status == ModelCapabilityProbeStatus.SUPPORTED


class ModelCapabilityProbeReport(StrictModel):
    valid: bool
    outcomes: tuple[ModelCapabilityProbeOutcome, ...]
    successful_probes: tuple[ProbeName, ...] = ()
    failed_probes: tuple[ProbeName, ...] = ()
    skipped_probes: tuple[ProbeName, ...] = ()
    supports_text: bool = False
    supports_multimodal: bool = False
    supports_structured_output: bool = False
    supports_json_object: bool = False
    supports_tools: bool = False

    def outcome(self, name: ProbeName) -> ModelCapabilityProbeOutcome:
        return next(value for value in self.outcomes if value.name == name)


async def probe_model_capabilities(
    provider: ModelProvider,
    *,
    model_binding: str,
    max_output_tokens: int = 128,
    timeout_seconds: float = 30,
) -> ModelCapabilityProbeReport:
    """Run independent semantic probes through one configured provider.

    A portable reasoning-disable parameter does not exist, so reasoning control
    is reported as skipped. Provider-specific reasoning negotiation belongs in
    the adapter and must not determine whether the route itself is usable.
    """

    run_id = new_id("model_capability_probe")
    executable = await asyncio.gather(
        _bounded_probe(
            "connection",
            _probe_connection(
                provider,
                model_binding=model_binding,
                run_id=run_id,
                max_output_tokens=max_output_tokens,
            ),
            timeout_seconds=timeout_seconds,
        ),
        _bounded_probe(
            "multimodal",
            _probe_multimodal(
                provider,
                model_binding=model_binding,
                run_id=run_id,
                max_output_tokens=max_output_tokens,
            ),
            timeout_seconds=timeout_seconds,
        ),
        _bounded_probe(
            "structured_output",
            _probe_structured_output(
                provider,
                model_binding=model_binding,
                run_id=run_id,
                max_output_tokens=max_output_tokens,
            ),
            timeout_seconds=timeout_seconds,
        ),
        _bounded_probe(
            "json_object",
            _probe_json_object(
                provider,
                model_binding=model_binding,
                run_id=run_id,
                max_output_tokens=max_output_tokens,
            ),
            timeout_seconds=timeout_seconds,
        ),
        _bounded_probe(
            "tool_calling",
            _probe_tool_calling(
                provider,
                model_binding=model_binding,
                run_id=run_id,
                max_output_tokens=max_output_tokens,
            ),
            timeout_seconds=timeout_seconds,
        ),
    )
    outcomes = (
        *executable,
        ModelCapabilityProbeOutcome(
            name="reasoning_control",
            status=ModelCapabilityProbeStatus.SKIPPED,
            metadata={
                "reason": "no_portable_reasoning_disable_control",
                "auxiliary_request_strategy": "omit",
            },
        ),
    )
    successful = tuple(value.name for value in outcomes if value.supported)
    skipped = tuple(
        value.name
        for value in outcomes
        if value.status == ModelCapabilityProbeStatus.SKIPPED
    )
    failed = tuple(
        value.name
        for value in outcomes
        if value.status
        in {ModelCapabilityProbeStatus.ERROR, ModelCapabilityProbeStatus.UNSUPPORTED}
    )
    connection = next(value for value in outcomes if value.name == "connection")
    return ModelCapabilityProbeReport(
        valid=bool(successful),
        outcomes=outcomes,
        successful_probes=successful,
        failed_probes=failed,
        skipped_probes=skipped,
        supports_text=(
            connection.supported and bool(connection.metadata.get("has_text"))
        ),
        supports_multimodal="multimodal" in successful,
        supports_structured_output="structured_output" in successful,
        supports_json_object="json_object" in successful,
        supports_tools="tool_calling" in successful,
    )


async def probe_model_connection(
    provider: ModelProvider,
    *,
    model_binding: str,
    max_output_tokens: int = 128,
    timeout_seconds: float = 30,
    prompt: str = "Reply with OK only.",
) -> ModelCapabilityProbeOutcome:
    """Probe one exact provider configuration with a minimal text request.

    Hosts use this to negotiate non-portable wire controls before constructing
    the provider that runs the broader semantic capability suite. The outcome
    records whether the provider emitted text and/or reasoning so a host can
    distinguish an accepted disable control from one that was merely ignored.
    """

    return await _bounded_probe(
        "connection",
        _probe_connection(
            provider,
            model_binding=model_binding,
            run_id=new_id("model_capability_probe"),
            max_output_tokens=max_output_tokens,
            prompt=prompt,
        ),
        timeout_seconds=timeout_seconds,
    )


async def probe_model_json_object(
    provider: ModelProvider,
    *,
    model_binding: str,
    max_output_tokens: int = 128,
    timeout_seconds: float = 30,
) -> ModelCapabilityProbeOutcome:
    """Probe the JSON-object dialect used by Sage auxiliary model calls."""

    return await _bounded_probe(
        "json_object",
        _probe_json_object(
            provider,
            model_binding=model_binding,
            run_id=new_id("model_capability_probe"),
            max_output_tokens=max_output_tokens,
        ),
        timeout_seconds=timeout_seconds,
    )


async def probe_model_tool_calling(
    provider: ModelProvider,
    *,
    model_binding: str,
    max_output_tokens: int = 128,
    timeout_seconds: float = 30,
) -> ModelCapabilityProbeOutcome:
    """Probe the exact required-Tool request shape used for combinations."""

    return await _bounded_probe(
        "tool_calling",
        _probe_tool_calling(
            provider,
            model_binding=model_binding,
            run_id=new_id("model_capability_probe"),
            max_output_tokens=max_output_tokens,
        ),
        timeout_seconds=timeout_seconds,
    )


async def _bounded_probe(
    name: ProbeName,
    probe: Awaitable[ModelCapabilityProbeOutcome],
    *,
    timeout_seconds: float,
) -> ModelCapabilityProbeOutcome:
    try:
        return await asyncio.wait_for(probe, timeout=max(0.001, timeout_seconds))
    except TimeoutError:
        return ModelCapabilityProbeOutcome(
            name=name,
            status=ModelCapabilityProbeStatus.ERROR,
            error=f"capability probe timed out after {timeout_seconds:g} seconds",
            error_code="model.probe_timeout",
        )


async def _probe_connection(
    provider: ModelProvider,
    *,
    model_binding: str,
    run_id: str,
    max_output_tokens: int,
    prompt: str = "Reply with OK only.",
) -> ModelCapabilityProbeOutcome:
    response, error = await _request(
        provider,
        ModelRequest(
            request_id=new_id("model_probe_connection"),
            run_id=run_id,
            model_binding=model_binding,
            messages=(
                ModelMessage(
                    role="user",
                    content=(TextBlock(text=prompt),),
                ),
            ),
            max_output_tokens=max_output_tokens,
        ),
        name="connection",
    )
    if error is not None:
        return error
    assert response is not None
    text = response.text.strip()
    reasoning = response.reasoning.strip()
    semantic = text or reasoning
    if not semantic and not response.tool_calls:
        return _unsupported("connection", "provider returned no semantic output")
    return _supported(
        "connection",
        semantic,
        metadata={
            "has_text": bool(text),
            "has_reasoning": bool(reasoning),
            "reasoning_tokens": response.usage.reasoning_tokens,
        },
    )


async def _probe_multimodal(
    provider: ModelProvider,
    *,
    model_binding: str,
    run_id: str,
    max_output_tokens: int,
) -> ModelCapabilityProbeOutcome:
    response, error = await _request(
        provider,
        ModelRequest(
            request_id=new_id("model_probe_multimodal"),
            run_id=run_id,
            model_binding=model_binding,
            messages=(
                ModelMessage(
                    role="user",
                    content=(
                        TextBlock(
                            text=(
                                "What is the main color of this image? Reply briefly."
                            )
                        ),
                        ImageBlock(
                            uri=_PROBE_IMAGE,
                            mime_type="image/png",
                            alt="capability probe",
                        ),
                    ),
                ),
            ),
            max_output_tokens=max_output_tokens,
        ),
        name="multimodal",
    )
    if error is not None:
        return error
    assert response is not None
    text = response.text.strip()
    if not any(marker in text.lower() for marker in _RED_MARKERS):
        return _unsupported(
            "multimodal",
            "response did not identify the probe image",
            response=text,
        )
    return _supported("multimodal", text)


async def _probe_structured_output(
    provider: ModelProvider,
    *,
    model_binding: str,
    run_id: str,
    max_output_tokens: int,
) -> ModelCapabilityProbeOutcome:
    response, error = await _request(
        provider,
        ModelRequest(
            request_id=new_id("model_probe_structured"),
            run_id=run_id,
            model_binding=model_binding,
            messages=(
                ModelMessage(
                    role="user",
                    content=(
                        TextBlock(
                            text=(
                                'Return a JSON object with the single field "ok" '
                                "set to true."
                            )
                        ),
                    ),
                ),
            ),
            max_output_tokens=max_output_tokens,
            response_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean", "const": True}},
                "required": ["ok"],
                "additionalProperties": False,
            },
        ),
        name="structured_output",
    )
    if error is not None:
        return error
    assert response is not None
    text = response.text.strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return _unsupported(
            "structured_output",
            "response was not valid JSON",
            response=text,
        )
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        return _unsupported(
            "structured_output",
            "response did not match the probe schema",
            response=text,
        )
    return _supported("structured_output", text)


async def _probe_json_object(
    provider: ModelProvider,
    *,
    model_binding: str,
    run_id: str,
    max_output_tokens: int,
) -> ModelCapabilityProbeOutcome:
    response, error = await _request(
        provider,
        ModelRequest(
            request_id=new_id("model_probe_json_object"),
            run_id=run_id,
            model_binding=model_binding,
            messages=(
                ModelMessage(
                    role="user",
                    content=(
                        TextBlock(
                            text=(
                                'Return a JSON object with the single field "ok" '
                                "set to true."
                            )
                        ),
                    ),
                ),
            ),
            max_output_tokens=max_output_tokens,
            response_format="json_object",
            tool_choice="none",
        ),
        name="json_object",
    )
    if error is not None:
        return error
    assert response is not None
    text = response.text.strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return _unsupported(
            "json_object",
            "response was not valid JSON",
            response=text,
        )
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        return _unsupported(
            "json_object",
            "response did not match the requested object",
            response=text,
        )
    return _supported(
        "json_object",
        text,
        metadata={
            "has_text": bool(text),
            "has_reasoning": bool(response.reasoning.strip()),
        },
    )


async def _probe_tool_calling(
    provider: ModelProvider,
    *,
    model_binding: str,
    run_id: str,
    max_output_tokens: int,
) -> ModelCapabilityProbeOutcome:
    response, error = await _request(
        provider,
        ModelRequest(
            request_id=new_id("model_probe_tools"),
            run_id=run_id,
            model_binding=model_binding,
            messages=(
                ModelMessage(
                    role="user",
                    content=(
                        TextBlock(text="Call sage_capability_probe with value OK."),
                    ),
                ),
            ),
            tools=(
                ModelToolDefinition(
                    name="sage_capability_probe",
                    description="Report the requested probe value.",
                    input_schema={
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                    strict=True,
                ),
            ),
            tool_choice="required",
            max_output_tokens=max_output_tokens,
        ),
        name="tool_calling",
    )
    if error is not None:
        return error
    assert response is not None
    if not any(call.name == "sage_capability_probe" for call in response.tool_calls):
        return _unsupported(
            "tool_calling",
            "provider did not return the required probe tool call",
            response=response.text.strip(),
        )
    return _supported("tool_calling", response.text.strip())


async def _request(
    provider: ModelProvider,
    request: ModelRequest,
    *,
    name: ProbeName,
) -> tuple[ModelResponse | None, ModelCapabilityProbeOutcome | None]:
    completed = None
    try:
        async for event in provider.stream(request):
            if event.kind == ModelEventKind.COMPLETED:
                completed = event.response
    except SageV2Error as exc:
        return None, ModelCapabilityProbeOutcome(
            name=name,
            status=ModelCapabilityProbeStatus.ERROR,
            error=exc.info.message,
            error_code=exc.info.code,
            error_category=exc.info.category.value,
            provider_code=exc.info.provider_code,
        )
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        return None, ModelCapabilityProbeOutcome(
            name=name,
            status=ModelCapabilityProbeStatus.ERROR,
            error=str(exc),
            error_code=type(exc).__name__,
            provider_code=str(status) if status is not None else None,
        )
    if completed is None:
        return None, ModelCapabilityProbeOutcome(
            name=name,
            status=ModelCapabilityProbeStatus.ERROR,
            error="provider stream ended without a completed response",
            error_code="model.probe_incomplete",
        )
    return completed, None


def _supported(
    name: ProbeName,
    response: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> ModelCapabilityProbeOutcome:
    return ModelCapabilityProbeOutcome(
        name=name,
        status=ModelCapabilityProbeStatus.SUPPORTED,
        response=response[:1_000] if response else None,
        metadata=metadata or {},
    )


def _unsupported(
    name: ProbeName,
    error: str,
    *,
    response: str | None = None,
) -> ModelCapabilityProbeOutcome:
    return ModelCapabilityProbeOutcome(
        name=name,
        status=ModelCapabilityProbeStatus.UNSUPPORTED,
        response=response[:1_000] if response else None,
        error=error,
    )
