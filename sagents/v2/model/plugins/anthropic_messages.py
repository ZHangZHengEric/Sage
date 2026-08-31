"""Anthropic Messages API adapter implemented against the public HTTP protocol."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from pydantic import Field

from sagents.v2.contracts.common import StrictModel, new_id
from sagents.v2.contracts.errors import SageV2Error
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
)
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
)


class AnthropicMessagesConfig(StrictModel):
    provider_id: str = "anthropic-messages"
    base_url: str = "https://api.anthropic.com"
    model: str
    capabilities: ModelCapabilities
    anthropic_version: str = "2023-06-01"
    default_max_output_tokens: int = Field(default=4096, gt=0)
    default_temperature: float | None = None
    default_top_p: float | None = None
    reasoning_effort: str | None = None
    timeout_seconds: float = 120
    prompt_cache: bool = True
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class AnthropicMessagesModelProvider:
    """Normalize Anthropic SSE content blocks into v2 stream events.

    Claude uses a top-level system field and embeds `tool_use`/`tool_result`
    blocks inside assistant/user messages.  The explicit mapper below preserves
    those semantics instead of routing Claude through an OpenAI-compatible shim.
    """

    def __init__(
        self,
        config: AnthropicMessagesConfig,
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
                base_url=config.base_url,
                timeout=config.timeout_seconds,
                headers={
                    "x-api-key": credential.secret.get_secret_value(),
                    "anthropic-version": config.anthropic_version,
                    "content-type": "application/json",
                    **config.extra_headers,
                },
            )

    @property
    def raw_client(self) -> Any:
        return self._client

    async def capabilities(self, model_binding: str) -> ModelCapabilities:
        return self.config.capabilities

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        return self._stream(request)

    def diagnostic_request(self, request: ModelRequest) -> dict[str, Any]:
        self._validate_request(request)
        system, messages = self._messages(request.messages)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": request.max_output_tokens
            or self.config.default_max_output_tokens,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if request.tools:
            payload["tools"] = [self._tool_definition(tool) for tool in request.tools]
            if self.config.prompt_cache:
                payload["tools"][-1]["cache_control"] = {"type": "ephemeral"}
            if request.tool_choice is not None:
                payload["tool_choice"] = {
                    "type": {
                        "auto": "auto",
                        "required": "any",
                        "none": "none",
                    }[request.tool_choice]
                }
        if self.config.reasoning_effort is None:
            temperature = (
                request.temperature
                if request.temperature is not None
                else self.config.default_temperature
            )
            if temperature is not None:
                payload["temperature"] = temperature
            if self.config.default_top_p is not None:
                payload["top_p"] = self.config.default_top_p
        output_config: dict[str, Any] = {}
        if self.config.reasoning_effort is not None:
            effort = (
                "low"
                if self.config.reasoning_effort == "minimal"
                else self.config.reasoning_effort
            )
            payload["thinking"] = {"type": "adaptive", "display": "summarized"}
            output_config["effort"] = effort
        if request.response_format == "json_object":
            # Anthropic Messages has no generic JSON-object response mode; the
            # unchanged V1 prompt remains the format contract for this route.
            pass
        elif request.response_schema is not None:
            output_config["format"] = {
                "type": "json_schema",
                "schema": request.response_schema,
            }
        if output_config:
            payload["output_config"] = output_config
        payload.update(self.config.extra_body)
        return payload

    async def _stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        payload = self.diagnostic_request(request)
        response_id = new_id("model_response")
        text = ""
        reasoning = ""
        finish_reason = "end_turn"
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        tools: dict[int, dict[str, str]] = {}
        thinking_blocks: dict[int, dict[str, Any]] = {}
        response_started = False
        try:
            async with self._open_stream(payload) as response:
                raise_for_status = getattr(response, "raise_for_status", None)
                if raise_for_status is not None:
                    raise_for_status()
                async for event in self._events(response):
                    event_type = str(event.get("type") or "")
                    if event_type == "message_start":
                        message = event.get("message") or {}
                        response_id = str(message.get("id") or response_id)
                        usage = message.get("usage") or {}
                        input_tokens = int(usage.get("input_tokens") or 0)
                        cached_tokens = int(usage.get("cache_read_input_tokens") or 0)
                    elif event_type == "content_block_start":
                        index = int(event.get("index") or 0)
                        block = event.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            response_started = True
                            tools[index] = {
                                "id": str(block.get("id") or new_id("tool_call")),
                                "name": str(block.get("name") or ""),
                                "arguments": compact_json(block.get("input") or {}),
                            }
                        elif block.get("type") in {
                            "thinking",
                            "redacted_thinking",
                        }:
                            response_started = True
                            thinking_blocks[index] = {
                                key: value
                                for key, value in block.items()
                                if key in {"type", "thinking", "signature", "data"}
                            }
                    elif event_type == "content_block_delta":
                        index = int(event.get("index") or 0)
                        delta = event.get("delta") or {}
                        delta_type = delta.get("type")
                        if delta_type == "text_delta":
                            value = str(delta.get("text") or "")
                            if value:
                                response_started = True
                                text += value
                                yield ModelStreamEvent(
                                    kind=ModelEventKind.TEXT_DELTA, delta=value
                                )
                        elif delta_type == "thinking_delta":
                            value = str(delta.get("thinking") or "")
                            if value:
                                response_started = True
                                reasoning += value
                                yield ModelStreamEvent(
                                    kind=ModelEventKind.REASONING_DELTA, delta=value
                                )
                            block = thinking_blocks.setdefault(
                                index, {"type": "thinking", "thinking": ""}
                            )
                            block["thinking"] = str(block.get("thinking") or "") + value
                        elif delta_type == "signature_delta":
                            block = thinking_blocks.setdefault(
                                index, {"type": "thinking", "thinking": ""}
                            )
                            block["signature"] = str(
                                block.get("signature") or ""
                            ) + str(delta.get("signature") or "")
                        elif delta_type == "input_json_delta":
                            fragment = tools.setdefault(
                                index,
                                {
                                    "id": new_id("tool_call"),
                                    "name": "",
                                    "arguments": "",
                                },
                            )
                            # A tool-use start block carries `{}` before deltas.
                            if fragment["arguments"] == "{}":
                                fragment["arguments"] = ""
                            fragment["arguments"] += str(
                                delta.get("partial_json") or ""
                            )
                    elif event_type == "message_delta":
                        delta = event.get("delta") or {}
                        finish_reason = str(delta.get("stop_reason") or finish_reason)
                        usage = event.get("usage") or {}
                        output_tokens = int(usage.get("output_tokens") or output_tokens)
        except SageV2Error:
            raise
        except Exception as exc:
            raise provider_error(exc, response_started=response_started) from exc

        calls = tuple(
            parse_tool_arguments(
                value["arguments"], tool_call_id=value["id"], name=value["name"]
            )
            for _, value in sorted(tools.items())
        )
        yield ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(
                response_id=response_id,
                text=text,
                reasoning=reasoning,
                tool_calls=calls,
                finish_reason=finish_reason,
                usage=UsageSummary(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_input_tokens=cached_tokens,
                    models=(self.config.model,),
                ),
                provider_metadata={
                    "provider_id": self.config.provider_id,
                    "model": self.config.model,
                    "api": "anthropic-messages",
                },
                provider_state=make_provider_state(
                    "anthropic_messages",
                    {
                        "thinking_blocks": [
                            thinking_blocks[index]
                            for index in sorted(thinking_blocks)
                        ]
                    },
                )
                if thinking_blocks
                else {},
            ),
        )

    @asynccontextmanager
    async def _open_stream(self, payload: dict[str, Any]):
        """Accept both httpx clients and small injected protocol test clients."""

        stream = self._client.stream("POST", "/v1/messages", json=payload)
        async with stream as response:
            yield response

    @staticmethod
    async def _events(response: Any) -> AsyncIterator[dict[str, Any]]:
        """Decode SSE data records; event-name lines are advisory duplicates."""

        async for line in response.aiter_lines():
            line = line.strip()
            if not line or line.startswith("event:") or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            value = json.loads(data)
            if isinstance(value, dict):
                yield value

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
        if maximum is not None and requested > maximum:
            from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo

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
    def _capability_error(capability: str) -> SageV2Error:
        from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo

        return SageV2Error(
            RuntimeErrorInfo(
                code="model.capability_unsupported",
                category=ErrorCategory.VALIDATION,
                message=f"model binding does not support {capability}",
                safe_to_resume=True,
            )
        )

    def _messages(
        self, messages: tuple[ModelMessage, ...]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        system: list[dict[str, Any]] = []
        output: list[dict[str, Any]] = []
        cache_candidates: dict[str, dict[str, Any]] = {}
        for message in messages:
            if message.role in {"system", "developer"}:
                for block in message.content:
                    system.append(
                        {"type": "text", "text": self._block_text(block)}
                    )
                self._remember_cache_candidate(
                    message, system, cache_candidates
                )
                continue
            if message.role == "tool":
                tool_result_content: list[dict[str, Any]] = [
                    {
                        "type": "tool_result",
                        "tool_use_id": message.tool_call_id,
                        "content": self._plain_content(message),
                    }
                ]
                self._append_message(output, "user", tool_result_content)
                self._remember_cache_candidate(
                    message, tool_result_content, cache_candidates
                )
                continue
            content: list[dict[str, Any]] = [
                self._content_block(block) for block in message.content
            ]
            if message.role == "assistant":
                state = read_provider_state(
                    message.provider_state, "anthropic_messages"
                )
                if state is not None:
                    stored_blocks = state.get("thinking_blocks")
                    if isinstance(stored_blocks, list):
                        content = [
                            dict(block)
                            for block in stored_blocks
                            if isinstance(block, dict)
                            and block.get("type")
                            in {"thinking", "redacted_thinking"}
                        ] + content
            if message.tool_calls:
                content.extend(
                    {
                        "type": "tool_use",
                        "id": call.tool_call_id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                    for call in message.tool_calls
                )
            self._append_message(output, message.role, content)
            self._remember_cache_candidate(message, content, cache_candidates)
        if self.config.prompt_cache:
            for segment in ("stable", "semi_stable"):
                candidate = cache_candidates.get(segment)
                if candidate is not None:
                    candidate["cache_control"] = {"type": "ephemeral"}
        return system, output

    @staticmethod
    def _remember_cache_candidate(message, content, candidates) -> None:
        segment = message.metadata.get("cache_segment")
        if segment in {"stable", "semi_stable"} and content:
            candidates[str(segment)] = content[-1]

    @staticmethod
    def _append_message(
        messages: list[dict[str, Any]], role: str, content: list[dict[str, Any]]
    ) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError(f"Anthropic message role is not supported: {role}")
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(content)
        else:
            messages.append({"role": role, "content": content})

    @classmethod
    def _plain_content(cls, message: ModelMessage) -> str:
        return "\n".join(cls._block_text(block) for block in message.content)

    @staticmethod
    def _block_text(block: Any) -> str:
        if isinstance(block, TextBlock):
            return block.text
        if isinstance(block, JsonBlock):
            return compact_json(block.value)
        if isinstance(block, (ImageBlock, AudioBlock, FileBlock, ResourceRefBlock)):
            return f"[{block.kind}: {block.uri}]"
        raise TypeError(f"unsupported content block {type(block)!r}")

    @classmethod
    def _content_block(cls, block: Any) -> dict[str, Any]:
        if isinstance(block, TextBlock):
            return {"type": "text", "text": block.text}
        if isinstance(block, JsonBlock):
            return {"type": "text", "text": compact_json(block.value)}
        if isinstance(block, ImageBlock):
            if block.uri.startswith("data:") and ";base64," in block.uri:
                header, data = block.uri.split(",", 1)
                media_type = header[5:].split(";", 1)[0]
                # Validate early so malformed data never reaches the provider.
                base64.b64decode(data, validate=True)
                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": data,
                    },
                }
            return {"type": "image", "source": {"type": "url", "url": block.uri}}
        if isinstance(block, FileBlock):
            return {
                "type": "document",
                "source": {"type": "url", "url": block.uri},
                "title": block.name,
            }
        if isinstance(block, (AudioBlock, ResourceRefBlock)):
            return {"type": "text", "text": cls._block_text(block)}
        raise TypeError(f"unsupported content block {type(block)!r}")

    @staticmethod
    def _tool_definition(tool) -> dict[str, Any]:
        value: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        if tool.output_schema is not None:
            value["output_schema"] = tool.output_schema
        return value

    async def close(self) -> None:
        """Close only the HTTP client owned by this provider instance."""

        if self._owns_client:
            await self._client.aclose()
