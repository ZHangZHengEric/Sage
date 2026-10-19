"""Build the provider-facing model context without mutating conversation facts."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict, defaultdict, deque
import re
from typing import Protocol

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.model.recovery import recovery_error
from sagents.v2.contracts.conversation import is_user_request, order_tool_context
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
from sagents.v2.context.plugins.persistent_reducer import (
    PersistentSummaryContextReducer,
)
from sagents.v2.context.plugins.summary_ephemeral import (
    InMemoryConversationSummaryStore,
)
from sagents.v2.model import ModelMessage
from sagents.v2.runtime.artifact.contracts import ArtifactStore
from sagents.v2.runtime.artifact.images import hydrate_image_blocks
from sagents.v2.contracts.items import ContentBlock
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.context.session_history import (
    SessionHistoryLedgerBuilder,
    SessionHistoryReader,
)
from sagents.v2.contracts.run_state import SessionConcurrencyMode
from sagents.v2.skill.tags import strip_skill_tags
from sagents.v2.runtime.observability.logs import get_logger


LOGGER = get_logger(__name__)


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
        max_system_tokens: int = 16_384,
        developer_instructions: str | None = None,
        providers: tuple[ContextSegmentProvider, ...] = (),
        runtime_context_in_user: bool = True,
        budget: ContextBudget | None = None,
        reducer: ContextReducer | None = None,
        history_reader: SessionHistoryReader | None = None,
        projection_observer: ContextProjectionObserver | None = None,
        artifact_store: ArtifactStore | None = None,
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
        if max_system_tokens <= 0:
            raise ValueError("max_system_tokens must be positive")
        self.max_system_tokens = max_system_tokens
        self.budget = budget
        self._compression_requested = {}
        self._projection_signatures = OrderedDict()
        self._compression_feedback = OrderedDict()
        self.reducer = reducer or PersistentSummaryContextReducer(
            InMemoryConversationSummaryStore()
        )
        self.history = (
            SessionHistoryLedgerBuilder(history_reader)
            if history_reader is not None
            else None
        )
        self.projection_observer = projection_observer
        self.artifact_store = artifact_store

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
            ledger_segments = getattr(provider, "segments_for_ledger", None)
            segments.extend(
                await ledger_segments(command, ledger, run_id=run_id)
                if ledger_segments is not None
                else await provider.segments(command, run_id=run_id)
            )
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
        system = (
            *system,
            *(message for message in ledger if message.role == "developer"),
        )
        canonical = tuple(
            message for message in ledger if message.role not in {"system", "developer"}
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
        # Excluded tool pairs must not consume the reduction budget or enter
        # summaries. Keep canonical positions separately for durable coverage;
        # transport ordering and runtime injection remain inference-only.
        source_positions: list[int] = []
        clean = self._strip_historical_search_memory(
            canonical, source_positions=source_positions
        )
        positions = defaultdict(deque)
        for index, message in zip(source_positions, clean, strict=True):
            positions[id(message)].append(index)
        payload = self._sanitize_tool_pairs(clean)
        canonical_indices = tuple(
            positions[id(message)].popleft() for message in payload
        )
        payload = tuple(strip_skill_tags(message) for message in payload)
        messages = (*system, *payload)
        # Resolved once and shared: the reduction scope and the projection
        # observer both need the owning Run, and neither should pay for a
        # second store read.
        run = None
        if run_id is not None and self.history is not None and self.reducer is not None:
            run = await self.history.reader.get_run(run_id)
        scope = ContextReductionScope(
            context_key=self._summary_context_key(
                run.session_id if run is not None else run_id or command.agent_id,
                run_id=run_id
                if run is not None
                and run.concurrency_mode == SessionConcurrencyMode.SNAPSHOT_ISOLATED
                else None,
            ),
            session_id=run.session_id
            if run is not None
            else run_id or command.agent_id,
            run_id=run_id or command.agent_id,
            source_sequence=run.base_session_sequence if run is not None else 0,
            canonical_messages=canonical,
            canonical_indices=canonical_indices,
            response_language=str(
                command.config.metadata.get("response_language") or "en"
            ),
            force=run_id in self._compression_requested,
            allow_summary_rewrite=self._compression_requested.get(run_id, False),
            allow_reference_compaction=not (
                self._compression_requested.get(run_id, False)
                and self._projection_signatures.get(run_id, (None, None))[1]
                == "reference_compaction"
            ),
        )
        required = self._compression_requested.get(run_id, False)
        try:
            projection = await self.reducer.reduce(messages, self.budget, scope=scope)
        except SageV2Error as exc:
            if required or exc.info.code not in {
                "context.no_reducible_history",
                "context.summary_no_progress",
            }:
                raise
            projection = await self.reducer.reduce(
                messages, self.budget, scope=scope.model_copy(update={"force": False})
            )
            feedback = self._compression_feedback.get(run_id)
            if feedback is not None:
                feedback["suppressed_at"] = feedback.get("last_input", 0)
        else:
            if scope.force and not required:
                feedback = self._compression_feedback.get(run_id)
                if feedback is not None:
                    feedback["pending_input"] = feedback.get("last_input", 0)
        self._compression_requested.pop(run_id, None)
        view = self._apply_inference_view(projection.messages, volatile)
        artifact_store = self.artifact_store
        if artifact_store is None and run_id is not None and self.history is not None:
            from sagents.v2.runtime.artifact.session import SessionArtifactStore

            artifact_store = SessionArtifactStore(self.history.reader, run_id)
        view = await hydrate_image_blocks(view, artifact_store)
        if view != projection.messages:
            projection = projection.model_copy(
                update={
                    "messages": view,
                }
            )
        if run_id is not None:
            signature = hashlib.sha256()
            for message in projection.messages:
                signature.update(message.model_dump_json().encode())
            digest = signature.hexdigest()
            if (
                required
                and digest == self._projection_signatures.get(run_id, (None, None))[0]
            ):
                raise recovery_error(
                    "context.summary_no_progress",
                    "Context recovery produced the same rejected request view",
                )
            self._projection_signatures[run_id] = (digest, projection.strategy)
            self._projection_signatures.move_to_end(run_id)
            while len(self._projection_signatures) > 128:
                self._projection_signatures.popitem(last=False)
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

    def request_compression(self, run_id, *, required=True):
        self._compression_requested[run_id] = (
            required or self._compression_requested.get(run_id, False)
        )

    def observe_usage(self, run_id, input_tokens):
        if self.budget is not None:
            maximum = max(
                1,
                self.budget.max_input_tokens
                - self.budget.reserve_output_tokens
                - self.budget.reserve_input_tokens,
            )
            feedback = self._compression_feedback.setdefault(run_id, {})
            self._compression_feedback.move_to_end(run_id)
            while len(self._compression_feedback) > 128:
                self._compression_feedback.popitem(last=False)
            previous = feedback.pop("pending_input", None)
            feedback["last_input"] = input_tokens
            # Judge benefit using actual subsequent provider usage, including
            # tools/system overhead. A successful but ineffective summary must
            # not trigger another LLM summary on every step. Retry advisory
            # compression only after 25% growth or a return below the threshold.
            if previous and input_tokens >= maximum and input_tokens * 10 >= previous * 9:
                feedback["suppressed_at"] = max(previous, input_tokens)
                LOGGER.bind(run_id=run_id).warning(
                    "context.compression.ineffective",
                    "Pausing advisory compression after insufficient reduction",
                    attributes={"before_input_tokens": previous, "after_input_tokens": input_tokens,
                                "threshold_tokens": maximum},
                )
            if input_tokens < maximum:
                feedback.pop("suppressed_at", None)
            suppressed_at = feedback.get("suppressed_at")
            if suppressed_at and input_tokens * 4 < suppressed_at * 5:
                return
            feedback.pop("suppressed_at", None)
            if input_tokens >= maximum:
                LOGGER.bind(run_id=run_id).info(
                    "context.compression.usage_pressure",
                    "Provider-reported input usage reached the compression threshold",
                    attributes={"input_tokens": input_tokens, "threshold_tokens": maximum},
                )
                self.request_compression(run_id, required=False)

    @classmethod
    def _apply_inference_view(
        cls,
        messages: tuple[ModelMessage, ...],
        volatile: tuple[ContextSegment, ...],
    ) -> tuple[ModelMessage, ...]:
        systems = tuple(
            message for message in messages if message.role in {"system", "developer"}
        )
        payload = tuple(
            message
            for message in messages
            if message.role not in {"system", "developer"}
        )
        payload = cls._sanitize_tool_pairs(cls._strip_historical_search_memory(payload))
        payload = tuple(strip_skill_tags(message) for message in payload)
        if volatile:
            payload = cls._inject_latest_user(payload, volatile)
        return (*systems, *payload)

    @staticmethod
    def _inject_latest_user(
        messages: tuple[ModelMessage, ...], segments: tuple[ContextSegment, ...]
    ) -> tuple[ModelMessage, ...]:
        index = next(
            (
                value
                for value in range(len(messages) - 1, -1, -1)
                if is_user_request(messages[value])
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
        messages = order_tool_context(messages)
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
        *,
        source_positions: list[int] | None = None,
    ) -> tuple[ModelMessage, ...]:
        """Keep only the current turn's automatic Memory Tool pair, as v1 does."""

        latest_user = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if is_user_request(messages[index])
            ),
            None,
        )
        if latest_user is None:
            if source_positions is not None:
                source_positions.extend(range(len(messages)))
            return messages
        historical_ids = {
            call.tool_call_id
            for message in messages[:latest_user]
            if message.role == "assistant"
            for call in message.tool_calls
            if call.name == "search_memory"
        }
        if not historical_ids:
            if source_positions is not None:
                source_positions.extend(range(len(messages)))
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
            if source_positions is not None:
                source_positions.append(index)
        return tuple(output)
