"""Build the provider-facing model context without mutating conversation facts."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Protocol

from sagents.v2.context.contracts import (
    ContextBudget,
    ContextPlacement,
    ContextProjection,
    ContextProjectionObserver,
    ContextRequestReservation,
    ContextReductionScope,
    ContextReducer,
    ContextSegment,
    ContextSegmentProvider,
    ContextStability,
)
from sagents.v2.context.plugins.estimator_json import JsonHeuristicTokenEstimator
from sagents.v2.context.plugins.window import WindowContextReducer
from sagents.v2.context.token_estimator import TokenEstimator
from sagents.v2.model import ModelMessage
from sagents.v2.contracts.items import ContentBlock
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.context.session_history import (
    SessionHistoryLedgerBuilder,
    SessionHistoryReader,
)
from sagents.v2.contracts.run_state import SessionConcurrencyMode


class ContextAssembler(Protocol):
    """Projection boundary between the Run ledger and ModelProvider request."""

    async def initial_ledger(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ModelMessage, ...]: ...

    async def prepare_messages(
        self,
        command: StartRun,
        ledger: tuple[ModelMessage, ...],
        *,
        run_id: str | None = None,
        reservation: ContextRequestReservation | None = None,
    ) -> tuple[ModelMessage, ...]: ...

    async def prepare_projection(
        self,
        command: StartRun,
        ledger: tuple[ModelMessage, ...],
        *,
        run_id: str | None = None,
        reservation: ContextRequestReservation | None = None,
    ) -> ContextProjection: ...


class StaticContextProvider:
    def __init__(self, segments: tuple[ContextSegment, ...]) -> None:
        self._segments = segments

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        return self._segments


class DefaultContextAssembler:
    """Fresh-system request projection with stable and volatile boundaries."""

    def __init__(
        self,
        *,
        system_instructions: str | None = None,
        developer_instructions: str | None = None,
        providers: tuple[ContextSegmentProvider, ...] = (),
        runtime_context_in_user: bool = True,
        budget: ContextBudget | None = None,
        reducer: ContextReducer | None = None,
        estimator: TokenEstimator | None = None,
        history_reader: SessionHistoryReader | None = None,
        projection_observer: ContextProjectionObserver | None = None,
    ) -> None:
        static = []
        if system_instructions:
            static.append(
                ContextSegment(
                    segment_id="system_instructions",
                    content=system_instructions,
                    stability=ContextStability.STABLE,
                    priority=-200,
                )
            )
        if developer_instructions:
            static.append(
                ContextSegment(
                    segment_id="agent_instructions",
                    content=(
                        "<role_definition>\n"
                        f"{developer_instructions}\n"
                        "</role_definition>"
                    ),
                    stability=ContextStability.STABLE,
                    priority=-180,
                )
            )
        self.providers = (
            *((StaticContextProvider(tuple(static)),) if static else ()),
            *providers,
        )
        self.runtime_context_in_user = runtime_context_in_user
        self.budget = budget
        self.estimator = estimator or JsonHeuristicTokenEstimator()
        self.reducer = reducer or WindowContextReducer(self.estimator)
        self.history = (
            SessionHistoryLedgerBuilder(history_reader)
            if history_reader is not None
            else None
        )
        self.projection_observer = projection_observer

    async def initial_ledger(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ModelMessage, ...]:
        # Ledger owns conversation facts only. System content is projected fresh.
        if self.history is not None and run_id is not None:
            return await self.history.build(command, run_id=run_id)
        return tuple(
            ModelMessage(role=item.role, content=item.content, metadata=item.metadata)
            for item in command.input
        )

    async def prepare_messages(
        self,
        command: StartRun,
        ledger: tuple[ModelMessage, ...],
        *,
        run_id: str | None = None,
        reservation: ContextRequestReservation | None = None,
    ) -> tuple[ModelMessage, ...]:
        return (
            await self.prepare_projection(
                command,
                ledger,
                run_id=run_id,
                reservation=reservation,
            )
        ).messages

    async def prepare_projection(
        self,
        command: StartRun,
        ledger: tuple[ModelMessage, ...],
        *,
        run_id: str | None = None,
        reservation: ContextRequestReservation | None = None,
    ) -> ContextProjection:
        """Create a fresh request view with deterministic context ordering.

        Stable system segments are regenerated for every request so cached or
        restored conversation messages do not become an accidental second copy
        of Agent instructions. Volatile runtime context is injected into the
        latest user message while preserving the original multimodal block order.
        """

        segments = []
        for provider in self.providers:
            segments.extend(await provider.segments(command, run_id=run_id))
        rank = {
            ContextStability.STABLE: 0,
            ContextStability.SEMI_STABLE: 1,
            ContextStability.VOLATILE: 2,
        }
        segments.sort(
            key=lambda value: (rank[value.stability], value.priority, value.segment_id)
        )
        # Provider caches operate on the serialized prefix. Coalescing by
        # stability reproduces the established [stable, semi-stable, volatile]
        # boundary instead of creating a different system message per document.
        system_messages = []
        for stability in (
            ContextStability.STABLE,
            ContextStability.SEMI_STABLE,
            ContextStability.VOLATILE,
        ):
            selected = tuple(
                segment
                for segment in segments
                if segment.placement == ContextPlacement.SYSTEM
                and segment.stability == stability
                and not (
                    self.runtime_context_in_user
                    and stability == ContextStability.VOLATILE
                )
            )
            if not selected:
                continue
            system_messages.append(
                ModelMessage(
                    role="system",
                    content=(
                        TextBlock(
                            text="\n".join(
                                segment.content.rstrip() for segment in selected
                            )
                            + "\n"
                        ),
                    ),
                    metadata={
                        "context_segment_ids": tuple(
                            segment.segment_id for segment in selected
                        ),
                        "cache_segment": stability.value,
                        "sensitive": any(segment.sensitive for segment in selected),
                    },
                )
            )
        system = tuple(system_messages)
        payload = self._sanitize_tool_pairs(
            self._strip_historical_search_memory(
                tuple(message for message in ledger if message.role != "system")
            )
        )
        volatile = tuple(
            segment
            for segment in segments
            if segment.placement == ContextPlacement.LATEST_USER
            or (
                self.runtime_context_in_user
                and segment.stability == ContextStability.VOLATILE
            )
        )
        if volatile:
            payload = self._inject_latest_user(payload, volatile)
        messages = (*system, *payload)
        # Resolved once and shared: the reduction scope and the projection
        # observer both need the owning Run, and neither should pay for a
        # second store read.
        run = None
        if (
            run_id is not None
            and self.history is not None
            and (self.budget is not None or self.projection_observer is not None)
        ):
            run = await self.history.reader.get_run(run_id)
        if self.budget is not None:
            # Reduction affects only this request projection. The checkpointed
            # ledger and canonical runtime events retain their original facts.
            scope = None
            if run is not None:
                context_key = self._summary_context_key(run.session_id)
                if run.concurrency_mode == SessionConcurrencyMode.SNAPSHOT_ISOLATED:
                    context_key = self._summary_context_key(
                        run.session_id, run_id=run.run_id
                    )
                scope = ContextReductionScope(
                    context_key=context_key,
                    session_id=run.session_id,
                    run_id=run.run_id,
                    source_sequence=run.base_session_sequence,
                    response_language=str(
                        command.config.metadata.get("response_language") or "en"
                    ),
                )
            effective_budget = self._with_reservation(
                self.budget,
                reservation or ContextRequestReservation(),
            )
            projection = await self.reducer.reduce(
                messages, effective_budget, scope=scope
            )
        else:
            projection = ContextProjection(
                messages=messages,
                estimated_tokens=self.estimator.estimate(messages),
                source_message_count=len(messages),
            )
        if self.projection_observer is not None and run_id is not None:
            await self.projection_observer.observe_projection(
                run_id,
                projection,
                session_id=run.session_id if run is not None else None,
                source_messages=ledger,
            )
        return projection

    @staticmethod
    def _summary_context_key(session_id: str, *, run_id: str | None = None) -> str:
        """Return a bounded opaque key without reparsing caller identifiers."""

        identity = {"session_id": session_id, "snapshot_run_id": run_id}
        digest = hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return f"context_{digest}"

    @staticmethod
    def _with_reservation(
        budget: ContextBudget,
        reservation: ContextRequestReservation,
    ) -> ContextBudget:
        max_messages = budget.max_messages
        if max_messages is not None:
            max_messages -= reservation.message_count
            if max_messages <= 0:
                from sagents.v2.contracts.errors import (
                    ErrorCategory,
                    RuntimeErrorInfo,
                    SageV2Error,
                )

                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="context.invalid_budget",
                        category=ErrorCategory.VALIDATION,
                        message=(
                            "reserved request suffix consumes the model message budget"
                        ),
                        safe_to_resume=True,
                    )
                )
        return budget.model_copy(
            update={
                "reserve_input_tokens": (
                    budget.reserve_input_tokens + reservation.input_tokens
                ),
                "max_messages": max_messages,
            }
        )

    @staticmethod
    def _inject_latest_user(
        messages: tuple[ModelMessage, ...], segments: tuple[ContextSegment, ...]
    ) -> tuple[ModelMessage, ...]:
        index = next(
            (
                value
                for value in range(len(messages) - 1, -1, -1)
                if messages[value].role == "user"
            ),
            None,
        )
        runtime_text = "\n".join(
            segment.content for segment in segments if segment.content
        )
        if index is None or not runtime_text:
            return messages
        prepared = list(messages)
        for prior_index in range(index):
            prior = prepared[prior_index]
            if prior.role != "user":
                continue
            # Match v1's historical projection: old user turns retain only the
            # time captured for that turn.  Long-term Memory, Todo state,
            # working directories, and workspace listings belong exclusively
            # to the current request projection.
            frozen = DefaultContextAssembler._historical_current_time(prior)
            clean = DefaultContextAssembler._unwrap_user_context(prior)
            prepared[prior_index] = (
                DefaultContextAssembler._wrap_user_context(clean, frozen)
                if frozen
                else clean
            )
        original = prepared[index]
        prepared[index] = DefaultContextAssembler._wrap_user_context(
            original, runtime_text
        )
        return tuple(prepared)

    @staticmethod
    def _wrap_user_context(original: ModelMessage, runtime_text: str) -> ModelMessage:
        original = DefaultContextAssembler._unwrap_user_context(original)
        prefix_text = (
            f"<runtime_context>\n{runtime_text}\n</runtime_context>\n\n<user_request>\n"
        )
        # Prefix and suffix the original block list instead of flattening text
        # and moving images/files behind it. Provider adapters therefore see
        # the same multimodal ordering the user supplied.
        if len(original.content) == 1 and isinstance(original.content[0], TextBlock):
            content: tuple[ContentBlock, ...] = (
                TextBlock(
                    text=(f"{prefix_text}{original.content[0].text}\n</user_request>")
                ),
            )
        else:
            content = (
                TextBlock(text=prefix_text),
                *original.content,
                TextBlock(text="\n</user_request>"),
            )
        updated = original.model_copy(
            update={
                "content": content,
                "metadata": {
                    **original.metadata,
                    "runtime_context_injected": True,
                    "inference_view_only": True,
                },
            }
        )
        return updated

    @staticmethod
    def _historical_current_time(message: ModelMessage) -> str | None:
        frozen = message.metadata.get("frozen_current_time_context")
        if isinstance(frozen, str):
            match = re.search(
                r"<current_time\b[^>]*>.*?</current_time>",
                frozen,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if match is not None:
                return match.group(0).strip()
        for block in message.content:
            if not isinstance(block, TextBlock):
                continue
            runtime = re.search(
                r"<runtime_context\b[^>]*>(.*?)</runtime_context>",
                block.text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if runtime is None:
                continue
            runtime_body = runtime.group(1)
            system = re.search(
                r"<system_context\b[^>]*>(.*?)</system_context>",
                runtime_body,
                flags=re.IGNORECASE | re.DOTALL,
            )
            trusted_body = system.group(1) if system is not None else runtime_body
            match = re.search(
                r"<current_time\b[^>]*>.*?</current_time>",
                trusted_body,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if match is not None:
                return match.group(0).strip()
        return None

    @staticmethod
    def _unwrap_user_context(message: ModelMessage) -> ModelMessage:
        """Recover canonical user content from a previously projected view."""

        content = list(message.content)
        if not content:
            return message
        changed = False
        if len(content) == 1 and isinstance(content[0], TextBlock):
            match = re.search(
                r"<user_request\b[^>]*>\s*(.*?)\s*</user_request>",
                content[0].text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if match is not None:
                content = [content[0].model_copy(update={"text": match.group(1)})]
                changed = True
        else:
            first = content[0]
            if isinstance(first, TextBlock):
                opening = re.search(
                    r"<user_request\b[^>]*>", first.text, flags=re.IGNORECASE
                )
                if opening is not None:
                    remainder = first.text[opening.end() :].lstrip("\n")
                    content = (
                        [first.model_copy(update={"text": remainder}), *content[1:]]
                        if remainder
                        else content[1:]
                    )
                    changed = True
            if content and isinstance(content[-1], TextBlock):
                closing_text = re.sub(
                    r"\s*</user_request>\s*$",
                    "",
                    content[-1].text,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if closing_text != content[-1].text:
                    if closing_text:
                        content[-1] = content[-1].model_copy(
                            update={"text": closing_text}
                        )
                    else:
                        content.pop()
                    changed = True
        if not changed:
            return message
        return message.model_copy(
            update={
                "content": tuple(content),
                "metadata": {
                    key: value
                    for key, value in message.metadata.items()
                    if key not in {"runtime_context_injected", "inference_view_only"}
                },
            }
        )

    @staticmethod
    def _sanitize_tool_pairs(
        messages: tuple[ModelMessage, ...],
    ) -> tuple[ModelMessage, ...]:
        """Drop only malformed provider pairs; never rewrite ordinary user history."""
        output = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.role == "tool":
                index += 1
                continue
            if message.role != "assistant" or not message.tool_calls:
                output.append(message)
                index += 1
                continue
            expected = {call.tool_call_id for call in message.tool_calls}
            cursor = index + 1
            results = []
            while cursor < len(messages) and messages[cursor].role == "tool":
                if messages[cursor].tool_call_id in expected:
                    results.append(messages[cursor])
                cursor += 1
            if {value.tool_call_id for value in results} == expected:
                output.append(message)
                output.extend(results)
            index = cursor
        return tuple(output)

    @staticmethod
    def _strip_historical_search_memory(
        messages: tuple[ModelMessage, ...],
    ) -> tuple[ModelMessage, ...]:
        """Keep only the current turn's automatic Memory Tool pair, as v1 does."""

        latest_user = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if messages[index].role == "user"
                and messages[index].metadata.get("runtime_continuation_guidance")
                is not True
            ),
            None,
        )
        if latest_user is None:
            return messages
        historical_ids = {
            call.tool_call_id
            for message in messages[:latest_user]
            if message.role == "assistant"
            for call in message.tool_calls
            if call.name == "search_memory"
        }
        if not historical_ids:
            return messages
        output = []
        for index, message in enumerate(messages):
            if (
                index < latest_user
                and message.role == "tool"
                and message.tool_call_id in historical_ids
            ):
                continue
            if index < latest_user and message.role == "assistant":
                kept = tuple(
                    call
                    for call in message.tool_calls
                    if call.tool_call_id not in historical_ids
                )
                if kept != message.tool_calls:
                    has_content = any(
                        not isinstance(block, TextBlock) or bool(block.text.strip())
                        for block in message.content
                    )
                    if not kept and not has_content:
                        continue
                    message = message.model_copy(update={"tool_calls": kept})
            output.append(message)
        return tuple(output)
