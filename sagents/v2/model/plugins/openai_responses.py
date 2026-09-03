"""OpenAI Responses API adapter for the v2 model capability port."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI
from pydantic import Field

from sagents.v2.contracts.common import StrictModel, new_id
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
from sagents.v2.runtime.credentials.contracts import CredentialMaterial
from sagents.v2.model.wire import (
    compact_json,
    parse_tool_arguments,
    provider_error,
    wire_json_value,
    wire_value,
)
from sagents.v2.model.usage import canonical_token_usage
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
)


class OpenAIResponsesConfig(StrictModel):
    """Configuration that is safe to persist because credentials live elsewhere."""

    provider_id: str = "openai-responses"
    base_url: str = "https://api.openai.com/v1"
    model: str
    capabilities: ModelCapabilities
    default_max_output_tokens: int | None = Field(default=None, gt=0)
    default_temperature: float | None = None
    default_top_p: float | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float = Field(default=120, gt=0)
    store: bool = False
    extra_body: dict[str, Any] = Field(default_factory=dict)
    reasoning_parameter_fallback: bool = False


class OpenAIResponsesModelProvider:
    """Map v2 messages, tools, and stream events to the Responses API.

    The adapter is stateless by default (`store=False`) because the Sage Run
    ledger is authoritative.  Hosts may opt into provider storage explicitly,
    but this adapter never relies on `previous_response_id` for correctness.
    """

    plugin_id = "sage.model.openai-responses"
    plugin_version = "3.0.0"
    name = "OpenAI Responses"
    description = "Uses typed input/output items and Responses streaming events."

    @classmethod
    def apply_capability_profile(cls, config, profile):
        """Apply only a Responses-owned persisted invocation strategy."""

        strategy = profile.invocation_strategy
        reasoning_effort = config.reasoning_effort
        if (
            reasoning_effort is None
            and strategy.get("reasoning_disable_strategy") == "reasoning_effort_none"
        ):
            reasoning_effort = "none"
        return config.model_copy(
            update={
                "default_max_output_tokens": min(
                    config.default_max_output_tokens
                    or profile.effective_max_output_tokens,
                    profile.effective_max_output_tokens,
                ),
                "reasoning_effort": reasoning_effort,
            }
        )

    def __init__(
        self,
        config: OpenAIResponsesConfig,
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
            self._client = AsyncOpenAI(
                api_key=credential.secret.get_secret_value(),
                base_url=config.base_url,
                timeout=config.timeout_seconds,
            )
        self._reasoning_control_rejected = False

    @property
    def raw_client(self) -> Any:
        return self._client

    async def close(self) -> None:
        """Release only the SDK client created by this plugin instance."""

        if not self._owns_client:
            return
        close = getattr(self._client, "close", None) or getattr(
            self._client, "aclose", None
        )
        if close is None:
            return
        result = close()
        if hasattr(result, "__await__"):
            await result

    async def capabilities(self, model_binding: str) -> ModelCapabilities:
        return self.config.capabilities

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        return self._stream(request)

    async def probe_capabilities(self, request):
        """Probe only the Responses wire contract owned by this plugin."""

        from sagents.v2.model.capability_probe import (
            model_capability_profile,
            negotiate_model_output_limit,
            probe_model_capabilities,
            probe_model_reasoning_controls,
        )

        effective, _ = await negotiate_model_output_limit(self, request)

        def clone(
            *,
            reasoning_effort: str | None = None,
            extra_body: dict[str, Any] | None = None,
        ):
            config = self.config.model_copy(
                update={
                    "default_max_output_tokens": effective,
                    "reasoning_effort": reasoning_effort,
                    "extra_body": dict(extra_body or {}),
                }
            )
            return self.__class__(config, client=self.raw_client)

        model_provider = clone()
        report = await probe_model_capabilities(
            model_provider,
            model_binding=request.model_binding,
            max_output_tokens=effective,
            timeout_seconds=request.timeout_seconds,
        )

        def reasoning_provider(strategy: str, effort: str | None):
            if effort is not None:
                return clone(reasoning_effort=effort)
            if strategy == "reasoning_effort_none":
                return clone(reasoning_effort="none")
            return clone()

        reasoning, reasoning_metadata = await probe_model_reasoning_controls(
            base_provider=model_provider,
            provider_factory=reasoning_provider,
            report=report,
            request=request,
            max_output_tokens=effective,
            disable_strategies=("omit", "reasoning_effort_none"),
            effort_strategies=("reasoning_effort",),
        )
        return model_capability_profile(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            protocol="openai-responses",
            request=request,
            effective_max_output_tokens=effective,
            report=report,
            reasoning=reasoning,
            invocation_strategy={
                "reasoning_disable_strategy": reasoning_metadata["disable_strategy"],
                "reasoning_behavior": reasoning_metadata["behavior"],
                "reasoning_effort_strategy": reasoning_metadata["effort_strategy"],
                "supported_reasoning_efforts": reasoning_metadata["supported_efforts"],
                "text_only_reasoning_efforts": reasoning_metadata["text_only_efforts"],
                "unsupported_reasoning_efforts": reasoning_metadata[
                    "unsupported_efforts"
                ],
                "supports_json_object": report.supports_json_object,
                "auxiliary_json_compatible": bool(
                    reasoning_metadata["auxiliary_json"].get("status") == "supported"
                ),
            },
        )

    def diagnostic_request(self, request: ModelRequest) -> dict[str, Any]:
        """Return the exact non-secret keyword arguments passed to the SDK."""

        self._validate_request(request)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "input": self._input_items(request.messages),
            "stream": True,
            "store": self.config.store,
        }
        if request.tools:
            payload["tools"] = [self._tool_definition(tool) for tool in request.tools]
            if request.tool_choice is not None:
                payload["tool_choice"] = request.tool_choice
        maximum = request.max_output_tokens or self.config.default_max_output_tokens
        if maximum is not None:
            payload["max_output_tokens"] = maximum
        temperature = (
            request.temperature
            if request.temperature is not None
            else self.config.default_temperature
        )
        if temperature is not None:
            payload["temperature"] = temperature
        if self.config.default_top_p is not None:
            payload["top_p"] = self.config.default_top_p
        if (
            self.config.reasoning_effort is not None
            and not self._reasoning_control_rejected
        ):
            payload["reasoning"] = {"effort": self.config.reasoning_effort}
            if not self.config.store:
                payload["include"] = ["reasoning.encrypted_content"]
        if request.response_format == "json_object":
            payload["text"] = {"format": {"type": "json_object"}}
        elif request.response_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "sage_response",
                    "strict": True,
                    "schema": request.response_schema,
                }
            }
        if self.config.extra_body:
            payload["extra_body"] = dict(self.config.extra_body)
        return payload

    async def _stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        payload = self.diagnostic_request(request)
        upstream = None
        response_id = new_id("model_response")
        text = ""
        reasoning = ""
        finish_reason = "completed"
        usage = UsageSummary(models=(self.config.model,))
        tool_fragments: dict[str, dict[str, str]] = {}
        reasoning_items: dict[str, dict[str, Any]] = {}
        response_started = False
        compatibility_fallback: dict[str, Any] | None = None
        try:
            try:
                upstream = await self._client.responses.create(**payload)
            except Exception as exc:
                fallback_payload = self._reasoning_fallback_request(payload, exc)
                if fallback_payload is None:
                    raise
                upstream = await self._client.responses.create(**fallback_payload)
                self._reasoning_control_rejected = True
                compatibility_fallback = {
                    "kind": "reasoning_controls_omitted",
                    "removed": ["reasoning"],
                    "provider_status": self._provider_status(exc),
                }
            async for event in upstream:
                event_type = str(wire_value(event, "type", ""))
                if event_type == "response.output_text.delta":
                    delta = str(wire_value(event, "delta", "") or "")
                    if delta:
                        response_started = True
                        text += delta
                        yield ModelStreamEvent(
                            kind=ModelEventKind.TEXT_DELTA, delta=delta
                        )
                    continue
                if event_type in {
                    "response.reasoning_summary_text.delta",
                    "response.reasoning_text.delta",
                }:
                    delta = str(wire_value(event, "delta", "") or "")
                    if delta:
                        response_started = True
                        reasoning += delta
                        yield ModelStreamEvent(
                            kind=ModelEventKind.REASONING_DELTA, delta=delta
                        )
                    continue
                if event_type == "response.output_item.added":
                    item = wire_value(event, "item")
                    if wire_value(item, "type") in {"function_call", "reasoning"}:
                        response_started = True
                    self._record_reasoning_item(reasoning_items, item)
                    self._record_tool_item(tool_fragments, item, replace=False)
                    continue
                if event_type == "response.function_call_arguments.delta":
                    key = self._tool_key(event)
                    fragment = tool_fragments.setdefault(
                        key, {"id": key, "name": "", "arguments": ""}
                    )
                    fragment["arguments"] += str(wire_value(event, "delta", "") or "")
                    continue
                if event_type == "response.output_item.done":
                    self._record_reasoning_item(
                        reasoning_items, wire_value(event, "item")
                    )
                    self._record_tool_item(
                        tool_fragments, wire_value(event, "item"), replace=True
                    )
                    continue
                if event_type in {"response.completed", "response.incomplete"}:
                    response = wire_value(event, "response")
                    response_id = str(
                        wire_value(response, "id", response_id) or response_id
                    )
                    status = str(
                        wire_value(response, "status", "completed") or "completed"
                    )
                    finish_reason = status
                    incomplete = wire_value(response, "incomplete_details")
                    if incomplete is not None:
                        finish_reason = str(
                            wire_value(incomplete, "reason", finish_reason)
                            or finish_reason
                        )
                    raw_usage = wire_value(response, "usage")
                    usage = self._usage(raw_usage)
                    for item in wire_value(response, "output", ()) or ():
                        self._record_reasoning_item(reasoning_items, item)
                    continue
                if event_type in {"response.failed", "error"}:
                    error = wire_value(event, "error") or wire_value(
                        wire_value(event, "response"), "error"
                    )
                    raise RuntimeError(
                        str(wire_value(error, "message", "Responses API failed"))
                    )
        except Exception as exc:
            from sagents.v2.contracts.errors import SageV2Error

            if isinstance(exc, SageV2Error):
                raise
            raise provider_error(exc, response_started=response_started) from exc
        finally:
            if upstream is not None:
                await self._close_stream(upstream)

        calls = tuple(
            parse_tool_arguments(
                fragment["arguments"],
                tool_call_id=fragment["id"],
                name=fragment["name"],
            )
            for fragment in tool_fragments.values()
        )
        yield ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(
                response_id=response_id,
                text=text,
                reasoning=reasoning,
                tool_calls=calls,
                finish_reason=finish_reason,
                usage=usage,
                provider_metadata={
                    "provider_id": self.config.provider_id,
                    "model": self.config.model,
                    "api": "responses",
                    **(
                        {"compatibility_fallback": compatibility_fallback}
                        if compatibility_fallback is not None
                        else {}
                    ),
                },
                provider_state=make_provider_state(
                    "openai_responses",
                    {"reasoning_items": list(reasoning_items.values())},
                )
                if reasoning_items
                else {},
            ),
        )

    def _reasoning_fallback_request(
        self, payload: dict[str, Any], exc: Exception
    ) -> dict[str, Any] | None:
        if not self.config.reasoning_parameter_fallback:
            return None
        if self._provider_status(exc) not in {400, 422}:
            return None
        if "reasoning" not in payload:
            return None
        fallback = dict(payload)
        fallback.pop("reasoning", None)
        include = fallback.get("include")
        if include == ["reasoning.encrypted_content"]:
            fallback.pop("include", None)
        return fallback

    @staticmethod
    def _provider_status(exc: Exception) -> int | None:
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        return status if isinstance(status, int) else None

    def _validate_request(self, request: ModelRequest) -> None:
        capabilities = self.config.capabilities
        if request.tools and not capabilities.supports_tools:
            raise self._capability_error("tools")
        if (
            request.response_schema is not None
            and not capabilities.supports_structured_output
        ):
            raise self._capability_error("structured_output")
        maximum = capabilities.max_output_tokens
        requested = request.max_output_tokens or self.config.default_max_output_tokens
        if maximum is not None and requested is not None and requested > maximum:
            from sagents.v2.contracts.errors import (
                ErrorCategory,
                RuntimeErrorInfo,
                SageV2Error,
            )

            raise SageV2Error(
                RuntimeErrorInfo(
                    code="model.output_budget_exceeded",
                    category=ErrorCategory.VALIDATION,
                    message=(
                        f"requested output tokens {requested} exceed model limit {maximum}"
                    ),
                    safe_to_resume=True,
                )
            )

    @staticmethod
    def _capability_error(capability: str):
        from sagents.v2.contracts.errors import (
            ErrorCategory,
            RuntimeErrorInfo,
            SageV2Error,
        )

        return SageV2Error(
            RuntimeErrorInfo(
                code="model.capability_unsupported",
                category=ErrorCategory.VALIDATION,
                message=f"model binding does not support {capability}",
                safe_to_resume=True,
            )
        )

    @classmethod
    def _input_items(cls, messages: tuple[ModelMessage, ...]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": cls._plain_content(message),
                    }
                )
                continue
            replayed_reasoning = False
            if message.role == "assistant":
                state = read_provider_state(message.provider_state, "openai_responses")
                if state is not None:
                    reasoning_items = state.get("reasoning_items")
                    if isinstance(reasoning_items, list):
                        replay = [
                            dict(item)
                            for item in reasoning_items
                            if isinstance(item, dict)
                            and item.get("type") == "reasoning"
                        ]
                        items.extend(replay)
                        replayed_reasoning = bool(replay)
            if message.tool_calls:
                if message.content:
                    items.append(cls._message_item(message))
                items.extend(
                    {
                        "type": "function_call",
                        "call_id": call.tool_call_id,
                        "name": call.name,
                        "arguments": compact_json(call.arguments),
                    }
                    for call in message.tool_calls
                )
                continue
            if replayed_reasoning and not message.content:
                continue
            items.append(cls._message_item(message))
        return items

    @classmethod
    def _message_item(cls, message: ModelMessage) -> dict[str, Any]:
        role = "developer" if message.role == "developer" else message.role
        return {
            "type": "message",
            "role": role,
            "content": [
                cls._content_block(block, role=role) for block in message.content
            ],
        }

    @staticmethod
    def _content_block(block: Any, *, role: str) -> dict[str, Any]:
        text_type = "output_text" if role == "assistant" else "input_text"
        if isinstance(block, TextBlock):
            return {"type": text_type, "text": block.text}
        if isinstance(block, ImageBlock):
            return {
                "type": "input_image",
                "image_url": block.uri,
                "detail": block.detail,
            }
        if isinstance(block, FileBlock):
            return {"type": "input_file", "file_id": block.uri}
        if isinstance(block, JsonBlock):
            return {"type": text_type, "text": compact_json(block.value)}
        if isinstance(block, ResourceRefBlock):
            return {"type": text_type, "text": f"[resource: {block.uri}]"}
        if isinstance(block, AudioBlock):
            return {"type": "input_audio", "audio_url": block.uri}
        raise TypeError(f"unsupported content block {type(block)!r}")

    @classmethod
    def _plain_content(cls, message: ModelMessage) -> str:
        values = []
        for block in message.content:
            if isinstance(block, TextBlock):
                values.append(block.text)
            elif isinstance(block, JsonBlock):
                values.append(compact_json(block.value))
            else:
                values.append(str(cls._content_block(block, role="user")))
        return "\n".join(values)

    @staticmethod
    def _tool_definition(tool) -> dict[str, Any]:
        value: dict[str, Any] = {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        }
        if tool.strict is not None:
            value["strict"] = tool.strict
        if tool.output_schema is not None:
            value["output_schema"] = tool.output_schema
        return value

    @classmethod
    def _record_tool_item(
        cls,
        fragments: dict[str, dict[str, str]],
        item: Any,
        *,
        replace: bool,
    ) -> None:
        if wire_value(item, "type") != "function_call":
            return
        key = cls._tool_key(item)
        current = fragments.setdefault(key, {"id": key, "name": "", "arguments": ""})
        call_id = str(wire_value(item, "call_id", "") or "")
        name = str(wire_value(item, "name", "") or "")
        arguments = str(wire_value(item, "arguments", "") or "")
        if call_id:
            current["id"] = call_id
        if name:
            current["name"] = name
        if arguments and (replace or not current["arguments"]):
            current["arguments"] = arguments

    @classmethod
    def _record_reasoning_item(
        cls, items: dict[str, dict[str, Any]], item: Any
    ) -> None:
        if wire_value(item, "type") != "reasoning":
            return
        normalized = wire_json_value(item)
        if not isinstance(normalized, dict):
            return
        key = str(
            wire_value(item, "id", None)
            or wire_value(item, "output_index", None)
            or len(items)
        )
        items[key] = {**items.get(key, {}), **normalized}

    @staticmethod
    def _tool_key(value: Any) -> str:
        return str(
            wire_value(value, "item_id", None)
            or wire_value(value, "id", None)
            or wire_value(value, "call_id", None)
            or wire_value(value, "output_index", 0)
        )

    def _usage(self, raw: Any) -> UsageSummary:
        normalized = wire_json_value(raw)
        usage = canonical_token_usage(raw, input_mode="inclusive")
        return UsageSummary(
            reported=True,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            models=(self.config.model,),
            provider_usage=normalized if isinstance(normalized, dict) else {},
        )

    @staticmethod
    async def _close_stream(stream: Any) -> None:
        closer = getattr(stream, "close", None) or getattr(stream, "aclose", None)
        if closer is None:
            return
        result = closer()
        if hasattr(result, "__await__"):
            await result
