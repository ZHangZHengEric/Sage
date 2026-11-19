"""Official conversation-summarizer plugin: bounded structured model summary."""

from __future__ import annotations
from sagents.v2.model.recovery_scope import scoped_recovery

import asyncio
from functools import partial
from sagents.v2.prompt_i18n import prompt_text
from sagents.v2.concurrency import auxiliary_capacity, bounded_to_thread
import json

import httpx

from sagents.v2.context.plugins._shared.progress_summary import extract_snapshot, task_snapshot
from sagents.v2.context.summary import SummarizationRequest, summary_safe_block_text
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import JsonBlock, TextBlock
from sagents.v2.model.contracts import ModelEventKind, ModelMessage, ModelRequest
from sagents.v2.model.plugins._shared.wire import stream_incomplete_error
from sagents.v2.model.recovery import (
    adaptive_summary,
    model_call_budget,
    reported_context_limit_error,
    recovery_error,
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
    _MAX_TIMEOUT_RETRIES = 2
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

    @scoped_recovery
    async def summarize(self, request: SummarizationRequest) -> str:
        from sagents.v2.model.recovery_scope import current_recovery_scope, reserve_additional_request

        source = await bounded_to_thread("context-cpu", partial(self._source, request))
        capabilities = getattr(self.model, "capabilities", None)
        limits = None
        if callable(capabilities):
            probe = request.model_copy(update={"messages": (), "previous_summary": None})
            limits = await self._attempt_with_retries(
                probe, discover=partial(capabilities, self.model_binding),
            )
        source_limit = None
        if limits is not None and limits.max_input_tokens is not None:
            # Reserve for framing, the longest prompt (including a repair),
            # the optional schema, and the wrapper used by fragment requests.
            overhead = 96 + len(self._instructions(request, repair=True).encode("utf-8"))
            if limits.supports_structured_output:
                overhead += len(json.dumps(self._SCHEMA, separators=(",", ":")).encode("utf-8"))
            source_limit = limits.max_input_tokens - overhead
            if source_limit < 4:
                raise recovery_error(
                    "model.context_irreducible", "The summary prompt exceeds the model input budget"
                )
        max_parts = None
        if source_limit is not None:
            scope = current_recovery_scope()
            state = scope.states.get(f"{scope.step_key}:summary_fragment")
            max_parts = 1 + max(0, min(
                scope.config.episode_requests - scope.episode_counts.get(scope.step_key, 0),
                scope.config.context_repairs - (state.counts.get("context", 0) if state else 0),
                scope.config.run_requests - scope.run_requests,
            ))
        parts = await bounded_to_thread(
            "context-cpu", partial(self._split_source, source, source_limit, max_parts=max_parts)
        )
        if parts is None:
            # Canonical messages still remain in the ledger. Use the existing
            # extractive summary when the request count exceeds durable limits.
            LOGGER.bind(run_id=request.scope.run_id, session_id=request.scope.session_id).info(
                "context.summary.preflight_extractive", "Using a bounded extractive summary",
                max_fragments=max_parts, source_characters=len(source), source_bytes_per_fragment=source_limit,
            )
            del source
            return await extract_snapshot(request)
        first = True

        async def summarize_fragment(fragment):
            nonlocal first
            initial = first
            first = False
            if not initial:
                await reserve_additional_request("context", purpose="summary_fragment")
            fragment_request = request
            if fragment is not source:
                fragment_request = request.model_copy(
                    update={
                        "previous_summary": None,
                        "messages": (ModelMessage(role="user", content=(TextBlock(text=fragment),)),),
                    }
                )
            return await self._attempt_with_retries(fragment_request, account_initial=initial)

        with model_call_budget() as budget:
            if len(parts) > budget.remaining:
                raise recovery_error(
                    "model.context_recovery_exhausted", "Context recovery reached its model-call limit"
                )
            result = await adaptive_summary(parts[0], summarize_fragment, merge=self._merge_payloads)
            for part in parts[1:]:
                value = await adaptive_summary(part, summarize_fragment, merge=self._merge_payloads)
                result = self._merge_payloads(result, value)
        if len(parts) > 1 and len(result) >= len(source):
            raise recovery_error("context.summary_no_progress", "Summary splitting did not reduce its source")
        return await bounded_to_thread(
            "context-cpu", partial(self._with_task_evidence, request, result)
        )

    @staticmethod
    def _split_source(
        source: str, max_bytes: int | None, *, max_parts: int | None = None,
    ) -> tuple[str, ...] | None:
        if max_bytes is None:
            return (source,)
        # UTF-8 bytes bound byte-based tokenizers without a network vocabulary.
        aggregate_limit = max_bytes * max_parts if max_parts is not None else None
        if aggregate_limit is not None and len(source) > aggregate_limit:
            return None
        encoded = source.encode("utf-8")
        if aggregate_limit is not None and len(encoded) > aggregate_limit:
            return None
        if len(encoded) <= max_bytes:
            return (source,)
        result = []
        position = 0
        while position < len(encoded):
            if len(result) == max_parts:
                return None
            end = min(position + max_bytes, len(encoded))
            if end < len(encoded):
                while encoded[end] & 0xC0 == 0x80:
                    end -= 1
            result.append(encoded[position:end].decode("utf-8"))
            position = end
        return tuple(result)

    @staticmethod
    def _instructions(request, *, repair: bool) -> str:
        language = request.response_language
        return (
            prompt_text("summary_system", language) + "\n"
            + prompt_text("summary_language", language) + " "
            + prompt_text("summary_budget", language, target_tokens=request.target_tokens)
            + ("\n\n" + prompt_text("summary_retry", language) if repair else "")
        )

    @staticmethod
    def _with_task_evidence(request: SummarizationRequest, result: str) -> str:
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

    async def _attempt_with_retries(self, request: SummarizationRequest, *, account_initial=False, discover=None):
        from sagents.v2.model.recovery import execute_recoverable_operation
        from sagents.v2.model.recovery_scope import current_recovery_scope, recovery_call
        from sagents.v2.model.failures import failure_from_error
        scope = current_recovery_scope()
        logger = LOGGER.bind(session_id=request.scope.session_id, run_id=request.scope.run_id,
            correlation_id=new_id("summary_operation"))
        progress = {}
        purpose = "summary_transport" if discover is None else "summary_capabilities"

        async def attempt():
            progress.clear()
            reservation = scope.states.get(key)
            progress.update(attempt=0, text_delta_count=0, reasoning_delta_count=0,
                timeout_attempt=(reservation.counts.get("transient", 0) if reservation else 0) + 1)
            if discover is None:
                logger.info("context.summary.attempt_started", "Starting conversation summary attempt", attributes=progress)
            # Capacity belongs to a request, never to backoff or a restored wait.
            async with auxiliary_capacity("context-summary"):
                try:
                    async with asyncio.timeout(self.timeout_seconds):
                        if discover is not None:
                            return await discover()
                        return await self._summarize(request, progress)
                except TimeoutError as exc:
                    raise self._timeout_error("total", progress) from exc
                except SageV2Error as exc:
                    if failure_from_error(exc.info).kind.value in {"transport", "stream"}:
                        timeout = self._as_timeout_error(exc, progress)
                        if timeout is not None:
                            raise timeout from exc
                    raise

        def on_retry(error, decision):
            is_timeout = error.code == "context.summarizer.model_timeout"
            logger.warning("context.summary.timeout_retry" if is_timeout else "context.summary.provider_retry",
                "Conversation summary recovery scheduled", error=SageV2Error(error),
                attributes={**error.metadata, **progress, "retry_delay_seconds": decision.delay_seconds})

        with recovery_call(request, purpose) as key:
            pending = scope.states.get(key)
            if (account_initial and scope.episode_counts.get(scope.step_key, 0)
                and not (pending and pending.pending_action is not None)
                and f"{scope.step_key}:auxiliary_context" not in scope.states):
                from sagents.v2.model.recovery_scope import reserve_additional_request
                await reserve_additional_request("context", purpose="recovery_summary")
            try:
                result = await execute_recoverable_operation(attempt, scope=scope, key=key,
                    purpose=purpose, transient_retries=self._MAX_TIMEOUT_RETRIES, on_retry=on_retry)
            except SageV2Error as exc:
                is_timeout = exc.info.code == "context.summarizer.model_timeout"
                if is_timeout:
                    exc = SageV2Error(exc.info.model_copy(update={"metadata": {
                        **exc.info.metadata, **progress, "timeout_retries_exhausted": True}}))
                logger.exception("context.summary.timeout_exhausted" if is_timeout else "context.summary.failed",
                    "Conversation summary failed", exc, attributes={**exc.info.metadata, **progress})
                raise exc
            if discover is None:
                logger.info("context.summary.completed", "Conversation summary completed", attributes=progress)
            return result

    def _as_timeout_error(self, error, progress):
        if (
            isinstance(error, SageV2Error)
            and error.info.code == "context.summarizer.model_timeout"
        ):
            return SageV2Error(error.info.model_copy(update={"metadata": {**error.info.metadata, **progress}}))
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
        source = await bounded_to_thread("context-cpu", partial(self._source, request))
        last_error = ""
        for attempt in range(2):
            progress["attempt"] = attempt + 1
            model_request = ModelRequest(
                request_id=new_id("summary_request"),
                run_id=request.scope.run_id,
                model_binding=self.model_binding,
                messages=(
                    ModelMessage(
                        role="system",
                        content=(
                            TextBlock(
                                text=self._instructions(request, repair=bool(attempt)),
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
            from sagents.v2.model.recovery import collect_response
            from sagents.v2.model.recovery_scope import reserve_additional_request
            if attempt:
                await reserve_additional_request("arguments", purpose="summary_output_repair")
            def observe(event):
                if event.kind == ModelEventKind.TEXT_DELTA and event.delta:
                    progress["text_delta_count"] += 1
                elif event.kind == ModelEventKind.REASONING_DELTA and event.delta:
                    progress["reasoning_delta_count"] += 1
            completed = await collect_response(self.model, model_request,
                idle_timeout_seconds=self.idle_timeout_seconds, on_event=observe,
                transient_retries=self._MAX_TIMEOUT_RETRIES)
            async def record_failed_output():
                from sagents.v2.model.recovery_scope import current_recovery_scope
                scope = current_recovery_scope()
                if completed is not None and scope is not None and scope.record_failed_usage is not None:
                    await scope.record_failed_usage(completed.usage)
            if completed is not None:
                ceiling_error = reported_context_limit_error(completed, capabilities)
                if ceiling_error is not None:
                    await record_failed_output()
                    raise ceiling_error
            if completed is not None and completed.finish_reason.lower() in {
                "max_output_tokens",
                "max_tokens",
                "length",
            }:
                last_error = "summary output was truncated at the model output limit"
                await record_failed_output()
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
                await record_failed_output()
                continue
            try:
                payload = self._parse_payload(completed.text)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                await record_failed_output()
                continue
            usage = completed.usage
            if usage.reported and usage.input_tokens > 0:
                reduced = usage.output_tokens < usage.input_tokens
                LOGGER.bind(
                    session_id=request.scope.session_id, run_id=request.scope.run_id,
                    request_id=model_request.request_id,
                ).info(
                    "context.summary.model_usage",
                    "Compared input and output usage for this summary call",
                    attributes={"input_tokens": usage.input_tokens,
                                "output_tokens": usage.output_tokens, "reduced": reduced},
                )
                if not reduced:
                    await record_failed_output()
                    raise SageV2Error(RuntimeErrorInfo(
                        code="context.summary_no_progress", category=ErrorCategory.VALIDATION,
                        message="Summary output tokens did not decrease from its input tokens",
                        safe_to_resume=True,
                    ))
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
