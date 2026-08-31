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


class OpenAICompatibleConfig(StrictModel):
    provider_id: str = "openai-compatible"
    base_url: str
    model: str
    capabilities: ModelCapabilities
    default_max_output_tokens: int | None = None
    default_temperature: float | None = None
    default_top_p: float | None = None
    reasoning_effort: str | None = None
    max_output_tokens_field: Literal["max_tokens", "max_completion_tokens"] = (
        "max_tokens"
    )
    timeout_seconds: float = 120
    extra_body: dict[str, Any] = Field(default_factory=dict)


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

    @property
    def raw_client(self) -> Any:
        """Expose the SDK client for host diagnostics and lifecycle management."""
        return self._client

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
            kwargs[self.config.max_output_tokens_field] = max_tokens
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
        usage = UsageSummary()
        tool_fragments: dict[int, dict[str, str]] = {}
        observed_choice_fields: set[str] = set()
        observed_delta_fields: set[str] = set()
        observed_delta_field_types: dict[str, set[str]] = {}
        response_started = False
        try:
            upstream = await self._client.chat.completions.create(**kwargs)
            async for chunk in upstream:
                response_id = str(wire_value(chunk, "id") or response_id)
                raw_usage = wire_value(chunk, "usage")
                if raw_usage is not None:
                    prompt_details = wire_value(raw_usage, "prompt_tokens_details")
                    completion_details = wire_value(
                        raw_usage, "completion_tokens_details"
                    )
                    usage = UsageSummary(
                        input_tokens=int(
                            wire_value(raw_usage, "prompt_tokens", 0) or 0
                        ),
                        output_tokens=int(
                            wire_value(raw_usage, "completion_tokens", 0) or 0
                        ),
                        cached_input_tokens=int(
                            wire_value(prompt_details, "cached_tokens", 0)
                            or 0
                        ),
                        reasoning_tokens=int(
                            wire_value(completion_details, "reasoning_tokens", 0)
                            or 0
                        ),
                        models=(self.config.model,),
                    )
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
                    latest_reasoning_details = wire_value(
                        delta, "reasoning_details"
                    )
                    if latest_reasoning_details is None:
                        latest_reasoning_details = wire_value(
                            wire_value(choice, "message"), "reasoning_details"
                        )
                    if latest_reasoning_details is not None:
                        # Providers that stream this field commonly send a
                        # cumulative structure. Preserve the latest complete
                        # value rather than concatenating duplicate chunks.
                        reasoning_details = wire_json_value(
                            latest_reasoning_details
                        )
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
                },
                provider_state=make_provider_state(
                    "openai_compatible",
                    {
                        **(
                            {"reasoning_content": reasoning}
                            if reasoning
                            else {}
                        ),
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
            state = read_provider_state(
                message.provider_state, "openai_compatible"
            )
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
