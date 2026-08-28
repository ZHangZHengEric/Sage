"""SAgents V2 module for model/plugins/openai_compatible.py."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
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
        if request.response_schema is not None:
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
        response_id = new_id("model_response")
        finish_reason = "unknown"
        usage = UsageSummary()
        tool_fragments: dict[int, dict[str, str]] = {}
        try:
            upstream = await self._client.chat.completions.create(**kwargs)
            async for chunk in upstream:
                response_id = str(getattr(chunk, "id", None) or response_id)
                raw_usage = getattr(chunk, "usage", None)
                if raw_usage is not None:
                    usage = UsageSummary(
                        input_tokens=int(getattr(raw_usage, "prompt_tokens", 0) or 0),
                        output_tokens=int(
                            getattr(raw_usage, "completion_tokens", 0) or 0
                        ),
                        cached_input_tokens=int(
                            getattr(
                                getattr(raw_usage, "prompt_tokens_details", None),
                                "cached_tokens",
                                0,
                            )
                            or 0
                        ),
                        reasoning_tokens=int(
                            getattr(
                                getattr(raw_usage, "completion_tokens_details", None),
                                "reasoning_tokens",
                                0,
                            )
                            or 0
                        ),
                        models=(self.config.model,),
                    )
                choices = getattr(chunk, "choices", None) or ()
                for choice in choices:
                    if getattr(choice, "finish_reason", None):
                        finish_reason = str(choice.finish_reason)
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue
                    reasoning_content = getattr(delta, "reasoning_content", None)
                    if reasoning_content:
                        reasoning += str(reasoning_content)
                        yield ModelStreamEvent(
                            kind=ModelEventKind.REASONING_DELTA,
                            delta=str(reasoning_content),
                        )
                    content = getattr(delta, "content", None)
                    if content:
                        text += str(content)
                        yield ModelStreamEvent(
                            kind=ModelEventKind.TEXT_DELTA, delta=str(content)
                        )
                    for tool_delta in getattr(delta, "tool_calls", None) or ():
                        index = int(getattr(tool_delta, "index", 0) or 0)
                        accumulator = tool_fragments.setdefault(
                            index, {"id": "", "name": "", "arguments": ""}
                        )
                        tool_id = getattr(tool_delta, "id", None)
                        if tool_id:
                            accumulator["id"] += str(tool_id)
                        function = getattr(tool_delta, "function", None)
                        if function is not None:
                            name = getattr(function, "name", None)
                            arguments = getattr(function, "arguments", None)
                            if name:
                                accumulator["name"] += str(name)
                            if arguments:
                                accumulator["arguments"] += str(arguments)
        except SageV2Error:
            raise
        except Exception as exc:
            raise self._provider_error(exc) from exc
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
            ),
        )

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

    @staticmethod
    def _provider_error(exc: Exception) -> SageV2Error:
        status = getattr(exc, "status_code", None)
        retryable = status in {408, 409, 429} or (
            isinstance(status, int) and status >= 500
        )
        return SageV2Error(
            RuntimeErrorInfo(
                code="model.provider_transient"
                if retryable
                else "model.provider_permanent",
                category=(
                    ErrorCategory.PROVIDER_TRANSIENT
                    if retryable
                    else ErrorCategory.PROVIDER_PERMANENT
                ),
                message=str(exc),
                retryable=retryable,
                safe_to_resume=True,
                provider_code=str(status) if status is not None else None,
            )
        )


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
