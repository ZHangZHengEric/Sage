from __future__ import annotations

import inspect
import re
from typing import Any

from pydantic import SecretStr

from app.desktop_v2.backend.catalog import (
    DesktopModelCompatibilityProfile,
    DesktopModelProviderRecord,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.model import (
    ModelCapabilityProbeRequest,
    probe_model_capabilities,
    probe_model_connection,
    probe_model_json_object,
    probe_model_tool_calling,
)
from sagents.v2.model.plugins.openai_compatible import (
    default_chat_completion_token_field,
)
from sagents.v2.package.manifest.models import (
    ModelCapabilityDeclaration,
    ModelLimits,
    ModelRequestDefaults,
    ModelRoute,
)
from sagents.v2.runtime.credentials import CredentialMaterial


_IMAGE_VALIDATION_FIELD_RE = re.compile(
    r"ResponseInputImageParam['\"],\s*['\"]([^'\"]+)['\"]\).*?"
    r"['\"]msg['\"]:\s*['\"]([^'\"]+)['\"]",
    flags=re.DOTALL,
)


def _probe_diagnostic(
    *, protocol: str, name: str, raw_error: str, fallback: str
) -> str:
    """Describe a failure only in terms of the configured wire protocol."""

    if protocol == "openai-chat-completions" and name == "multimodal":
        match = _IMAGE_VALIDATION_FIELD_RE.search(raw_error)
        if match is not None:
            return (
                "openai-chat-completions image_url probe rejected during provider "
                f"validation (image_url.{match.group(1)}: {match.group(2)})"
            )
    return fallback


async def probe_model_provider_capabilities(
    provider: DesktopModelProviderRecord,
    *,
    provider_factory,
    compatibility_fingerprint,
    output_token_fallbacks: tuple[int, ...],
    reasoning_disable_extras: dict[str, dict[str, Any]],
    reasoning_efforts: tuple[str, ...],
) -> dict[str, Any]:
    credential = CredentialMaterial(
        credential_id="desktop_model_probe",
        secret=SecretStr(provider.api_key),
        source="desktop-settings",
    )
    created_providers: list[Any] = []

    def create_probe_provider(
        *,
        max_output_tokens: int,
        maximum_field: str | None = None,
        reasoning_effort: str | None = None,
        request_extra: dict[str, Any] | None = None,
    ):
        extra = dict(request_extra or {})
        if (
            provider.protocol == "openai-chat-completions"
            and maximum_field is not None
        ):
            extra["max_output_tokens_field"] = maximum_field
        route = ModelRoute(
            provider=provider.protocol,
            base_url=provider.base_url,
            credential="desktop_model_probe",
            model=provider.model,
            request=ModelRequestDefaults(
                max_output_tokens=max_output_tokens,
                temperature=provider.temperature,
                top_p=provider.top_p,
                reasoning_effort=reasoning_effort,
                extra=extra,
            ),
            limits=ModelLimits(
                context_window=provider.max_model_len,
                max_output_tokens=max_output_tokens,
            ),
            capabilities=ModelCapabilityDeclaration(
                multimodal=True,
                structured_output=True,
                tool_calling=True,
                reasoning=True,
                parallel_tool_calls=True,
            ),
        )
        model_provider = provider_factory(
            route,
            credential,
            provider_instance_id=provider.id,
        )
        created_providers.append(model_provider)
        return model_provider

    def serialize_outcome(outcome) -> dict[str, Any]:
        value = {
            "supported": outcome.supported,
            **outcome.model_dump(
                mode="json",
                exclude={"name", "status"},
                exclude_none=True,
                exclude_defaults=True,
            ),
            "status": outcome.status.value,
        }

        if not outcome.supported and outcome.error:
            metadata = dict(value.get("metadata") or {})
            fallback = str(metadata.get("diagnostic_error") or outcome.error)[:1_000]
            metadata["diagnostic_error"] = _probe_diagnostic(
                protocol=provider.protocol,
                name=outcome.name,
                raw_error=outcome.error,
                fallback=fallback,
            )
            metadata["protocol"] = provider.protocol
            value["metadata"] = metadata
        return value

    def diagnostic_outcome(outcome: dict[str, Any]) -> dict[str, str]:
        metadata = outcome.get("metadata")
        diagnostic = (
            metadata.get("diagnostic_error") if isinstance(metadata, dict) else None
        )
        values = {
            "status": outcome.get("status"),
            "provider_code": outcome.get("provider_code"),
            "error_code": outcome.get("error_code"),
            "error_category": outcome.get("error_category"),
            "diagnostic_error": diagnostic or outcome.get("error"),
        }
        return {
            key: str(value)[:1_000]
            for key, value in values.items()
            if value is not None and str(value)
        }

    candidates = (provider.max_tokens,) + tuple(
        value for value in output_token_fallbacks if value < provider.max_tokens
    )
    negotiation_provider = create_probe_provider(
        max_output_tokens=provider.max_tokens
    )
    connection_outcome = None
    effective_max_output_tokens = provider.max_tokens
    try:
        plugin_probe = getattr(negotiation_provider, "probe_capabilities", None)
        if callable(plugin_probe):
            route_fingerprint = compatibility_fingerprint(provider)
            plugin_profile = await plugin_probe(
                ModelCapabilityProbeRequest(
                    model_binding=provider.id,
                    route_fingerprint=route_fingerprint,
                    max_output_tokens=provider.max_tokens,
                    output_token_fallbacks=output_token_fallbacks,
                    reasoning_efforts=reasoning_efforts,
                )
            )
            probes = {
                outcome.name: serialize_outcome(outcome)
                for outcome in plugin_profile.outcomes
            }
            reasoning_outcome = plugin_profile.outcome("reasoning_control")
            reasoning_control = probes["reasoning_control"]
            reasoning_control.update(reasoning_outcome.metadata)
            reasoning_control["probed"] = True
            probes["reasoning_control"] = reasoning_control
            successful_probes = [
                outcome.name
                for outcome in plugin_profile.outcomes
                if outcome.supported
            ]
            failed_probes = [
                outcome.name
                for outcome in plugin_profile.outcomes
                if outcome.status.value in {"error", "unsupported"}
            ]
            skipped_probes = [
                outcome.name
                for outcome in plugin_profile.outcomes
                if outcome.status.value == "skipped"
            ]
            strategy = plugin_profile.invocation_strategy
            compatibility_profile = DesktopModelCompatibilityProfile(
                route_fingerprint=route_fingerprint,
                max_output_tokens_field=strategy.get("max_output_tokens_field"),
                effective_max_output_tokens=(
                    plugin_profile.effective_max_output_tokens
                ),
                reasoning_disable_strategy=strategy.get(
                    "reasoning_disable_strategy", "omit"
                ),
                reasoning_behavior=strategy.get("reasoning_behavior", "none"),
                reasoning_effort_strategy=strategy.get(
                    "reasoning_effort_strategy", "reasoning_effort"
                ),
                supported_reasoning_efforts=tuple(
                    strategy.get("supported_reasoning_efforts", ())
                ),
                text_only_reasoning_efforts=tuple(
                    strategy.get("text_only_reasoning_efforts", ())
                ),
                unsupported_reasoning_efforts=tuple(
                    strategy.get("unsupported_reasoning_efforts", ())
                ),
                supports_json_object=bool(
                    strategy.get("supports_json_object", False)
                ),
                auxiliary_json_compatible=bool(
                    strategy.get("auxiliary_json_compatible", False)
                ),
                successful_probes=tuple(successful_probes),
                failed_probes=tuple(failed_probes),
                probe_diagnostics={
                    name: diagnostic_outcome(outcome)
                    for name, outcome in probes.items()
                    if outcome.get("supported") is not True
                    and outcome.get("status") != "supported"
                },
                plugin_profile=plugin_profile,
            )
            return {
                "valid": plugin_profile.supports("connection"),
                "successful_probes": successful_probes,
                "failed_probes": failed_probes,
                "skipped_probes": skipped_probes,
                "connection": probes["connection"],
                "requested_max_output_tokens": provider.max_tokens,
                "effective_max_output_tokens": (
                    plugin_profile.effective_max_output_tokens
                ),
                "supports_multimodal": plugin_profile.supports("multimodal"),
                "supports_structured_output": plugin_profile.supports(
                    "structured_output"
                ),
                "supports_json_object": plugin_profile.supports("json_object"),
                "supports_tool_calling": plugin_profile.supports("tool_calling"),
                "multimodal": probes["multimodal"],
                "structured_output": probes["structured_output"],
                "json_object": probes["json_object"],
                "tool_calling": probes["tool_calling"],
                "reasoning_control": reasoning_control,
                "compatibility_profile": compatibility_profile.model_dump(
                    mode="json"
                ),
                "probes": probes,
                "protocol": provider.protocol,
                "model": provider.model,
                "base_url": provider.base_url,
            }

        for candidate in candidates:
            connection_outcome = await probe_model_connection(
                negotiation_provider,
                model_binding=provider.id,
                max_output_tokens=candidate,
            )
            if connection_outcome.supported:
                effective_max_output_tokens = candidate
                break
            if str(connection_outcome.provider_code or "") not in {"400", "422"}:
                break
        if connection_outcome is None or not connection_outcome.supported:
            details = (
                serialize_outcome(connection_outcome)
                if connection_outcome is not None
                else {}
            )
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="model.capability_probe_all_failed",
                    category=ErrorCategory.VALIDATION,
                    message="model connection and request dialect negotiation failed",
                    safe_to_resume=True,
                    metadata={
                        "connection": details,
                        "probes": {"connection": details},
                    },
                )
            )

        resolved_maximum_field = None
        if provider.protocol == "openai-chat-completions":
            resolved_maximum_field = getattr(
                negotiation_provider, "resolved_max_output_tokens_field", None
            ) or default_chat_completion_token_field(provider.model)

        model_provider = create_probe_provider(
            max_output_tokens=effective_max_output_tokens,
            maximum_field=resolved_maximum_field,
        )
        report = await probe_model_capabilities(
            model_provider,
            model_binding=provider.id,
            max_output_tokens=effective_max_output_tokens,
        )
        probes = {
            outcome.name: serialize_outcome(outcome) for outcome in report.outcomes
        }
        if not report.valid:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="model.capability_probe_all_failed",
                    category=ErrorCategory.VALIDATION,
                    message="all model capability probes failed",
                    safe_to_resume=True,
                    metadata={"probes": probes},
                )
            )

        reasoning_prompt = (
            "Think carefully about 17 multiplied by 19, then reply with the "
            "number only."
        )
        omit_outcome = await probe_model_connection(
            model_provider,
            model_binding=provider.id,
            max_output_tokens=effective_max_output_tokens,
            prompt=reasoning_prompt,
        )
        disable_strategy = "omit"
        disable_outcomes = {"omit": serialize_outcome(omit_outcome)}
        omit_has_reasoning = bool(omit_outcome.metadata.get("has_reasoning"))
        selected_auxiliary_json_outcome = report.outcome("json_object")
        if omit_outcome.supported and omit_has_reasoning:
            for strategy, extra in reasoning_disable_extras.items():
                if strategy == "omit":
                    continue
                candidate_provider = create_probe_provider(
                    max_output_tokens=effective_max_output_tokens,
                    maximum_field=resolved_maximum_field,
                    request_extra=extra,
                )
                outcome = await probe_model_connection(
                    candidate_provider,
                    model_binding=provider.id,
                    max_output_tokens=effective_max_output_tokens,
                    prompt=reasoning_prompt,
                )
                disable_outcomes[strategy] = serialize_outcome(outcome)
                if (
                    outcome.supported
                    and outcome.metadata.get("has_text") is True
                    and outcome.metadata.get("has_reasoning") is not True
                ):
                    json_outcome = await probe_model_json_object(
                        candidate_provider,
                        model_binding=provider.id,
                        max_output_tokens=effective_max_output_tokens,
                    )
                    disable_outcomes[strategy]["auxiliary_json"] = (
                        serialize_outcome(json_outcome)
                    )
                    if json_outcome.supported:
                        disable_strategy = strategy
                        selected_auxiliary_json_outcome = json_outcome
                        break

        effort_strategy_results: dict[str, dict[str, Any]] = {}
        for effort_strategy in (
            "reasoning_effort",
            "chat_template_reasoning_effort",
        ):
            reasoning_outcomes: dict[str, dict[str, Any]] = {}
            supported_reasoning_efforts: list[str] = []
            text_only_reasoning_efforts: list[str] = []
            unsupported_reasoning_efforts: list[str] = []
            for effort in reasoning_efforts:
                nested_strategy = (
                    effort_strategy == "chat_template_reasoning_effort"
                )
                effort_provider = create_probe_provider(
                    max_output_tokens=effective_max_output_tokens,
                    maximum_field=resolved_maximum_field,
                    reasoning_effort=None if nested_strategy else effort,
                    request_extra=(
                        {
                            "chat_template_kwargs": {
                                "thinking": True,
                                "reasoning_effort": effort,
                            }
                        }
                        if nested_strategy
                        else None
                    ),
                )
                outcome = await probe_model_connection(
                    effort_provider,
                    model_binding=provider.id,
                    max_output_tokens=effective_max_output_tokens,
                    prompt=reasoning_prompt,
                )
                text_result = serialize_outcome(outcome)
                reasoning_outcomes[effort] = {"text": text_result}
                reasoning_observed = bool(
                    outcome.metadata.get("has_reasoning")
                    or outcome.metadata.get("reasoning_tokens")
                )
                text_supported = outcome.supported and (
                    not nested_strategy or reasoning_observed
                )
                if text_supported:
                    text_only_reasoning_efforts.append(effort)
                tool_outcome = None
                if text_supported and report.supports_tools:
                    tool_outcome = await probe_model_tool_calling(
                        effort_provider,
                        model_binding=provider.id,
                        max_output_tokens=effective_max_output_tokens,
                    )
                    reasoning_outcomes[effort]["with_tools"] = serialize_outcome(
                        tool_outcome
                    )
                runtime_supported = text_supported and (
                    not report.supports_tools
                    or (tool_outcome is not None and tool_outcome.supported)
                )
                (
                    supported_reasoning_efforts
                    if runtime_supported
                    else unsupported_reasoning_efforts
                ).append(effort)
            effort_strategy_results[effort_strategy] = {
                "supported": supported_reasoning_efforts,
                "text_only": text_only_reasoning_efforts,
                "unsupported": unsupported_reasoning_efforts,
                "outcomes": reasoning_outcomes,
            }

        top_level_efforts = effort_strategy_results["reasoning_effort"]
        nested_efforts = effort_strategy_results["chat_template_reasoning_effort"]
        top_supported = top_level_efforts["supported"]
        nested_supported = nested_efforts["supported"]
        reasoning_effort_strategy = "reasoning_effort"
        if nested_supported and (
            not top_supported
            or (
                len(top_supported) == len(reasoning_efforts)
                and len(nested_supported) < len(top_supported)
            )
        ):
            reasoning_effort_strategy = "chat_template_reasoning_effort"
        selected_efforts = effort_strategy_results[reasoning_effort_strategy]
        supported_reasoning_efforts = selected_efforts["supported"]
        text_only_reasoning_efforts = selected_efforts["text_only"]
        unsupported_reasoning_efforts = selected_efforts["unsupported"]
        reasoning_outcomes = selected_efforts["outcomes"]

        explicit_disable = disable_strategy != "omit"
        if omit_has_reasoning:
            reasoning_behavior = "controllable" if explicit_disable else "always"
        else:
            reasoning_behavior = (
                "controllable" if supported_reasoning_efforts else "none"
            )
        reasoning_control = {
            "supported": explicit_disable or bool(supported_reasoning_efforts),
            "status": "supported"
            if explicit_disable or supported_reasoning_efforts
            else "unsupported",
            "probed": True,
            "behavior": reasoning_behavior,
            "disable_strategy": disable_strategy,
            "effort_strategy": reasoning_effort_strategy,
            "disable_outcomes": disable_outcomes,
            "supported_efforts": supported_reasoning_efforts,
            "text_only_efforts": text_only_reasoning_efforts,
            "unsupported_efforts": unsupported_reasoning_efforts,
            "effort_outcomes": reasoning_outcomes,
            "effort_strategy_outcomes": effort_strategy_results,
            "auxiliary_json": serialize_outcome(selected_auxiliary_json_outcome),
        }
        probes["reasoning_control"] = reasoning_control
        successful_probes = list(report.successful_probes)
        failed_probes = list(report.failed_probes)
        if reasoning_control["supported"]:
            successful_probes.append("reasoning_control")
        elif "reasoning_control" not in failed_probes:
            failed_probes.append("reasoning_control")
        compatibility_profile = DesktopModelCompatibilityProfile(
            route_fingerprint=compatibility_fingerprint(provider),
            max_output_tokens_field=resolved_maximum_field,
            effective_max_output_tokens=effective_max_output_tokens,
            reasoning_disable_strategy=disable_strategy,
            reasoning_behavior=reasoning_behavior,
            reasoning_effort_strategy=reasoning_effort_strategy,
            supported_reasoning_efforts=tuple(supported_reasoning_efforts),
            text_only_reasoning_efforts=tuple(text_only_reasoning_efforts),
            unsupported_reasoning_efforts=tuple(unsupported_reasoning_efforts),
            supports_json_object=report.supports_json_object,
            auxiliary_json_compatible=(selected_auxiliary_json_outcome.supported),
            successful_probes=tuple(successful_probes),
            failed_probes=tuple(failed_probes),
            probe_diagnostics={
                name: diagnostic_outcome(outcome)
                for name, outcome in probes.items()
                if outcome.get("supported") is not True
                and outcome.get("status") != "supported"
            },
        )
        return {
            "valid": True,
            "successful_probes": successful_probes,
            "failed_probes": failed_probes,
            "skipped_probes": [],
            "connection": probes["connection"],
            "requested_max_output_tokens": provider.max_tokens,
            "effective_max_output_tokens": effective_max_output_tokens,
            "supports_multimodal": report.supports_multimodal,
            "supports_structured_output": report.supports_structured_output,
            "supports_json_object": report.supports_json_object,
            "supports_tool_calling": report.supports_tools,
            "multimodal": probes["multimodal"],
            "structured_output": probes["structured_output"],
            "json_object": probes["json_object"],
            "tool_calling": probes["tool_calling"],
            "reasoning_control": reasoning_control,
            "compatibility_profile": compatibility_profile.model_dump(mode="json"),
            "probes": probes,
            "protocol": provider.protocol,
            "model": provider.model,
            "base_url": provider.base_url,
        }
    finally:
        closed_clients: set[int] = set()
        for value in created_providers:
            client = getattr(value, "raw_client", None)
            if client is None or id(client) in closed_clients:
                continue
            closed_clients.add(id(client))
            close = getattr(client, "aclose", None) or getattr(
                client, "close", None
            )
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
