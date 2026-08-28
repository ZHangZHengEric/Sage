"""Build the provider-facing model context without mutating conversation facts."""

from __future__ import annotations

from typing import Protocol

from sagents.v2.context.contracts import (
    ContextBudget,
    ContextPlacement,
    ContextProjection,
    ContextReductionScope,
    ContextReducer,
    ContextSegment,
    ContextSegmentProvider,
    ContextStability,
)
from sagents.v2.context.budget import (
    WindowContextReducer,
)
from sagents.v2.context.token_estimator import (
    JsonHeuristicTokenEstimator,
    TokenEstimator,
)
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
    ) -> tuple[ModelMessage, ...]: ...

    async def prepare_projection(
        self,
        command: StartRun,
        ledger: tuple[ModelMessage, ...],
        *,
        run_id: str | None = None,
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
    ) -> tuple[ModelMessage, ...]:
        return (await self.prepare_projection(command, ledger, run_id=run_id)).messages

    async def prepare_projection(
        self,
        command: StartRun,
        ledger: tuple[ModelMessage, ...],
        *,
        run_id: str | None = None,
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
            tuple(message for message in ledger if message.role != "system")
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
        if self.budget is not None:
            # Reduction affects only this request projection. The checkpointed
            # ledger and canonical runtime events retain their original facts.
            scope = None
            if run_id is not None and self.history is not None:
                run = await self.history.reader.get_run(run_id)
                context_key = run.session_id
                if run.concurrency_mode == SessionConcurrencyMode.SNAPSHOT_ISOLATED:
                    context_key = f"{run.session_id}:snapshot:{run.run_id}"
                scope = ContextReductionScope(
                    context_key=context_key,
                    session_id=run.session_id,
                    run_id=run.run_id,
                    source_sequence=run.base_session_sequence,
                )
            return await self.reducer.reduce(messages, self.budget, scope=scope)
        return ContextProjection(
            messages=messages,
            estimated_tokens=self.estimator.estimate(messages),
            source_message_count=len(messages),
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
            frozen = prior.metadata.get("frozen_current_time_context")
            if prior.role == "user" and isinstance(frozen, str) and frozen.strip():
                prepared[prior_index] = DefaultContextAssembler._wrap_user_context(
                    prior, frozen.strip()
                )
        original = prepared[index]
        prepared[index] = DefaultContextAssembler._wrap_user_context(
            original, runtime_text
        )
        return tuple(prepared)

    @staticmethod
    def _wrap_user_context(original: ModelMessage, runtime_text: str) -> ModelMessage:
        prefix = TextBlock(
            text=(
                f"<runtime_context>\n{runtime_text}\n</runtime_context>"
                "\n\n<user_request>\n"
            )
        )
        # Prefix and suffix the original block list instead of flattening text
        # and moving images/files behind it. Provider adapters therefore see
        # the same multimodal ordering the user supplied.
        if len(original.content) == 1 and isinstance(original.content[0], TextBlock):
            content: tuple[ContentBlock, ...] = (
                TextBlock(
                    text=(f"{prefix.text}{original.content[0].text}\n</user_request>")
                ),
            )
        else:
            content = (
                prefix,
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
