"""Translate the APP's default model record into a CLI runtime route."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from app.v2.cli.errors import CLIError
from app.v2.cli.package import CliModelSettings
from sagents.v2.model.protocols import model_protocol_descriptor, model_protocol_implementation
from sagents.v2.package.manifest.models import (
    ModelCapabilityDeclaration, ModelLimits, ModelRequestDefaults, ModelRoute,
)

# A process-only credential reference; never embed the APP key in a manifest.
APP_CREDENTIAL_ENV = "SAGE_CLI_APP_MODEL_API_KEY"
_DISABLE_REASONING: dict[str | None, dict[str, Any]] = {
    "omit": {},
    "reasoning_effort_none": {"reasoning_effort": "none"},
    "thinking_type_disabled": {"thinking": {"type": "disabled"}},
    "enable_thinking_false": {"enable_thinking": False},
    "thinking_false": {"thinking": False},
    "chat_template_enable_thinking_false": {"chat_template_kwargs": {"enable_thinking": False}},
}


def _verified_profile(provider: dict, protocol: str) -> dict:
    profile = provider.get("compatibility_profile") or {}
    implementation = model_protocol_implementation(model_protocol_descriptor(protocol).protocol)
    payload = {
        "protocol": protocol,
        "plugin_id": implementation.plugin_id,
        "plugin_version": implementation.plugin_version,
        "base_url": provider["base_url"].rstrip("/"),
        "model": provider["model"],
        "max_tokens": provider.get("max_tokens", 8192),
        "max_model_len": provider.get("max_model_len", 128000),
        "temperature": provider.get("temperature"),
        "top_p": provider.get("top_p"),
        "credential_sha256": hashlib.sha256(provider["api_key"].encode()).hexdigest(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    fingerprint = "sha256:" + hashlib.sha256(encoded).hexdigest()
    return profile if profile.get("route_fingerprint") == fingerprint else {}


def app_model_settings(provider: dict) -> CliModelSettings:
    try:
        protocol = provider.get("protocol", "openai-responses")
        profile = _verified_profile(provider, protocol)
        plugin_profile = profile.get("plugin_profile")
        maximum = (profile.get("effective_max_output_tokens") or provider.get("max_tokens") or 8192)
        extra = {}
        if profile and not plugin_profile:
            extra.update(_DISABLE_REASONING.get(profile.get("reasoning_disable_strategy"), {}))
            if protocol == "openai-chat-completions" and profile.get("max_output_tokens_field"):
                extra["max_output_tokens_field"] = profile["max_output_tokens_field"]
        route = ModelRoute(
            provider=protocol, model=provider["model"], base_url=provider["base_url"],
            credential="model_api_key",
            request=ModelRequestDefaults(
                max_output_tokens=maximum, temperature=provider.get("temperature"),
                top_p=provider.get("top_p"), extra=extra,
            ),
            limits=ModelLimits(context_window=provider.get("max_model_len") or 128000,
                               max_output_tokens=maximum),
            capabilities=ModelCapabilityDeclaration(
                multimodal=provider.get("supports_multimodal", True),
                structured_output=provider.get("supports_structured_output", True),
                tool_calling=provider.get("supports_tool_calling", True), reasoning=True,
                parallel_tool_calls=provider.get("supports_tool_calling", True),
            ),
            capability_profile=plugin_profile,
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CLIError("The APP default model configuration is invalid.",
                       next_steps=["Check the default model in APP settings."]) from exc
    os.environ[APP_CREDENTIAL_ENV] = provider["api_key"]
    return CliModelSettings(
        model=route.model, base_url=route.base_url, credential_env=APP_CREDENTIAL_ENV,
        context_window=route.limits.context_window, max_output_tokens=maximum, route=route,
    )
