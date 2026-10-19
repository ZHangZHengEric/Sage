"""Official conversation-summarizer plugin: bounded structured model summary."""

from __future__ import annotations

import asyncio
from sagents.v2.prompt_i18n import prompt_text
from sagents.v2.concurrency import auxiliary_capacity
import json

import httpx

from sagents.v2.context.progress_summary import task_snapshot
from sagents.v2.context.summary import SummarizationRequest, summary_safe_block_text
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import JsonBlock, TextBlock
from sagents.v2.model.contracts import ModelEventKind, ModelMessage, ModelRequest
from sagents.v2.model.wire import stream_incomplete_error
from sagents.v2.model.recovery import (
    adaptive_summary,
    consume_model_call,
    model_call_budget,
    reported_context_limit_error,
)
from sagents.v2.model.provider import (
    DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
    ModelProvider,
    auxiliary_model_timeout_error,
)
from sagents.v2.runtime.observability.logs import get_logger

DEFAULT_SUMMARY_MODEL_TIMEOUT_SECONDS = 300.0
LOGGER = get_logger(__name__)


class ModelConversationSummarizer:
    """Use any v2 ModelProvider for a bounded, structured rolling summary.

    The seven-field payload intentionally mirrors the information contract used
    by the established compression path. It is still derived state: callers
    persist the canonical ledger and may discard or regenerate this JSON.
    """

    plugin_id = "sage.context.summarizer.model"
    name = "Model conversation summarizer"
    description = "Uses a model binding to write conversation summaries."
    _MAX_TIMEOUT_RETRIES = 3
    _FIELDS = (
        "summary",
        "decisions",
        "open_tasks",
        "files_touched",
        "commands_run",
        "important_errors",
        "user_requirements",
    )
    _SCHEMA = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "decisions": {"type": "array", "items": {"type": "string"}},
            "open_tasks": {"type": "array", "items": {"type": "string"}},
            "files_touched": {"type": "array", "items": {"type": "string"}},
            "commands_run": {"type": "array", "items": {"type": "string"}},
            "important_errors": {"type": "array", "items": {"type": "string"}},
            "user_requirements": {"type": "array", "items": {"type": "string"}},
        },
        "required": list(_FIELDS),
        "additionalProperties": False,
    }

    def __init__(
        self,
        model: ModelProvider,
        *,
        model_binding: str = "primary",
        max_source_tokens: int = 24_000,
        timeout_seconds: float = DEFAULT_SUMMARY_MODEL_TIMEOUT_SECONDS,
        idle_timeout_seconds: float = DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if idle_timeout_seconds <= 0:
            raise ValueError("idle_timeout_seconds must be greater than zero")
        if max_source_tokens <= 0:
            raise ValueError("max_source_tokens must be greater than zero")
        if model_binding != "primary":
            raise ValueError("history summarization must use the Agent primary model")
        self.model = model
        self.model_binding = model_binding
        self.max_source_tokens = max_source_tokens
        self.timeout_seconds = float(timeout_seconds)
        self.idle_timeout_seconds = float(idle_timeout_seconds)

    async def summarize(self, request: SummarizationRequest) -> str:
        # The complete source, including the previous checkpoint, participates
        # in splitting. Never drop a prefix or commit a partial successful half.
        source = self._source(request)
        first = True

        async def summarize_fragment(fragment):
            nonlocal first
            if first:
                first = False
                return await self._summarize_with_retries(request)
            fragment_request = request.model_copy(
                update={
                    "previous_summary": None,
                    "messages": (
                        ModelMessage(role="user", content=(TextBlock(text=fragment),)),
                    ),
                }
            )
            return await self._summarize_with_retries(fragment_request)

        with model_call_budget():
            result = await adaptive_summary(
                source, summarize_fragment, merge=self._merge_payloads
            )
        # Fragment requests carry serialized text; attach authoritative Tool/Todo
        # evidence from the original complete request only after all parts finish.
        try:
            payload = json.loads(result)
        except (TypeError, ValueError):
            return result  # compatibility for custom summarizer subclasses
        snapshot = task_snapshot(request)
        for field in ("tool_outcomes", "todo_state_at_compaction_boundary"):
            if field in snapshot:
                payload[field] = snapshot[field]
        if "todo_state_at_compaction_boundary" in snapshot:
            payload["open_tasks"] = snapshot.get("open_tasks", [])
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    async def _summarize_with_retries(self, request: SummarizationRequest) -> str:
        async with auxiliary_capacity("context-summary"):
            logger = LOGGER.bind(
                session_id=request.scope.session_id,
                run_id=request.scope.run_id,
                correlation_id=new_id("summary_operation"),
            )
            started = asyncio.get_running_loop().time()
            for timeout_attempt in range(self._MAX_TIMEOUT_RETRIES + 1):
                progress = {
                    "attempt": 0,
                    "text_delta_count": 0,
                    "reasoning_delta_count": 0,
                    "timeout_attempt": timeout_attempt + 1,
                    "timeout_retry_limit": self._MAX_TIMEOUT_RETRIES,
                }
                attributes = {
                    "model_binding": self.model_binding,
                    "source_message_count": len(request.messages),
                    "target_tokens": request.target_tokens,
                    "timeout_seconds": self.timeout_seconds,
                    "idle_timeout_seconds": self.idle_timeout_seconds,
                    **progress,
                }
                logger.info(
                    "context.summary.attempt_started",
                    "Starting conversation summary attempt",
                    attributes=attributes,
                )
                try:
                    try:
                        # Each timeout retry gets a fresh total budget, including
                        # capabilities discovery and both output-format attempts.
                        async with asyncio.timeout(self.timeout_seconds):
                            result = await self._summarize(request, progress)
                    except TimeoutError as exc:
                        raise self._timeout_error("total", progress) from exc
                except Exception as exc:
                    timeout_error = self._as_timeout_error(exc, progress)
                    if (
                        timeout_error is None
                        and isinstance(exc, SageV2Error)
                        and exc.info.retryable
                        and exc.info.category
                        in {
                            ErrorCategory.PROVIDER_TRANSIENT,
                            ErrorCategory.RATE_LIMITED,
                        }
                    ):
                        # Summary output is derived, with no Tool side effects
                        # or user-visible deltas. Retrying it cannot replay work.
                        if timeout_attempt == self._MAX_TIMEOUT_RETRIES:
                            raise
                        delay = 2 ** (timeout_attempt + 1)
                        logger.warning(
                            "context.summary.provider_retry",
                            "Conversation summary provider failed; retrying",
                            error=exc,
                            attributes={
                                **attributes,
                                "retry_delay_seconds": delay,
                                "provider_retry_attempt": timeout_attempt + 1,
                            },
                        )
                        await asyncio.sleep(delay)
                        continue
                    if timeout_error is None:
                        logger.exception(
                            "context.summary.failed",
                            "Conversation summary failed",
                            exc,
                            attributes={**attributes, **progress},
                        )
                        raise
                    exhausted = timeout_attempt == self._MAX_TIMEOUT_RETRIES
                    delay = 0 if exhausted else 2 ** (timeout_attempt + 1)
                    attributes.update(
                        {
                            **timeout_error.info.metadata,
                            "retry_delay_seconds": delay,
                            "elapsed_seconds": asyncio.get_running_loop().time()
                            - started,
                            "timeout_retries_exhausted": exhausted,
                        }
                    )
                    if exhausted:
                        error = SageV2Error(
                            timeout_error.info.model_copy(
                                update={
                                    "metadata": {
                                        **timeout_error.info.metadata,
                                        "timeout_retries_exhausted": True,
                                    }
                                }
                            )
                        )
                        logger.exception(
                            "context.summary.timeout_exhausted",
                            "Conversation summary timeout retries exhausted",
                            error,
                            attributes=attributes,
                        )
                        raise error from exc
                    logger.warning(
                        "context.summary.timeout_retry",
                        "Conversation summary timed out; retrying",
                        error=timeout_error,
                        attributes=attributes,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.info(
                        "context.summary.completed",
                        "Conversation summary completed",
                        attributes={
                            **attributes,
                            **progress,
                            "elapsed_seconds": asyncio.get_running_loop().time()
                            - started,
                            "output_characters": len(result),
                        },
                    )
                    return result
            raise AssertionError("unreachable summary retry state")

    def _as_timeout_error(self, error, progress):
        if (
            isinstance(error, SageV2Error)
            and error.info.code == "context.summarizer.model_timeout"
        ):
            return error
        # Official providers wrap SDK errors but preserve their exception cause.
        # Recognize transport timeouts by type, never by matching arbitrary text.
        cause = error
        seen = set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, (TimeoutError, httpx.TimeoutException)):
                return SageV2Error(
                    RuntimeErrorInfo(
                        code="context.summarizer.model_timeout",
                        category=ErrorCategory.PROVIDER_TRANSIENT,
                        message="Conversation summary provider request timed out",
                        retryable=True,
                        safe_to_resume=True,
                        metadata={
                            "plugin_id": self.plugin_id,
                            "timeout_kind": "provider",
                            "provider_exception_type": type(cause).__name__,
                            **progress,
                        },
                    )
                )
            cause = cause.__cause__
        return None

    def _timeout_error(self, kind, progress):
        seconds = self.timeout_seconds if kind == "total" else self.idle_timeout_seconds
        error = auxiliary_model_timeout_error(
            code="context.summarizer.model_timeout",
            operation="Model conversation summarization",
            timeout_seconds=seconds,
            plugin_id=self.plugin_id,
        )
        return SageV2Error(
            error.info.model_copy(
                update={
                    "metadata": {
                        **error.info.metadata,
                        "timeout_kind": kind,
                        **progress,
                    }
                }
            )
        )

    def _source(self, request: SummarizationRequest) -> str:
        parts = []
        if request.previous_summary:
            parts.append(
                f"<previous_summary>\n{request.previous_summary}\n</previous_summary>"
            )
        parts.append("<history>")
        for message in request.messages:
            value = self._message_text(message)
            if message.tool_calls:
                value += (
                    "\n"
                    + prompt_text("summary_tools", request.response_language)
                    + " "
                    + ", ".join(
                        f"{call.name}({summary_safe_block_text(JsonBlock(value=call.arguments))})"
                        for call in message.tool_calls
                    )
                )
            parts.append(f"<{message.role}>\n{value}\n</{message.role}>")
        parts.append("</history>")
        return "\n".join(parts)

    async def _summarize(self, request: SummarizationRequest, progress) -> str:
        capabilities = await self.model.capabilities(self.model_binding)
        source = self._source(request)
        last_error = ""
        for attempt in range(2):
            progress["attempt"] = attempt + 1
            retry = (
                ("\n\n" + prompt_text("summary_retry", request.response_language))
                if attempt
                else ""
            )
            model_request = ModelRequest(
                request_id=new_id("summary_request"),
                run_id=request.scope.run_id,
                model_binding=self.model_binding,
                messages=(
                    ModelMessage(
                        role="system",
                        content=(
                            TextBlock(
                                text=(
                                    prompt_text(
                                        "summary_system", request.response_language
                                    )
                                    + "\n"
                                    + prompt_text(
                                        "summary_language", request.response_language
                                    )
                                    + " "
                                    + prompt_text(
                                        "summary_budget",
                                        request.response_language,
                                        target_tokens=request.target_tokens,
                                    )
                                    + retry
                                )
                            ),
                        ),
                    ),
                    ModelMessage(role="user", content=(TextBlock(text=source),)),
                ),
                response_schema=(
                    self._SCHEMA if capabilities.supports_structured_output else None
                ),
                max_output_tokens=min(
                    max(8192, request.target_tokens * 2) * (attempt + 1),
                    capabilities.max_output_tokens or 32768,
                    32768,
                ),
                reasoning_mode="minimum",
                metadata={
                    "purpose": "conversation_summary",
                    "attempt": attempt + 1,
                    "response_language": request.response_language,
                },
            )
            progress["model_request_id"] = model_request.request_id
            completed = None
            consume_model_call()
            stream = self.model.stream(model_request)
            try:
                iterator = aiter(stream)
                while True:
                    try:
                        async with asyncio.timeout(self.idle_timeout_seconds):
                            event = await anext(iterator)
                    except StopAsyncIteration:
                        break
                    except TimeoutError as exc:
                        raise self._timeout_error("idle", progress) from exc
                    if event.kind == ModelEventKind.TEXT_DELTA and event.delta:
                        progress["text_delta_count"] += 1
                    elif event.kind == ModelEventKind.REASONING_DELTA and event.delta:
                        progress["reasoning_delta_count"] += 1
                    elif event.kind == ModelEventKind.COMPLETED:
                        completed = event.response
                        break
            finally:
                closer = getattr(stream, "aclose", None)
                if closer is not None:
                    await closer()
            if completed is not None:
                ceiling_error = reported_context_limit_error(completed, capabilities)
                if ceiling_error is not None:
                    raise ceiling_error
            if completed is not None and completed.finish_reason.lower() in {
                "max_output_tokens",
                "max_tokens",
                "length",
            }:
                last_error = "summary output was truncated at the model output limit"
                continue
            if completed is None:
                raise stream_incomplete_error(
                    provider=self.plugin_id,
                    response_started=bool(
                        progress["text_delta_count"]
                        or progress["reasoning_delta_count"]
                    ),
                )
            if not completed.text.strip():
                last_error = "summary model completed without usable text"
                continue
            try:
                payload = self._parse_payload(completed.text)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                continue
            # The API output limit is the bound. Do not truncate verified
            # identifiers or drop requirements after a complete valid response.
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        raise RuntimeError(
            f"summary model returned invalid structured output: {last_error}"
        )

    @staticmethod
    def _merge_payloads(first: str, second: str) -> str:
        """Keep every successful child's structured facts, in source order.

        A further generative summary can silently forget identifiers from the
        first child. Storage merges never trim these facts; the next request
        still goes through API feedback if this aggregate is too large.
        """
        left, right = json.loads(first), json.loads(second)
        merged = dict(left)
        for key, value in right.items():
            previous = merged.get(key)
            if key == "summary":
                merged[key] = "\n".join(
                    dict.fromkeys(str(v) for v in (previous, value) if v)
                )
            elif key == "todo_state_at_compaction_boundary":
                merged[key] = value
            elif isinstance(previous, list) and isinstance(value, list):
                seen = set()
                combined = []
                for item in (*previous, *value):
                    identity = json.dumps(item, ensure_ascii=False, sort_keys=True)
                    if identity not in seen:
                        seen.add(identity)
                        combined.append(item)
                merged[key] = combined
            elif isinstance(previous, dict) and isinstance(value, dict):
                merged[key] = {**previous, **value}
            else:
                merged[key] = value
        return json.dumps(merged, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _message_text(message: ModelMessage) -> str:
        return "\n".join(summary_safe_block_text(block) for block in message.content)

    @classmethod
    def _parse_payload(cls, value: str) -> dict[str, object]:
        text = value.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                text = "\n".join(lines[1:-1])
                if text.lstrip().lower().startswith("json\n"):
                    text = text.lstrip()[5:]
        parsed = json.loads(text)
        # Older checkpoints also contain host-derived task facts. A model can
        # echo those keys even though all seven requested fields are valid.
        # The host rebuilds these facts from the ledger after parsing, so ignore
        # only those known keys rather than paying for another full generation.
        derived_fields = {"tool_outcomes", "todo_state_at_compaction_boundary"}
        if (
            not isinstance(parsed, dict)
            or not set(cls._FIELDS).issubset(parsed)
            or set(parsed) - set(cls._FIELDS) - derived_fields
        ):
            raise ValueError("summary JSON has the wrong fields")
        if not isinstance(parsed["summary"], str):
            raise ValueError("summary JSON field 'summary' must be a string")
        normalized: dict[str, object] = {"summary": parsed["summary"].strip()}
        for field_name in cls._FIELDS[1:]:
            raw = parsed[field_name]
            if not isinstance(raw, list) or not all(
                isinstance(item, str) for item in raw
            ):
                raise ValueError(f"summary JSON field {field_name!r} must be strings")
            normalized[field_name] = [item.strip() for item in raw if item.strip()]
        return normalized
