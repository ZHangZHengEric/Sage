"""Official Memory recall-query plugin: compact keywords from a fast model."""

from __future__ import annotations

from sagents.v2.context.auxiliary import stream_auxiliary_model

import asyncio
import json

from sagents.v2.prompt_i18n import prompt_language, prompt_text

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelMessage, ModelRequest
from sagents.v2.model.provider import ModelProvider
from sagents.v2.model.provider import (
    DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
    auxiliary_model_timeout_error,
)


class LLMMemoryRecallQueryGenerator:
    """Use a model to turn the current request into compact search keywords."""

    plugin_id = "sage.memory.recall-query.llm"
    name = "LLM-generated keywords"
    description = (
        "Uses a fast model to generate compact keywords before calling search_memory."
    )

    def __init__(
        self,
        model: ModelProvider,
        *,
        language: str = "en",
        timeout_seconds: float = DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.model = model
        self.language = language
        self.timeout_seconds = float(timeout_seconds)

    async def generate(
        self, user_input: str, *, run_id: str, language: str | None = None
    ) -> str:
        source = user_input.strip()
        if not source:
            return ""
        language = prompt_language(language if language is not None else self.language)
        system = prompt_text("memory_system", language)
        prompt = prompt_text("memory_request", language)
        request = ModelRequest(
            request_id=new_id("memory_query"),
            run_id=run_id,
            model_binding="fast",
            messages=(
                ModelMessage(role="system", content=(TextBlock(text=system),)),
                ModelMessage(role="user", content=(TextBlock(text=prompt + source),)),
            ),
            tools=(),
            tool_choice="none",
            metadata={"purpose": "memory_recall_query", "response_language": language},
        )
        response = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                stream = stream_auxiliary_model(self.model, request)
                try:
                    async for event in stream:
                        if event.response is not None:
                            response = event.response
                finally:
                    closer = getattr(stream, "aclose", None)
                    if closer is not None:
                        await closer()
        except TimeoutError as exc:
            raise auxiliary_model_timeout_error(
                code="memory.recall_query.model_timeout",
                operation="LLM Memory recall query generation",
                timeout_seconds=self.timeout_seconds,
                plugin_id=self.plugin_id,
            ) from exc
        if response is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="memory.recall_query.response_missing",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message="LLM Memory recall query returned no completed response",
                    safe_to_resume=True,
                    metadata={"plugin_id": self.plugin_id},
                )
            )
        text = response.text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1]).strip() if len(lines) > 2 else text
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="memory.recall_query.output_invalid",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message="LLM Memory recall query returned invalid JSON",
                    safe_to_resume=True,
                    metadata={"plugin_id": self.plugin_id},
                )
            ) from exc
        query = value.get("query") if isinstance(value, dict) else None
        if not isinstance(query, str):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="memory.recall_query.output_invalid",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message="LLM Memory recall query returned no string query",
                    safe_to_resume=True,
                    metadata={"plugin_id": self.plugin_id},
                )
            )
        # An empty query means no recall is needed; the engine skips the search.
        return query.strip()
