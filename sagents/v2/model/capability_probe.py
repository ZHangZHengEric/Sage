"""Reusable, provider-backed model capability probes.

The suite deliberately exercises the configured ``ModelProvider`` rather than
reconstructing provider wire payloads. Each probe is independent: one rejected
parameter combination is evidence about that capability only, not evidence
that the whole model route is invalid.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import ImageBlock, TextBlock
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolDefinition,
)
from sagents.v2.model.capability_contracts import (
    ModelCapabilityProbeOutcome,
    ModelCapabilityProbeReport,
    ModelCapabilityProbeRequest,
    ModelCapabilityProbeStatus,
    ModelCapabilityProfile,
    ProbeName,
)
from sagents.v2.model.provider import ModelProvider


_PROBE_IMAGE = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAIAAAAC64paAAAAG0lEQVR4nGP8z0A+"
    "YKJA76jmUc2jmkc1U0EzACKcASc1hNCeAAAAAElFTkSuQmCC"
)
_RED_MARKERS = ("red", "红色", "红", "赤", "绯", "朱", "丹", "绛")
async def negotiate_model_output_limit(
    provider: ModelProvider,
    request: ModelCapabilityProbeRequest,
) -> tuple[int, ModelCapabilityProbeOutcome]:
    """Find one accepted output budget without changing wire protocols."""

    candidates = (request.max_output_tokens,) + tuple(
        value
        for value in request.output_token_fallbacks
        if value < request.max_output_tokens
    )
    last: ModelCapabilityProbeOutcome | None = None
    for candidate in candidates:
        last = await probe_model_connection(
            provider,
            model_binding=request.model_binding,
            max_output_tokens=candidate,
            timeout_seconds=request.timeout_seconds,
        )
        if last.supported:
            return candidate, last
        if str(last.provider_code or "") not in {"400", "422"}:
            break
    assert last is not None
    raise SageV2Error(
        RuntimeErrorInfo(
            code="model.capability_probe_all_failed",
            category=ErrorCategory.VALIDATION,
            message="model connection and request dialect negotiation failed",
            safe_to_resume=True,
            metadata={"connection": last.model_dump(mode="json")},
        )
    )


async def probe_model_reasoning_controls(
    *,
    base_provider: ModelProvider,
    provider_factory: Callable[[str, str | None], ModelProvider],
    report: ModelCapabilityProbeReport,
    request: ModelCapabilityProbeRequest,
    max_output_tokens: int,
    disable_strategies: tuple[str, ...],
    effort_strategies: tuple[str, ...],
) -> tuple[ModelCapabilityProbeOutcome, dict[str, Any]]:
    """Probe plugin-declared reasoning variants and select one exact strategy."""

    prompt = "Think carefully about 17 multiplied by 19, then reply with the number only."
    omit = await probe_model_connection(
        base_provider,
        model_binding=request.model_binding,
        max_output_tokens=max_output_tokens,
        timeout_seconds=request.timeout_seconds,
        prompt=prompt,
    )
    omit_has_reasoning = bool(omit.metadata.get("has_reasoning"))
    disable_outcomes = {"omit": omit.model_dump(mode="json")}
    disable_strategy = "omit"
    selected_json = report.outcome("json_object")
    if omit.supported and omit_has_reasoning:
        for strategy in disable_strategies:
            if strategy == "omit":
                continue
            candidate = provider_factory(strategy, None)
            outcome = await probe_model_connection(
                candidate,
                model_binding=request.model_binding,
                max_output_tokens=max_output_tokens,
                timeout_seconds=request.timeout_seconds,
                prompt=prompt,
            )
            disable_outcomes[strategy] = outcome.model_dump(mode="json")
            if (
                outcome.supported
                and outcome.metadata.get("has_text") is True
                and outcome.metadata.get("has_reasoning") is not True
            ):
                json_outcome = await probe_model_json_object(
                    candidate,
                    model_binding=request.model_binding,
                    max_output_tokens=max_output_tokens,
                    timeout_seconds=request.timeout_seconds,
                )
                disable_outcomes[strategy]["auxiliary_json"] = (
                    json_outcome.model_dump(mode="json")
                )
                if json_outcome.supported:
                    disable_strategy = strategy
                    selected_json = json_outcome
                    break

    strategy_results: dict[str, dict[str, Any]] = {}
    for effort_strategy in effort_strategies:
        supported: list[str] = []
        text_only: list[str] = []
        unsupported: list[str] = []
        outcomes: dict[str, Any] = {}
        for effort in request.reasoning_efforts:
            candidate = provider_factory(effort_strategy, effort)
            text_outcome = await probe_model_connection(
                candidate,
                model_binding=request.model_binding,
                max_output_tokens=max_output_tokens,
                timeout_seconds=request.timeout_seconds,
                prompt=prompt,
            )
            values: dict[str, Any] = {
                "text": text_outcome.model_dump(mode="json")
            }
            observed = bool(
                text_outcome.metadata.get("has_reasoning")
                or text_outcome.metadata.get("reasoning_tokens")
            )
            text_supported = text_outcome.supported and (
                effort_strategy != "chat_template_reasoning_effort" or observed
            )
            if text_supported:
                text_only.append(effort)
            tool_outcome = None
            if text_supported and report.supports_tools:
                tool_outcome = await probe_model_tool_calling(
                    candidate,
                    model_binding=request.model_binding,
                    max_output_tokens=max_output_tokens,
                    timeout_seconds=request.timeout_seconds,
                )
                values["with_tools"] = tool_outcome.model_dump(mode="json")
            runtime_supported = text_supported and (
                not report.supports_tools
                or (tool_outcome is not None and tool_outcome.supported)
            )
            (supported if runtime_supported else unsupported).append(effort)
            outcomes[effort] = values
        strategy_results[effort_strategy] = {
            "supported": supported,
            "text_only": text_only,
            "unsupported": unsupported,
            "outcomes": outcomes,
        }

    effort_strategy = effort_strategies[0] if effort_strategies else "reasoning_effort"
    if "chat_template_reasoning_effort" in strategy_results:
        top = strategy_results.get("reasoning_effort", {}).get("supported", [])
        nested = strategy_results["chat_template_reasoning_effort"]["supported"]
        if nested and (
            not top
            or (
                len(top) == len(request.reasoning_efforts)
                and len(nested) < len(top)
            )
        ):
            effort_strategy = "chat_template_reasoning_effort"
    selected = strategy_results.get(
        effort_strategy,
        {"supported": [], "text_only": [], "unsupported": [], "outcomes": {}},
    )
    explicit_disable = disable_strategy != "omit"
    if omit_has_reasoning:
        behavior = "controllable" if explicit_disable else "always"
    else:
        behavior = "controllable" if selected["supported"] else "none"
    supported_control = explicit_disable or bool(selected["supported"])
    metadata = {
        "behavior": behavior,
        "disable_strategy": disable_strategy,
        "effort_strategy": effort_strategy,
        "supported_efforts": selected["supported"],
        "text_only_efforts": selected["text_only"],
        "unsupported_efforts": selected["unsupported"],
        "disable_outcomes": disable_outcomes,
        "effort_outcomes": selected["outcomes"],
        "effort_strategy_outcomes": strategy_results,
        "auxiliary_json": selected_json.model_dump(mode="json"),
    }
    return (
        ModelCapabilityProbeOutcome(
            name="reasoning_control",
            status=(
                ModelCapabilityProbeStatus.SUPPORTED
                if supported_control
                else ModelCapabilityProbeStatus.UNSUPPORTED
            ),
            error=None if supported_control else "no supported reasoning control",
            metadata=metadata,
        ),
        metadata,
    )


def model_capability_profile(
    *,
    plugin_id: str,
    plugin_version: str,
    protocol: str,
    request: ModelCapabilityProbeRequest,
    effective_max_output_tokens: int,
    report: ModelCapabilityProbeReport,
    reasoning: ModelCapabilityProbeOutcome,
    invocation_strategy: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
) -> ModelCapabilityProfile:
    """Build the standard persisted profile returned by every model plugin."""

    outcomes = tuple(
        reasoning if value.name == "reasoning_control" else value
        for value in report.outcomes
    )
    return ModelCapabilityProfile(
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        protocol=protocol,
        route_fingerprint=request.route_fingerprint,
        effective_max_output_tokens=effective_max_output_tokens,
        outcomes=outcomes,
        invocation_strategy=dict(invocation_strategy),
        metadata=dict(metadata or {}),
    )


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


async def probe_model_multimodal(
    provider: ModelProvider,
    *,
    model_binding: str,
    max_output_tokens: int = 128,
    timeout_seconds: float = 30,
) -> ModelCapabilityProbeOutcome:
    """Probe one plugin-owned multimodal request shape."""

    return await _bounded_probe(
        "multimodal",
        _probe_multimodal(
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
        diagnostic = _compact_probe_error(exc.info.message, name=name)
        return None, ModelCapabilityProbeOutcome(
            name=name,
            status=ModelCapabilityProbeStatus.ERROR,
            error=exc.info.message,
            error_code=exc.info.code,
            error_category=exc.info.category.value,
            provider_code=exc.info.provider_code,
            metadata={"diagnostic_error": diagnostic},
        )
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        message = str(exc)
        return None, ModelCapabilityProbeOutcome(
            name=name,
            status=ModelCapabilityProbeStatus.ERROR,
            error=message,
            error_code=type(exc).__name__,
            provider_code=str(status) if status is not None else None,
            metadata={
                "diagnostic_error": _compact_probe_error(message, name=name)
            },
        )
    if completed is None:
        return None, ModelCapabilityProbeOutcome(
            name=name,
            status=ModelCapabilityProbeStatus.ERROR,
            error="provider stream ended without a completed response",
            error_code="model.probe_incomplete",
        )
    return completed, None


def _compact_probe_error(message: str, *, name: ProbeName) -> str:
    """Compact a provider error without inferring another wire protocol."""

    del name
    compact = " ".join(message.split())
    return compact[:1_000]


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
