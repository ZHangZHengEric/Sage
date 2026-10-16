"""Desktop model route translation and process-local provider reuse.

No Session, sandbox or plugin lifecycle is managed here. The host verifies
compatibility fingerprints before passing a profile, and retains its existing
concurrency budget for every cached provider.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from pydantic import SecretStr
from app.v2.desktop.backend.catalog import (
    DesktopModelCompatibilityProfile,
    DesktopModelProviderRecord,
)
from app.v2.desktop.backend.model_request_defaults import (
    build_llm_extra_body,
    is_openai_reasoning_model,
)
from app.v2.desktop.backend.runtime_config import _REASONING_DISABLE_EXTRAS
from sagents.v2.package.manifest.models import (
    ModelRoute,
    ModelRequestDefaults,
    ModelLimits,
    ModelCapabilityDeclaration,
)
from sagents.v2.model.middleware.concurrency import ModelConcurrencyBudget
from sagents.v2.model.protocols import create_registered_model_provider
from sagents.v2.runtime.credentials import CredentialMaterial


class DesktopModelProviders:
    def __init__(self, budget: ModelConcurrencyBudget) -> None:
        self.budget = budget
        self._providers: dict[tuple[Any, ...], Any] = {}

    def clear(self) -> None:
        self._providers.clear()

    @staticmethod
    def route(
        provider, agent, *, compatibility_profile=None, enable_thinking=None
    ) -> ModelRoute:
        deep_thinking, thinking_level = thinking_config(agent)
        if enable_thinking is not None:
            deep_thinking = enable_thinking
        request_extra: dict[str, Any] = {}
        plugin_profile = (
            compatibility_profile.plugin_profile
            if compatibility_profile is not None
            else None
        )
        legacy_profile = compatibility_profile if plugin_profile is None else None
        effective_max_output_tokens = effective_model_output_tokens(
            provider, compatibility_profile
        )
        reasoning_effort = effective_reasoning_effort(
            compatibility_profile,
            enabled=deep_thinking,
            requested=thinking_level,
            legacy=thinking_level if deep_thinking else None,
        )
        if legacy_profile is not None:
            if provider.protocol == "openai-chat-completions":
                request_extra["max_output_tokens_field"] = (
                    legacy_profile.max_output_tokens_field
                )
            request_extra.update(
                reasoning_effort_extra(
                    legacy_profile, enabled=True, requested=thinking_level
                )
                if deep_thinking
                else reasoning_disable_extra(legacy_profile.reasoning_disable_strategy)
            )
        elif enable_thinking is not None:
            if provider.protocol in {"openai-chat-completions", "openai-responses"}:
                request_extra["reasoning_parameter_fallback"] = enable_thinking is False
            # Minimal still reasons, and some gateways reject reasoning_effort.
            # Auxiliary OpenAI reasoning requests keep provider defaults;
            # vendor-specific controls are used only by the chat mapping.
            if provider.protocol == "openai-chat-completions" and (
                enable_thinking or not is_openai_reasoning_model(provider.model)
            ):
                request_extra.update(
                    build_llm_extra_body(
                        provider.model,
                        base_url=provider.base_url,
                        enable_thinking=enable_thinking,
                        thinking_level=thinking_level if enable_thinking else None,
                        default_off="minimal",
                    )
                )
        return ModelRoute(
            provider=provider.protocol,
            base_url=provider.base_url,
            credential="desktop_model",
            model=provider.model,
            request=ModelRequestDefaults(
                max_output_tokens=effective_max_output_tokens,
                temperature=provider.temperature,
                top_p=provider.top_p,
                reasoning_effort=reasoning_effort,
                extra=request_extra,
            ),
            limits=ModelLimits(
                context_window=provider.max_model_len,
                max_output_tokens=effective_max_output_tokens,
            ),
            capabilities=ModelCapabilityDeclaration(
                multimodal=provider.supports_multimodal,
                structured_output=provider.supports_structured_output,
                tool_calling=provider.supports_tool_calling,
                reasoning=True,
                parallel_tool_calls=provider.supports_tool_calling,
            ),
            capability_profile=plugin_profile,
        )

    def get(self, provider, agent, *, compatibility_profile=None, enable_thinking=None):
        route = self.route(
            provider,
            agent,
            compatibility_profile=compatibility_profile,
            enable_thinking=enable_thinking,
        )
        plugin_profile = route.capability_profile
        cache_key = (
            provider.id,
            agent.agent_id,
            bool(
                enable_thinking
                if enable_thinking is not None
                else thinking_config(agent)[0]
            ),
            json.dumps(route.model_dump(mode="json"), sort_keys=True),
            json.dumps(
                plugin_profile.model_dump(mode="json") if plugin_profile else None,
                sort_keys=True,
            ),
            hashlib.sha256((provider.api_key or "").encode()).hexdigest(),
        )
        cached = self._providers.get(cache_key)
        if cached is not None:
            return cached
        model = create_registered_model_provider(
            route,
            CredentialMaterial(
                credential_id=f"llm-provider:{provider.id}",
                secret=SecretStr(provider.api_key or ""),
                source="desktop-catalog",
            ),
            provider_instance_id=provider.id,
            capability_profile=plugin_profile,
        )
        model = self.budget.wrap(model)
        self._providers[cache_key] = model
        return model


def effective_model_output_tokens(
    provider: DesktopModelProviderRecord,
    profile: DesktopModelCompatibilityProfile | None,
) -> int:
    if profile is not None and profile.effective_max_output_tokens is not None:
        return profile.effective_max_output_tokens
    return provider.max_tokens


def effective_reasoning_effort(
    profile: DesktopModelCompatibilityProfile | None,
    *,
    enabled: bool,
    requested: str,
    legacy: str | None,
) -> str | None:
    if not enabled:
        return None
    if profile is None:
        return legacy
    if profile.schema_version < 2:
        return None
    if profile.reasoning_effort_strategy != "reasoning_effort":
        return None
    if requested in profile.supported_reasoning_efforts:
        return requested
    return None


def reasoning_disable_extra(strategy: str) -> dict[str, Any]:
    return dict(_REASONING_DISABLE_EXTRAS.get(strategy, {}))


def reasoning_effort_extra(
    profile: DesktopModelCompatibilityProfile,
    *,
    enabled: bool,
    requested: str,
) -> dict[str, Any]:
    if (
        enabled
        and profile.schema_version >= 2
        and profile.reasoning_effort_strategy == "chat_template_reasoning_effort"
        and requested in profile.supported_reasoning_efforts
    ):
        return {
            "chat_template_kwargs": {
                "thinking": True,
                "reasoning_effort": requested,
            }
        }
    return {}


def thinking_config(agent) -> tuple[bool, str]:
    enabled = bool(
        agent.config.get("deepThinking", agent.config.get("deep_thinking", False))
    )
    level = str(
        agent.config.get("thinkingLevel")
        or agent.config.get("thinking_level")
        or "medium"
    ).lower()
    if level not in {"minimal", "low", "medium", "high", "xhigh", "max"}:
        level = "medium"
    return enabled, level
