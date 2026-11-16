"""Gemini GenerateContent adapter using the native REST/SSE protocol.

Sage owns the conversation ledger. Native model Parts are kept in protocol
state so thought signatures retain their original position across tool calls
and persisted Session history, including signature-only streaming Parts.
"""

from __future__ import annotations
from sagents.v2.model.failures import annotate_stream_failure

import base64
import copy
import json
from sagents.v2.model.wire_diagnostics import record_wire_event, record_wire_request

from collections.abc import AsyncIterator
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import Field

from sagents.v2.contracts.common import StrictModel, new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import (
    AudioBlock,
    FileBlock,
    ImageBlock,
    JsonBlock,
    ResourceRefBlock,
    TextBlock,
    UsageSummary,
)
from sagents.v2.contracts.provider_state import make_provider_state, read_provider_state
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
)
from sagents.v2.model.plugins._shared.image_limits import request_too_large
from sagents.v2.model.plugins._shared.media import (
    accepts_media,
    media_kind,
    omitted_media_text,
    resolve_media_capabilities,
)
from sagents.v2.model.plugins._shared.stream_idle import StreamIdleTimeout
from sagents.v2.model.plugins._shared.video_storage import (
    STORAGE_OMITTED_TEXT,
    S3VideoStorageConfig,
    current_turn_start,
    publish_videos,
    redact_error_info,
    redact_signed_urls,
)
from sagents.v2.model.plugins._shared.wire import (
    compact_json,
    minimum_reasoning_control,
    parse_tool_arguments,
    provider_error,
    stream_incomplete_error,
    validate_extra_body,
)
from sagents.v2.runtime.credentials.contracts import CredentialMaterial
from sagents.v2.runtime.artifact.workspace_images import materialize_inline_media


_HOST_OWNED_FIELDS = frozenset(
    {
        "contents",
        "systemInstruction",
        "tools",
        "toolConfig",
        "generationConfig",
        "system_instruction",
        "tool_config",
        "generation_config",
    }
)
_EFFORT_BUDGETS = {"minimal": 128, "low": 1024, "medium": 4096, "high": 8192}
# The GenerateContent video guide recommends the Files API above 20 MB.
_DEFAULT_MAX_REQUEST_BYTES = 20_000_000
_WIRE_JSON = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _wire_bytes(value: Any) -> int:
    # Match httpx's JSON encoding without allocating the full oversized body.
    return sum(len(chunk.encode("utf-8")) for chunk in _WIRE_JSON.iterencode(value))


class GeminiGenerateContentConfig(StrictModel):
    provider_id: str = "gemini-generate-content"
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    model: str
    capabilities: ModelCapabilities
    default_max_output_tokens: int | None = Field(default=None, gt=0)
    default_temperature: float | None = None
    default_top_p: float | None = None
    reasoning_effort: str | None = None
    invocation_strategy: dict[str, Any] = Field(default_factory=dict)
    # Gemini 2.5 uses budgets; Gemini 3 uses levels. Gateways can override the
    # dialect explicitly without pretending to implement another protocol.
    thinking_control: Literal["auto", "level", "budget"] = "auto"
    thinking_budget: int | None = Field(default=None, ge=-1)
    include_thoughts: bool = True
    max_inline_videos: int = Field(default=10, ge=1, le=10)
    max_request_bytes: int = Field(default=_DEFAULT_MAX_REQUEST_BYTES, gt=0)
    timeout_seconds: float = Field(default=120, gt=0)
    stream_idle_timeout_seconds: float | None = Field(
        default=None, gt=0, allow_inf_nan=False
    )
    video_storage: S3VideoStorageConfig | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)


class GeminiGenerateContentModelProvider:
    plugin_id = "sage.model.gemini-generate-content"
    plugin_version = "1.0.0"
    name = "Gemini GenerateContent"
    description = (
        "Uses native Gemini Parts, function calls, thought signatures, and SSE."
    )

    def __init__(
        self,
        config: GeminiGenerateContentConfig,
        credential: CredentialMaterial | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        if client is None and credential is None:
            raise ValueError("credential is required when client is not injected")
        self.config = config
        self._owns_client = client is None
        if client is not None:
            self._client = client
        else:
            assert credential is not None
            self._client = httpx.AsyncClient(
                base_url=config.base_url.rstrip("/") + "/",
                timeout=config.timeout_seconds,
                headers={
                    "x-goog-api-key": credential.secret.get_secret_value(),
                    "content-type": "application/json",
                },
            )

    @property
    def raw_client(self) -> Any:
        return self._client

    @property
    def thinking_control(self) -> str:
        if self.config.thinking_control != "auto":
            return self.config.thinking_control
        model = self.config.model.removeprefix("models/").lower()
        return "budget" if model.startswith("gemini-2.5") else "level"

    async def capabilities(self, model_binding: str) -> ModelCapabilities:
        return self._effective_capabilities()

    def _effective_capabilities(self) -> ModelCapabilities:
        capabilities = self.config.capabilities
        return resolve_media_capabilities(
            capabilities, native=True, default=capabilities.supports_multimodal_input
        )

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        return self._stream(request)

    @classmethod
    def apply_capability_profile(cls, config, profile):
        updates: dict[str, Any] = {
            "invocation_strategy": dict(profile.invocation_strategy),
            "default_max_output_tokens": min(
                config.default_max_output_tokens or profile.effective_max_output_tokens,
                profile.effective_max_output_tokens,
            ),
        }
        dialect = profile.invocation_strategy.get("thinking_control")
        if config.thinking_control == "auto" and dialect in {"level", "budget"}:
            updates["thinking_control"] = dialect
        if (
            config.reasoning_effort is None
            and config.thinking_budget is None
            and profile.invocation_strategy.get("reasoning_disable_strategy")
            == "thinking_budget_zero"
        ):
            updates["thinking_budget"] = 0
        return config.model_copy(update=updates)

    async def probe_capabilities(self, request):
        from sagents.v2.model.capability_probe import (
            capability_probe_config,
            model_capability_profile,
            negotiate_model_output_limit,
            probe_model_capabilities,
            probe_model_reasoning_controls,
        )

        probe_config = capability_probe_config(self.config)
        effective, _ = await negotiate_model_output_limit(self, request)

        def clone(*, effort=None, budget=None):
            return self.__class__(
                probe_config.model_copy(
                    update={
                        "default_max_output_tokens": effective,
                        "reasoning_effort": effort,
                        "thinking_budget": budget,
                        "extra_body": {},
                    }
                ),
                client=self.raw_client,
            )

        base = clone()
        report = await probe_model_capabilities(
            base,
            model_binding=request.model_binding,
            max_output_tokens=effective,
            timeout_seconds=request.timeout_seconds,
        )
        reasoning, metadata = await probe_model_reasoning_controls(
            base_provider=base,
            provider_factory=lambda strategy, effort: clone(
                effort=effort,
                budget=0 if strategy == "thinking_budget_zero" else None,
            ),
            report=report,
            request=request,
            max_output_tokens=effective,
            disable_strategies=("omit", "thinking_budget_zero"),
            effort_strategies=("reasoning_effort",),
        )
        return model_capability_profile(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            protocol="gemini-generate-content",
            request=request,
            effective_max_output_tokens=effective,
            report=report,
            reasoning=reasoning,
            invocation_strategy={
                "reasoning_disable_strategy": metadata["disable_strategy"],
                "reasoning_behavior": metadata["behavior"],
                "reasoning_effort_strategy": metadata["effort_strategy"],
                "supported_reasoning_efforts": metadata["supported_efforts"],
                "text_only_reasoning_efforts": metadata["text_only_efforts"],
                "unsupported_reasoning_efforts": metadata["unsupported_efforts"],
                "supports_json_object": report.supports_json_object,
                "auxiliary_json_compatible": bool(
                    metadata["auxiliary_json"].get("status") == "supported"
                ),
                "thinking_control": self.thinking_control,
            },
        )

    def diagnostic_request(self, request: ModelRequest) -> dict[str, Any]:
        self._validate_request(request)
        system, contents = self._contents(request.messages)
        generation: dict[str, Any] = {"candidateCount": 1}
        maximum = request.max_output_tokens or self.config.default_max_output_tokens
        if maximum is not None:
            generation["maxOutputTokens"] = maximum
        temperature = (
            request.temperature
            if request.temperature is not None
            else self.config.default_temperature
        )
        if temperature is not None:
            generation["temperature"] = temperature
        if self.config.default_top_p is not None:
            generation["topP"] = self.config.default_top_p
        if self.config.capabilities.supports_reasoning:
            thinking: dict[str, Any] = {"includeThoughts": self.config.include_thoughts}
            if self.config.thinking_budget is not None:
                thinking["thinkingBudget"] = self.config.thinking_budget
            elif (
                self.config.reasoning_effort is not None
                and request.reasoning_mode != "minimum"
            ):
                effort = self.config.reasoning_effort
                if effort not in _EFFORT_BUDGETS:
                    raise self._error("model.reasoning_effort_unsupported", effort)
                if self.thinking_control == "budget":
                    thinking["thinkingBudget"] = _EFFORT_BUDGETS[effort]
                else:
                    thinking["thinkingLevel"] = effort
            if request.reasoning_mode == "minimum":
                control, effort = minimum_reasoning_control(
                    self.config.invocation_strategy,
                    default_disable=(
                        "thinking_budget_zero"
                        if self.thinking_control == "budget"
                        else "thinking_level_minimal"
                    ),
                )
                thinking = {"includeThoughts": False}
                if control == "thinking_budget_zero":
                    thinking["thinkingBudget"] = 0
                elif effort is not None:
                    if self.thinking_control == "budget":
                        thinking["thinkingBudget"] = _EFFORT_BUDGETS[effort]
                    else:
                        thinking["thinkingLevel"] = effort
                elif control != "omit":
                    thinking["thinkingLevel"] = "minimal"
            generation["thinkingConfig"] = thinking
        if (
            request.response_format == "json_object"
            or request.response_schema is not None
        ):
            generation["responseMimeType"] = "application/json"
        if request.response_schema is not None:
            generation["responseJsonSchema"] = request.response_schema
        payload: dict[str, Any] = {"contents": contents, "generationConfig": generation}
        if system:
            payload["systemInstruction"] = {"parts": system}
        if request.tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "parametersJsonSchema": tool.input_schema,
                        }
                        for tool in request.tools
                    ]
                }
            ]
            if request.tool_choice is not None:
                payload["toolConfig"] = {
                    "functionCallingConfig": {
                        "mode": {
                            "auto": "AUTO",
                            "required": "ANY",
                            "none": "NONE",
                        }[request.tool_choice]
                    }
                }
        validate_extra_body(
            self.config.extra_body,
            reserved_fields=_HOST_OWNED_FIELDS,
            provider=self.config.provider_id,
        )
        payload.update(self.config.extra_body)
        return payload

    async def _stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        payload = self.diagnostic_request(request)
        signed_urls = await self._publish_videos(payload)
        await self._limit_media_parts(payload)
        model = quote(self.config.model.removeprefix("models/"), safe="-._")
        path = f"models/{model}:streamGenerateContent?alt=sse"
        response_id = new_id("model_response")
        parts: list[dict[str, Any]] = []
        calls = []
        text = reasoning = ""
        provider_usage: dict[str, Any] = {}
        terminal = False
        idle = StreamIdleTimeout(
            self.config.stream_idle_timeout_seconds, provider=self.config.provider_id
        )
        finish_reason = "completed"
        def stream_failure(error):
            error = redact_error_info(error, signed_urls)
            thoughts = self._counter(provider_usage, "thoughtsTokenCount")
            cached = self._counter(provider_usage, "cachedContentTokenCount")
            observed_usage = UsageSummary(
                reported=bool(provider_usage),
                input_tokens=max(self._counter(provider_usage, "promptTokenCount"), cached),
                output_tokens=self._counter(provider_usage, "candidatesTokenCount") + thoughts,
                cached_input_tokens=cached, reasoning_tokens=thoughts,
                models=(self.config.model,), provider_usage=provider_usage,
            )
            return SageV2Error(annotate_stream_failure(
                error, provider=self.config.provider_id, usage=observed_usage,
                response_id=response_id, terminal_received=terminal,
                text=text, reasoning=reasoning, tools=calls,
            ))

        try:
            diagnostic_payload = redact_signed_urls(payload, signed_urls)
            await record_wire_request(
                diagnostic_payload, model=self.config.model, provider=self.config.provider_id,
            )
            record_wire_event(
                {"diagnostic_event": "request_attempt", "payload": diagnostic_payload}
            )
            async with self._client.stream("POST", path, json=payload) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise httpx.HTTPStatusError(
                        response.text[:2000],
                        request=response.request,
                        response=response,
                    )
                async for event in idle.iterate(self._events(response)):
                    record_wire_event(redact_signed_urls(event, signed_urls))
                    if event.get("error"):
                        error = event["error"]
                        failed = httpx.Response(
                            int(error.get("code") or 500),
                            request=response.request,
                            json={"error": error},
                        )
                        raise httpx.HTTPStatusError(
                            str(error.get("message") or error),
                            request=response.request,
                            response=failed,
                        )
                    feedback = event.get("promptFeedback") or {}
                    if feedback.get("blockReason") not in (
                        None,
                        "BLOCK_REASON_UNSPECIFIED",
                    ):
                        raise self._error(
                            "model.response_blocked", str(feedback["blockReason"])
                        )
                    response_id = event.get("responseId") or response_id
                    provider_usage.update(event.get("usageMetadata") or {})
                    for candidate in event.get("candidates") or []:
                        if candidate.get("index", 0) != 0:
                            raise self._error(
                                "model.response_invalid", "unexpected extra candidate"
                            )
                        for part in (candidate.get("content") or {}).get("parts") or []:
                            if terminal:
                                raise self._error(
                                    "model.response_invalid",
                                    "content after finishReason",
                                )
                            if not isinstance(part, dict) or set(part) - {
                                "text",
                                "thought",
                                "thoughtSignature",
                                "functionCall",
                            }:
                                raise self._error(
                                    "model.response_unsupported",
                                    "unsupported Gemini output Part",
                                )
                            parts.append(copy.deepcopy(part))
                            value = part.get("text") or ""
                            if value or part.get("thoughtSignature") or part.get("functionCall"):
                                idle.progress()
                            if value:
                                thought = bool(part.get("thought"))
                                if thought:
                                    reasoning += value
                                else:
                                    text += value
                                yield ModelStreamEvent(
                                    kind=ModelEventKind.REASONING_DELTA
                                    if thought
                                    else ModelEventKind.TEXT_DELTA,
                                    delta=value,
                                )
                            if "functionCall" in part:
                                call = part["functionCall"]
                                calls.append(
                                    parse_tool_arguments(
                                        compact_json(call.get("args", {})),
                                        tool_call_id=call.get("id"),
                                        name=call.get("name"),
                                        diagnostic_context={
                                            "provider": self.config.provider_id,
                                            "finish_reason": "max_tokens" if candidate.get("finishReason") == "MAX_TOKENS" else candidate.get("finishReason"),
                                        },
                                    )
                                )
                        reason = candidate.get("finishReason")
                        if reason and reason != "FINISH_REASON_UNSPECIFIED":
                            if reason not in {"STOP", "MAX_TOKENS"}:
                                if reason in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"}:
                                    finish_reason = "refusal"
                                    terminal = True
                                    idle.finish()
                                    continue
                                if reason in {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL"}:
                                    raise SageV2Error(RuntimeErrorInfo(
                                        code="model.tool_arguments_invalid_json",
                                        category=ErrorCategory.VALIDATION,
                                        message="The model returned an invalid function call.",
                                        retryable=True, safe_to_resume=True,
                                        metadata={"side_effect_state": "not_applied", "tool_execution_started": False,
                                                  "native_finish_reason": reason}))
                                raise self._error("model.response_unknown", str(reason))
                            terminal = True
                            idle.finish()
                            finish_reason = (
                                "max_tokens" if reason == "MAX_TOKENS" else "completed"
                            )
        except SageV2Error as exc:
            raise stream_failure(exc.info) from exc
        except Exception as exc:
            failure = stream_failure(provider_error(exc, response_started=idle.response_started, provider=self.config.provider_id).info)
            if signed_urls:
                raise failure from None
            raise failure from exc
        if not terminal:
            raise stream_failure(stream_incomplete_error(
                provider=self.config.provider_id, response_started=idle.response_started
            ).info)
        thoughts = self._counter(provider_usage, "thoughtsTokenCount")
        cached = self._counter(provider_usage, "cachedContentTokenCount")
        yield ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(
                response_id=response_id,
                text=text,
                reasoning=reasoning,
                tool_calls=tuple(calls),
                finish_reason=finish_reason,
                usage=UsageSummary(
                    reported=bool(provider_usage),
                    input_tokens=max(
                        self._counter(provider_usage, "promptTokenCount"), cached
                    ),
                    output_tokens=self._counter(provider_usage, "candidatesTokenCount")
                    + thoughts,
                    cached_input_tokens=cached,
                    reasoning_tokens=thoughts,
                    models=(self.config.model,),
                    provider_usage=provider_usage,
                ),
                provider_metadata={
                    "provider_id": self.config.provider_id,
                    "model": self.config.model,
                    "api": "gemini-generate-content",
                },
                provider_state=make_provider_state(
                    "gemini_generate_content",
                    {
                        "parts": parts,
                        "tool_call_ids": [call.tool_call_id for call in calls],
                    },
                ),
            ),
        )

    @staticmethod
    async def _events(response) -> AsyncIterator[dict[str, Any]]:
        lines: list[str] = []
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                lines.append(line[5:].lstrip())
            elif not line and lines:
                value = json.loads("\n".join(lines))
                lines.clear()
                if not isinstance(value, dict):
                    raise ValueError("Gemini SSE data must be an object")
                yield value
        if lines:
            value = json.loads("\n".join(lines))
            if not isinstance(value, dict):
                raise ValueError("Gemini SSE data must be an object")
            yield value

    async def _publish_videos(self, payload: dict[str, Any]) -> frozenset[str]:
        if self.config.video_storage is None:
            return frozenset()
        contents = payload["contents"]
        turn_start = current_turn_start([content.get("role") for content in contents], "model")
        videos = [
            (part, index >= turn_start)
            for index, content in enumerate(contents)
            for part in content["parts"]
            if str(
                (part.get("inlineData") or part.get("fileData") or {}).get("mimeType", "")
            ).lower().startswith("video/")
        ]
        # Older videos beyond the inline cap become text references without uploading.
        parts = [
            (part, current) for part, current in videos[-self.config.max_inline_videos:]
            if isinstance(part.get("inlineData"), dict)
        ]
        sources = {
            id(part): f"data:{part['inlineData']['mimeType']};base64,{part['inlineData']['data']}"
            for part, _ in parts
        }
        signed = await publish_videos(
            self.config.video_storage,
            {sources[id(part)]: part["inlineData"]["mimeType"] for part, _ in parts},
            required={sources[id(part)] for part, current in parts if current},
        )
        omitted = 0
        for part, _ in parts:
            media = part.pop("inlineData")
            url = signed.get(sources[id(part)])
            if url is None:
                part["text"] = STORAGE_OMITTED_TEXT
                omitted += 1
            else:
                part["fileData"] = {"mimeType": media["mimeType"], "fileUri": url}
        if omitted:
            record_wire_event({"diagnostic_event": "video_storage_omitted", "videos": omitted})
        return frozenset(signed.values())

    async def _limit_media_parts(self, payload: dict[str, Any]) -> None:
        media_parts = []
        for content in payload["contents"]:
            parts = content["parts"]
            for index, part in enumerate(parts):
                media = part.get("inlineData") or part.get("fileData")
                mime_type = media.get("mimeType") if isinstance(media, dict) else None
                kind = mime_type.lower().partition("/")[0] if isinstance(mime_type, str) else ""
                if kind in {"audio", "video"}:
                    media_parts.append((parts, index, media, mime_type, kind))

        videos = [item for item in media_parts if item[4] == "video"]
        overflow = videos[: max(0, len(videos) - self.config.max_inline_videos)]
        for parts, index, media, mime_type, kind in overflow:
            parts[index] = await self._media_reference(media, mime_type, kind)
        replaced = {id(item[2]) for item in overflow}

        size = _wire_bytes(payload)
        limit = self.config.max_request_bytes
        for parts, index, media, mime_type, kind in media_parts:
            if size <= limit:
                break
            if id(media) in replaced or "data" not in media:
                continue  # Remote file references do not carry media bytes.
            replacement = await self._media_reference(media, mime_type, kind)
            saved = _wire_bytes(parts[index]) - _wire_bytes(replacement)
            if saved > 0:
                parts[index] = replacement
                size -= saved
        if size > limit:
            raise request_too_large(size, limit)

    @staticmethod
    async def _media_reference(
        media: dict[str, Any], mime_type: str, kind: str
    ) -> dict[str, str]:
        label = kind.capitalize()
        if "fileUri" in media:
            return {"text": f"[{label} reference: {media['fileUri']}]"}
        path = await materialize_inline_media(media["data"], mime_type.lower())
        return {"text": (
            f"[Workspace {kind}: {path}]"
            if path
            else f"[{label} omitted from this model request because of the request limits.]"
        )}

    def _contents(self, messages: tuple[ModelMessage, ...]):
        system: list[dict[str, Any]] = []
        contents: list[dict[str, Any]] = []
        call_map: dict[str, dict[str, Any]] = {}
        for message in messages:
            if message.role in {"system", "developer"}:
                if any(
                    not isinstance(block, (TextBlock, JsonBlock))
                    for block in message.content
                ):
                    raise self._error(
                        "model.system_content_unsupported",
                        "Gemini system instructions must be text",
                    )
                system.extend(self._part(block) for block in message.content)
                continue
            if message.role == "tool":
                original = call_map.get(message.tool_call_id) if message.tool_call_id else None
                if original is None:
                    raise self._error(
                        "model.tool_call_missing",
                        "tool result has no matching Gemini function call",
                    )
                output = (
                    message.content[0].value
                    if len(message.content) == 1
                    and isinstance(message.content[0], JsonBlock)
                    else message.content[0].text
                    if len(message.content) == 1
                    and isinstance(message.content[0], TextBlock)
                    else [self._request_part(block) for block in message.content]
                )
                result = {
                    "name": original["name"],
                    "response": output
                    if isinstance(output, dict)
                    else {"output": output},
                }
                if original.get("id"):
                    result["id"] = original["id"]
                parts = [{"functionResponse": result}]
            else:
                state = (
                    read_provider_state(
                        message.provider_state, "gemini_generate_content"
                    )
                    if message.role == "assistant"
                    else None
                )
                if state is not None:
                    parts = copy.deepcopy(state.get("parts"))
                    ids = state.get("tool_call_ids", [])
                    if not isinstance(parts, list) or any(
                        not isinstance(part, dict) for part in parts
                    ):
                        raise self._error(
                            "model.provider_state_invalid", "invalid Gemini Parts state"
                        )
                    native_calls = [
                        part["functionCall"] for part in parts if "functionCall" in part
                    ]
                    if len(ids) != len(native_calls) or list(ids) != [
                        call.tool_call_id for call in message.tool_calls
                    ]:
                        raise self._error(
                            "model.provider_state_invalid",
                            "Gemini tool call state does not match ledger",
                        )
                    call_map.update(zip(ids, native_calls, strict=True))
                else:
                    parts = [self._request_part(block) for block in message.content]
                    for call in message.tool_calls:
                        native = {"name": call.name, "args": call.arguments}
                        parts.append({"functionCall": native})
                        call_map[call.tool_call_id] = native
            if not parts:
                continue
            role = "model" if message.role == "assistant" else "user"
            # Batch parallel results into one user Content, after all model calls.
            if role == "user" and contents and contents[-1]["role"] == role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": role, "parts": parts})
        return system, contents

    def _request_part(self, block) -> dict[str, Any]:
        kind = media_kind(block)
        if kind is not None and not accepts_media(self._effective_capabilities(), kind):
            return {"text": omitted_media_text(kind)}
        return self._part(block)

    @classmethod
    def _part(cls, block) -> dict[str, Any]:
        if isinstance(block, TextBlock):
            return {"text": block.text}
        if isinstance(block, JsonBlock):
            return {"text": compact_json(block.value)}
        if isinstance(block, ResourceRefBlock):
            return {"text": f"[resource: {block.uri}]"}
        if isinstance(block, (ImageBlock, AudioBlock, FileBlock)):
            if block.uri.startswith("data:") and ";base64," in block.uri:
                header, data = block.uri.split(",", 1)
                base64.b64decode(data, validate=True)
                return {
                    "inlineData": {
                        "mimeType": header[5:].split(";", 1)[0],
                        "data": data,
                    }
                }
            if not block.mime_type:
                raise cls._error(
                    "model.media_mime_type_missing", "Gemini media requires a MIME type"
                )
            return {"fileData": {"mimeType": block.mime_type, "fileUri": block.uri}}
        raise TypeError(f"unsupported content block {type(block)!r}")

    def _validate_request(self, request: ModelRequest) -> None:
        caps = self.config.capabilities
        if request.tools and not caps.supports_tools:
            raise self._error(
                "model.capability_unsupported", "model binding does not support tools"
            )
        if (
            request.response_schema is not None or request.response_format is not None
        ) and not caps.supports_structured_output:
            raise self._error(
                "model.capability_unsupported",
                "model binding does not support structured_output",
            )
        if not caps.supports_multimodal_input and any(
            isinstance(block, (ImageBlock, FileBlock)) and media_kind(block) is None
            for message in request.messages
            for block in message.content
        ):
            raise self._error(
                "model.capability_unsupported",
                "model binding does not support multimodal_input",
            )
        maximum = request.max_output_tokens or self.config.default_max_output_tokens
        if (
            maximum is not None
            and caps.max_output_tokens is not None
            and maximum > caps.max_output_tokens
        ):
            raise self._error(
                "model.output_budget_exceeded",
                "requested output tokens exceed model limit",
            )
        if self.config.reasoning_effort is not None and not caps.supports_reasoning:
            raise self._error(
                "model.capability_unsupported",
                "model binding does not support reasoning",
            )

    @staticmethod
    def _counter(value: dict[str, Any], name: str) -> int:
        return max(0, int(value.get(name) or 0))

    @staticmethod
    def _error(
        code: str, message: str, *, provider_code: str | None = None
    ) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION
                if code.startswith("model.capability")
                or code
                in {
                    "model.output_budget_exceeded",
                    "model.reasoning_effort_unsupported",
                    "model.provider_state_invalid",
                    "model.tool_call_missing",
                    "model.media_mime_type_missing",
                    "model.system_content_unsupported",
                }
                else ErrorCategory.PROVIDER_PERMANENT,
                message=message,
                provider_code=provider_code,
                safe_to_resume=True,
            )
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
