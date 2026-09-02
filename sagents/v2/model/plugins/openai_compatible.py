"""SAgents V2 module for model/plugins/openai_compatible.py."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import Field

from sagents.v2.runtime.credentials.contracts import CredentialMaterial
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.contracts.common import StrictModel, new_id
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
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
from sagents.v2.model.wire import provider_error, wire_json_value, wire_value


def default_chat_completion_token_field(
    model: str,
) -> Literal["max_tokens", "max_completion_tokens"]:
    """Choose the first wire field to try for an unprobed compatible route."""

    normalized = str(model or "").strip().lower()
    if normalized.startswith(("gpt-5", "o1", "o3", "o4")):
        return "max_completion_tokens"
    return "max_tokens"


class OpenAICompatibleConfig(StrictModel):
    provider_id: str = "openai-compatible"
    base_url: str
    model: str
    capabilities: ModelCapabilities
    default_max_output_tokens: int | None = None
    default_temperature: float | None = None
    default_top_p: float | None = None
    reasoning_effort: str | None = None
    max_output_tokens_field: Literal["auto", "max_tokens", "max_completion_tokens"] = (
        "auto"
    )
    timeout_seconds: float = 120
    extra_body: dict[str, Any] = Field(default_factory=dict)
    reasoning_parameter_fallback: bool = False


class OpenAICompatibleModelProvider:
    """Chat Completions streaming adapter with normalized v2 model events."""

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        credential: CredentialMaterial | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        if client is None and credential is None:
            raise ValueError("credential is required when client is not injected")
        self.config = config
        if client is not None:
            self._client = client
        else:
            assert credential is not None
            self._client = AsyncOpenAI(
                api_key=credential.secret.get_secret_value(),
                base_url=config.base_url,
                timeout=config.timeout_seconds,
            )
        # Capability declarations describe the model, but OpenAI-compatible
        # gateways may still reject otherwise valid reasoning controls. Learn
        # that route behavior after one bounded compatibility retry so later
        # requests from the same provider instance omit the rejected fields.
        self._rejected_reasoning_controls: set[str] = set()
        # ``max_tokens`` and ``max_completion_tokens`` are both output-budget
        # fields, but compatible gateways do not expose a portable capability
        # flag for selecting between them. In auto mode, start with the model-
        # family preference, retry the alternate field only after an explicit
        # pre-stream 400/422 rejection, and remember the accepted route dialect.
        self._resolved_max_output_tokens_field: (
            Literal["max_tokens", "max_completion_tokens"] | None
        ) = None

    @property
    def raw_client(self) -> Any:
        """Expose the SDK client for host diagnostics and lifecycle management."""
        return self._client

    @property
    def resolved_max_output_tokens_field(
        self,
    ) -> Literal["max_tokens", "max_completion_tokens"] | None:
        """Return the field accepted by a completed request on this route."""

        return self._resolved_max_output_tokens_field

    async def capabilities(self, model_binding: str) -> ModelCapabilities:
        return self.config.capabilities

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        return self._stream(request)

    def diagnostic_request(self, request: ModelRequest) -> dict[str, Any]:
        """Return the exact non-secret payload passed to the OpenAI SDK."""
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": [self._message(message) for message in request.messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.tools:
            kwargs["tools"] = []
            for tool in request.tools:
                function: dict[str, Any] = {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                }
                if tool.strict is not None:
                    function["strict"] = tool.strict
                if tool.output_schema is not None:
                    function["returns"] = tool.output_schema
                kwargs["tools"].append({"type": "function", "function": function})
            if request.tool_choice is not None:
                kwargs["tool_choice"] = request.tool_choice
        max_tokens = request.max_output_tokens or self.config.default_max_output_tokens
        if max_tokens is not None:
            kwargs[self._effective_max_output_tokens_field()] = max_tokens
        temperature = (
            request.temperature
            if request.temperature is not None
            else self.config.default_temperature
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        if self.config.default_top_p is not None:
            kwargs["top_p"] = self.config.default_top_p
        if request.response_format == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        elif request.response_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "sage_response",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        extra_body = dict(self.config.extra_body)
        if self.config.reasoning_effort is not None:
            extra_body.setdefault("reasoning_effort", self.config.reasoning_effort)
        extra_body = self._without_rejected_reasoning_controls(extra_body)
        if extra_body:
            kwargs["extra_body"] = extra_body
        return kwargs

    async def _stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        """Accumulate provider deltas into one normalized completed response.

        Fragmented tool ids, names, and JSON arguments are joined by provider
        index. Canonical Runtime Item ids and lifecycle events are intentionally
        left to AgentLoopEngine.
        """

        self._validate_request(request)
        kwargs = self.diagnostic_request(request)

        upstream = None
        text = ""
        reasoning = ""
        reasoning_details: Any = None
        response_id = new_id("model_response")
        finish_reason = "unknown"
        usage = UsageSummary(models=(self.config.model,))
        tool_fragments: dict[int, dict[str, str]] = {}
        observed_choice_fields: set[str] = set()
        observed_delta_fields: set[str] = set()
        observed_delta_field_types: dict[str, set[str]] = {}
        response_started = False
        compatibility_fallback: dict[str, Any] | None = None
        try:
            (
                upstream,
                compatibility_fallback,
            ) = await self._create_with_compatibility_negotiation(kwargs)
            async for chunk in upstream:
                response_id = str(wire_value(chunk, "id") or response_id)
                raw_usage = wire_value(chunk, "usage")
                if raw_usage is not None:
                    usage = self._usage(raw_usage)
                choices = wire_value(chunk, "choices", ()) or ()
                for choice in choices:
                    observed_choice_fields.update(self._wire_field_names(choice))
                    choice_finish_reason = wire_value(choice, "finish_reason")
                    if choice_finish_reason:
                        finish_reason = str(choice_finish_reason)
                    delta = wire_value(choice, "delta")
                    if delta is None:
                        delta = {}
                    delta_fields = self._wire_field_names(delta)
                    observed_delta_fields.update(delta_fields)
                    for field in delta_fields:
                        observed_delta_field_types.setdefault(field, set()).add(
                            self._wire_type_name(wire_value(delta, field))
                        )
                    reasoning_content = self._first_wire_text(
                        delta,
                        "reasoning_content",
                        "reasoning",
                        "thinking",
                        "analysis",
                    )
                    if not reasoning_content and not reasoning:
                        reasoning_content = self._first_wire_text(
                            wire_value(choice, "message"),
                            "reasoning_content",
                            "reasoning",
                            "thinking",
                            "analysis",
                        )
                    if reasoning_content:
                        reasoning, reasoning_delta = self._merge_stream_text(
                            reasoning, reasoning_content
                        )
                        if reasoning_delta:
                            response_started = True
                            yield ModelStreamEvent(
                                kind=ModelEventKind.REASONING_DELTA,
                                delta=reasoning_delta,
                            )
                    latest_reasoning_details = wire_value(delta, "reasoning_details")
                    if latest_reasoning_details is None:
                        latest_reasoning_details = wire_value(
                            wire_value(choice, "message"), "reasoning_details"
                        )
                    if latest_reasoning_details is not None:
                        # Providers that stream this field commonly send a
                        # cumulative structure. Preserve the latest complete
                        # value rather than concatenating duplicate chunks.
                        reasoning_details = wire_json_value(latest_reasoning_details)
                    content = self._first_wire_text(delta, "content", "text")
                    if not content and not text:
                        content = self._first_wire_text(choice, "text")
                    if not content and not text:
                        content = self._first_wire_text(
                            wire_value(choice, "message"), "content", "text"
                        )
                    if not content and not text:
                        content = self._first_wire_text(delta, "refusal")
                    if content:
                        response_started = True
                        text += content
                        yield ModelStreamEvent(
                            kind=ModelEventKind.TEXT_DELTA, delta=content
                        )
                    for tool_delta in wire_value(delta, "tool_calls", ()) or ():
                        response_started = True
                        index = int(wire_value(tool_delta, "index", 0) or 0)
                        accumulator = tool_fragments.setdefault(
                            index, {"id": "", "name": "", "arguments": ""}
                        )
                        tool_id = wire_value(tool_delta, "id")
                        if tool_id:
                            accumulator["id"] += str(tool_id)
                        function = wire_value(tool_delta, "function")
                        if function is not None:
                            name = wire_value(function, "name")
                            arguments = wire_value(function, "arguments")
                            if name:
                                accumulator["name"] += str(name)
                            if arguments:
                                accumulator["arguments"] += str(arguments)
        except SageV2Error:
            raise
        except Exception as exc:
            raise provider_error(exc, response_started=response_started) from exc
        finally:
            if upstream is not None:
                closer = getattr(upstream, "close", None) or getattr(
                    upstream, "aclose", None
                )
                if closer is not None:
                    result = closer()
                    if hasattr(result, "__await__"):
                        await result

        tool_calls: list[ModelToolCall] = []
        for index in sorted(tool_fragments):
            fragment = tool_fragments[index]
            try:
                arguments = json.loads(fragment["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="model.tool_arguments_invalid_json",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                        message=f"model returned invalid tool arguments: {exc}",
                        safe_to_resume=True,
                    )
                ) from exc
            if not isinstance(arguments, dict):
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="model.tool_arguments_not_object",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                        message="model tool arguments must decode to an object",
                        safe_to_resume=True,
                    )
                )
            tool_calls.append(
                ModelToolCall(
                    tool_call_id=fragment["id"] or new_id("tool_call"),
                    name=fragment["name"],
                    arguments=arguments,
                )
            )
        if (
            usage.output_tokens > 0
            and not text.strip()
            and not reasoning.strip()
            and not tool_calls
        ):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="model.empty_semantic_response",
                    category=ErrorCategory.PROVIDER_TRANSIENT,
                    message=(
                        "provider reported output tokens but returned no supported "
                        "text, reasoning, or Tool call fields"
                    ),
                    retryable=True,
                    safe_to_resume=True,
                    metadata={
                        "output_tokens": usage.output_tokens,
                        "finish_reason": finish_reason,
                        "observed_choice_fields": sorted(observed_choice_fields),
                        "observed_delta_fields": sorted(observed_delta_fields),
                        "observed_delta_field_types": {
                            key: sorted(values)
                            for key, values in sorted(
                                observed_delta_field_types.items()
                            )
                        },
                    },
                )
            )
        yield ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(
                response_id=response_id,
                text=text,
                reasoning=reasoning,
                tool_calls=tuple(tool_calls),
                finish_reason=finish_reason,
                usage=usage,
                provider_metadata={
                    "provider_id": self.config.provider_id,
                    "model": self.config.model,
                    **(
                        {"compatibility_fallback": compatibility_fallback}
                        if compatibility_fallback is not None
                        else {}
                    ),
                },
                provider_state=make_provider_state(
                    "openai_compatible",
                    {
                        **({"reasoning_content": reasoning} if reasoning else {}),
                        **(
                            {"reasoning_details": reasoning_details}
                            if reasoning_details is not None
                            else {}
                        ),
                    },
                )
                if reasoning or reasoning_details is not None
                else {},
            ),
        )

    async def _create_with_compatibility_negotiation(
        self,
        kwargs: dict[str, Any],
    ) -> tuple[Any, dict[str, Any] | None]:
        """Create one stream with bounded pre-stream dialect negotiation."""

        current = kwargs
        fallbacks: list[dict[str, Any]] = []
        reasoning_fallback_used = False
        token_fallback_used = False
        while True:
            try:
                upstream = await self._client.chat.completions.create(**current)
                self._learn_output_token_field(current)
                if not fallbacks:
                    return upstream, None
                if len(fallbacks) == 1:
                    return upstream, fallbacks[0]
                return upstream, {
                    "kind": "provider_dialect_negotiated",
                    "attempts": fallbacks,
                }
            except Exception as exc:
                if not token_fallback_used:
                    fallback, change = self._token_field_fallback_request(current, exc)
                    if fallback is not None:
                        current = fallback
                        token_fallback_used = True
                        fallbacks.append(change)
                        continue
                if not reasoning_fallback_used:
                    fallback, removed = self._reasoning_fallback_request(current, exc)
                    if fallback is not None:
                        current = fallback
                        reasoning_fallback_used = True
                        self._rejected_reasoning_controls.update(removed)
                        fallbacks.append(
                            {
                                "kind": "reasoning_controls_omitted",
                                "removed": sorted(removed),
                                "provider_status": self._provider_status(exc),
                            }
                        )
                        continue
                raise

    def _effective_max_output_tokens_field(
        self,
    ) -> Literal["max_tokens", "max_completion_tokens"]:
        configured = self.config.max_output_tokens_field
        if configured != "auto":
            return configured
        return self._resolved_max_output_tokens_field or (
            default_chat_completion_token_field(self.config.model)
        )

    def _learn_output_token_field(self, kwargs: Mapping[str, Any]) -> None:
        if self.config.max_output_tokens_field != "auto":
            return
        for field in ("max_tokens", "max_completion_tokens"):
            if field in kwargs:
                self._resolved_max_output_tokens_field = field
                return

    def _token_field_fallback_request(
        self,
        kwargs: dict[str, Any],
        exc: Exception,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Swap output-budget wire fields after a compatible-route rejection."""

        if self.config.max_output_tokens_field != "auto":
            return None, {}
        status = self._provider_status(exc)
        if status not in {400, 422} or not self._token_field_rejection(exc):
            return None, {}
        current = next(
            (
                field
                for field in ("max_tokens", "max_completion_tokens")
                if field in kwargs
            ),
            None,
        )
        if current is None:
            return None, {}
        alternate = "max_completion_tokens" if current == "max_tokens" else "max_tokens"
        fallback = dict(kwargs)
        value = fallback.pop(current)
        fallback[alternate] = value
        return fallback, {
            "kind": "output_token_field_switched",
            "from": current,
            "to": alternate,
            "provider_status": status,
        }

    @staticmethod
    def _token_field_rejection(exc: Exception) -> bool:
        text = str(exc).lower()
        if "max_tokens" in text or "max_completion_tokens" in text:
            return True
        # Do not reinterpret an error that explicitly identifies a different
        # optional parameter. Generic compatible-gateway rejections often hide
        # the rejected field, so those remain eligible for one bounded retry.
        unrelated = (
            "response_format",
            "temperature",
            "top_p",
            "tool_choice",
            "tools",
            "reasoning_effort",
            "enable_thinking",
            "credential",
            "api key",
            "authentication",
            "authorization",
        )
        if any(name in text for name in unrelated):
            return False
        return any(
            marker in text
            for marker in (
                "provider rejected",
                "request rejected",
                "bad request",
                "unprocessable entity",
            )
        )

    def _reasoning_fallback_request(
        self,
        kwargs: dict[str, Any],
        exc: Exception,
    ) -> tuple[dict[str, Any] | None, set[str]]:
        """Remove rejected optional reasoning controls and retry exactly once."""

        if not self.config.reasoning_parameter_fallback:
            return None, set()
        if self._provider_status(exc) not in {400, 422}:
            return None, set()
        extra_body = kwargs.get("extra_body")
        if not isinstance(extra_body, Mapping):
            return None, set()
        cleaned, removed = self._strip_reasoning_controls(dict(extra_body))
        if not removed:
            return None, set()
        fallback = dict(kwargs)
        if cleaned:
            fallback["extra_body"] = cleaned
        else:
            fallback.pop("extra_body", None)
        return fallback, removed

    def _without_rejected_reasoning_controls(
        self, extra_body: dict[str, Any]
    ) -> dict[str, Any]:
        if not self._rejected_reasoning_controls:
            return extra_body
        cleaned = dict(extra_body)
        for name in self._rejected_reasoning_controls:
            if name == "chat_template_kwargs.enable_thinking":
                template = cleaned.get("chat_template_kwargs")
                if isinstance(template, Mapping):
                    template = dict(template)
                    template.pop("enable_thinking", None)
                    if template:
                        cleaned["chat_template_kwargs"] = template
                    else:
                        cleaned.pop("chat_template_kwargs", None)
                continue
            cleaned.pop(name, None)
        return cleaned

    @staticmethod
    def _strip_reasoning_controls(
        extra_body: dict[str, Any],
    ) -> tuple[dict[str, Any], set[str]]:
        cleaned = dict(extra_body)
        removed: set[str] = set()
        for name in ("reasoning_effort", "enable_thinking", "thinking"):
            if name in cleaned:
                cleaned.pop(name, None)
                removed.add(name)
        template = cleaned.get("chat_template_kwargs")
        if isinstance(template, Mapping) and "enable_thinking" in template:
            template = dict(template)
            template.pop("enable_thinking", None)
            removed.add("chat_template_kwargs.enable_thinking")
            if template:
                cleaned["chat_template_kwargs"] = template
            else:
                cleaned.pop("chat_template_kwargs", None)
        return cleaned, removed

    @staticmethod
    def _provider_status(exc: Exception) -> int | None:
        status = getattr(exc, "status_code", None)
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        return status if isinstance(status, int) else None

    @classmethod
    def _first_wire_text(cls, value: Any, *names: str) -> str:
        if value is None:
            return ""
        for name in names:
            item = wire_value(value, name)
            text = cls._coerce_wire_text(item)
            if text:
                return text
        return ""

    def _usage(self, raw: Any) -> UsageSummary:
        """Normalize common Chat Completions and Responses-style usage keys."""

        prompt_details = wire_value(raw, "prompt_tokens_details")
        completion_details = wire_value(raw, "completion_tokens_details")
        input_details = wire_value(raw, "input_tokens_details")
        output_details = wire_value(raw, "output_tokens_details")
        normalized = wire_json_value(raw)
        return UsageSummary(
            reported=True,
            input_tokens=self._first_usage_int(raw, "prompt_tokens", "input_tokens"),
            output_tokens=self._first_usage_int(
                raw, "completion_tokens", "output_tokens"
            ),
            cached_input_tokens=self._first_usage_int(
                prompt_details,
                "cached_tokens",
                fallback_values=(
                    wire_value(input_details, "cached_tokens"),
                    wire_value(raw, "cached_input_tokens"),
                    wire_value(raw, "cache_read_input_tokens"),
                ),
            ),
            reasoning_tokens=self._first_usage_int(
                completion_details,
                "reasoning_tokens",
                fallback_values=(
                    wire_value(output_details, "reasoning_tokens"),
                    wire_value(raw, "reasoning_tokens"),
                ),
            ),
            models=(self.config.model,),
            provider_usage=normalized if isinstance(normalized, dict) else {},
        )

    @staticmethod
    def _first_usage_int(
        raw: Any,
        *names: str,
        fallback_values: tuple[Any, ...] = (),
    ) -> int:
        for name in names:
            value = wire_value(raw, name)
            if value is not None:
                return int(value)
        for value in fallback_values:
            if value is not None:
                return int(value)
        return 0

    @staticmethod
    def _merge_stream_text(accumulated: str, incoming: str) -> tuple[str, str]:
        """Normalize providers that stream cumulative reasoning snapshots."""

        if accumulated and incoming.startswith(accumulated):
            return incoming, incoming[len(accumulated) :]
        return accumulated + incoming, incoming

    @classmethod
    def _coerce_wire_text(cls, value: Any) -> str:
        """Accept common structured Chat Completions content-part shapes."""

        if isinstance(value, str):
            return value
        if isinstance(value, (list, tuple)):
            return "".join(cls._coerce_wire_text(item) for item in value)
        if isinstance(value, Mapping):
            part_type = str(value.get("type") or "").lower()
            if part_type and part_type not in {
                "text",
                "output_text",
                "reasoning",
                "reasoning_text",
                "thinking",
            }:
                return ""
            for key in ("text", "content", "value"):
                text = cls._coerce_wire_text(value.get(key))
                if text:
                    return text
            return ""
        dumper = getattr(value, "model_dump", None)
        if callable(dumper):
            dumped = dumper(exclude_none=True)
            if isinstance(dumped, Mapping):
                return cls._coerce_wire_text(dumped)
        return ""

    @staticmethod
    def _wire_field_names(value: Any) -> set[str]:
        if isinstance(value, Mapping):
            return {str(key) for key in value}
        dumper = getattr(value, "model_dump", None)
        if callable(dumper):
            dumped = dumper(exclude_none=True)
            if isinstance(dumped, dict):
                return {str(key) for key in dumped}
        attributes = getattr(value, "__dict__", None)
        if isinstance(attributes, dict):
            return {str(key) for key in attributes if not str(key).startswith("_")}
        return set()

    @staticmethod
    def _wire_type_name(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, str):
            return "string"
        if isinstance(value, Mapping):
            return "object"
        if isinstance(value, (list, tuple)):
            return "array"
        return type(value).__name__

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
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="model.output_budget_exceeded",
                    category=ErrorCategory.VALIDATION,
                    message=f"requested output tokens {requested} exceed model limit {maximum}",
                    safe_to_resume=True,
                )
            )

    @staticmethod
    def _capability_error(capability: str) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code="model.capability_unsupported",
                category=ErrorCategory.VALIDATION,
                message=f"model binding does not support {capability}",
                safe_to_resume=True,
            )
        )

    @classmethod
    def _message(cls, message: ModelMessage) -> dict[str, Any]:
        value: dict[str, Any] = {"role": message.role}
        if message.role == "assistant":
            state = read_provider_state(message.provider_state, "openai_compatible")
            if state is not None:
                for key in ("reasoning_content", "reasoning_details"):
                    if key in state:
                        value[key] = state[key]
        if message.role == "tool":
            value["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            value["tool_calls"] = [
                {
                    "id": call.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ),
                    },
                }
                for call in message.tool_calls
            ]
        parts = [cls._content_block(block) for block in message.content]
        if len(parts) == 1 and parts[0].get("type") == "text":
            value["content"] = parts[0]["text"]
        else:
            value["content"] = parts
        return value

    @staticmethod
    def _content_block(block) -> dict[str, Any]:
        if isinstance(block, TextBlock):
            return {"type": "text", "text": block.text}
        if isinstance(block, ImageBlock):
            return {"type": "image_url", "image_url": {"url": block.uri}}
        if isinstance(block, AudioBlock):
            return {"type": "input_audio", "input_audio": {"data": block.uri}}
        if isinstance(block, FileBlock):
            return {"type": "file", "file": {"file_id": block.uri}}
        if isinstance(block, JsonBlock):
            return {
                "type": "text",
                "text": json.dumps(block.value, ensure_ascii=False),
            }
        if isinstance(block, ResourceRefBlock):
            return {"type": "text", "text": f"[resource: {block.uri}]"}
        raise TypeError(f"unsupported content block {type(block)!r}")


class OpenAIChatCompletionsConfig(OpenAICompatibleConfig):
    """Explicitly named configuration for the Chat Completions wire protocol.

    `OpenAICompatibleConfig` remains a source-compatible alias for hosts that
    already use the v2 preview API.  New manifests should use the explicit
    `openai-chat-completions` provider id so the selected wire protocol is not
    ambiguous.
    """

    provider_id: str = "openai-chat-completions"


class OpenAIChatCompletionsModelProvider(OpenAICompatibleModelProvider):
    """Named Chat Completions adapter; behavior is implemented by its base."""

    plugin_id = "sage.model.openai-chat-completions"
    name = "OpenAI Chat Completions"
    description = "Streams chat messages and function calls through /chat/completions."
