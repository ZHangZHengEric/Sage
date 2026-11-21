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
    RunHistoryWindow,
)
from sagents.v2.context.plugins.summary_only import (
    SummaryOnlyContextReducer,
)
from sagents.v2.context.plugins.summary_ephemeral import (
    InMemoryConversationSummaryStore,
)
from sagents.v2.model import ModelCapabilities, ModelMessage
from sagents.v2.runtime.artifact.contracts import ArtifactStore
from sagents.v2.runtime.artifact.images import hydrate_image_blocks, hydrate_wishseen_history
from sagents.v2.runtime.artifact.media import hydrate_media_blocks
from sagents.v2.contracts.items import ContentBlock, ImageBlock
from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.context.session_history import (
    SessionHistoryLedgerBuilder,
    SessionHistoryReader,
)
from sagents.v2.context.message_time import historical_time_context
from sagents.v2.contracts.run_state import RunSnapshot, SessionConcurrencyMode
from sagents.v2.skill.tags import strip_skill_tags
from sagents.v2.prompt_i18n import prompt_text, run_prompt_language
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
        developer_instructions: str | None = None,
        providers: tuple[ContextSegmentProvider, ...] = (),
        runtime_context_in_user: bool = True,
        budget: ContextBudget | None = None,
        reducer: ContextReducer | None = None,
        history_reader: SessionHistoryReader | None = None,
        history_window: RunHistoryWindow | None = None,
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
        self.budget = budget
        self._compression_requested = {}
        self._projection_signatures = OrderedDict()
        self.reducer = reducer or SummaryOnlyContextReducer(
            InMemoryConversationSummaryStore()
        )
        self._history_window_enabled = history_window is not None
        self.history = (
            SessionHistoryLedgerBuilder(history_reader, history_window=history_window)
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

    async def _history_start(self, command: StartRun, run_id: str | None) -> int:
        # An explicit continuation has no new input. Its instructions attach to
        # the original user request and rely on history from the named Run.
        if (
            not self._history_window_enabled or self.history is None or run_id is None
            or command.continuation_of_run_id is not None
        ):
            return 0
        return await self.history.window_start(run_id)

    async def windowed_ledger(
        self, command: StartRun, ledger: tuple[ModelMessage, ...], *, run_id: str
    ) -> tuple[ModelMessage, ...]:
        start = await self._history_start(command, run_id)
        visible, _ = self._split_history_window(ledger, start)
        return visible

    @staticmethod
    def _split_history_window(
        ledger: tuple[ModelMessage, ...], start: int
    ) -> tuple[tuple[ModelMessage, ...], tuple[ModelMessage, ...]]:
        if not start:
            return ledger, ()
        prior = ledger[:start]
        # Trusted developer instructions retain the same visibility they have
        # without a window. They never enter the history search boundary.
        visible = (
            *(message for message in prior if message.role == "developer"),
            *ledger[start:],
        )
        omitted = tuple(message for message in prior if message.role not in {"system", "developer"})
        return visible, omitted

    async def prepare_history_search(
        self, command: StartRun, ledger: tuple[ModelMessage, ...], *, run_id: str, session_id: str
    ) -> None:
        """Publish the window boundary for recall before the first model call."""
        if self.projection_observer is None:
            return
        start = await self._history_start(command, run_id)
        if not start:
            return
        visible, omitted = self._split_history_window(ledger, start)
        await self.projection_observer.observe_projection(
            run_id,
            ContextProjection(
                messages=visible,
                historical_messages=omitted,
                source_message_count=len(ledger),
                dropped_message_count=len(omitted),
                strategy="history_window",
            ),
            session_id=session_id,
            source_messages=ledger,
        )

    async def restore_history_search(
        self, command: StartRun, ledger: tuple[ModelMessage, ...], *, run_id: str
    ) -> None:
        """Restore omitted history when a saved tool call runs before the next model request."""
        if (
            not self._history_window_enabled
            or self.projection_observer is None
            or run_id in self._projection_signatures
        ):
            return
        await self._project_context(command, ledger, run_id=run_id, history_only=True)

    async def prepare_messages(
        self,
        command: StartRun,
        ledger: tuple[ModelMessage, ...],
        *,
        run_id: str | None = None,
        reservation: ContextRequestReservation | None = None,
        media_capabilities: ModelCapabilities | None = None,
        run_snapshot: RunSnapshot | None = None,
    ) -> tuple[ModelMessage, ...]:
        return (
            await self.prepare_projection(
                command,
                ledger,
                run_id=run_id,
                reservation=reservation,
                media_capabilities=media_capabilities,
                **({"run_snapshot": run_snapshot} if run_snapshot is not None else {}),
            )
        ).messages

    async def prepare_projection(
        self,
        command: StartRun,
        ledger: tuple[ModelMessage, ...],
        *,
        run_id: str | None = None,
        reservation: ContextRequestReservation | None = None,
        media_capabilities: ModelCapabilities | None = None,
        run_snapshot: RunSnapshot | None = None,
    ) -> ContextProjection:
        """Create a fresh request view with deterministic context ordering.

        Stable system segments are regenerated for every request so cached or
        restored conversation messages do not become an accidental second copy
        of Agent instructions. Volatile runtime context is injected into the
        latest user message while preserving the original multimodal block order.
        """
        return await self._project_context(
            command, ledger, run_id=run_id, media_capabilities=media_capabilities,
            **({"run_snapshot": run_snapshot} if run_snapshot is not None else {}),
        )

    async def _project_context(
        self,
        command: StartRun,
        ledger: tuple[ModelMessage, ...],
        *,
        run_id: str | None,
        history_only: bool = False,
        media_capabilities: ModelCapabilities | None = None,
        run_snapshot: RunSnapshot | None = None,
    ) -> ContextProjection:
        if self.history is not None and run_id is not None:
            ledger = await self.history.with_message_times(ledger, run_id=run_id)
        source_ledger = ledger
        start = await self._history_start(command, run_id)
        ledger, omitted = self._split_history_window(ledger, start)
        segments = []
        latest_user = next((message for message in reversed(ledger) if is_user_request(message)), None)
        if (run_id is not None and latest_user is not None
                and latest_user.metadata.get("steer_id")
                and latest_user.metadata.get("steer_run_id", latest_user.metadata.get("source_run_id")) == run_id):
            segments.append(ContextSegment(
                segment_id="steering_guidance",
                content=prompt_text("steering", run_prompt_language(command.config.metadata)),
                stability=ContextStability.STABLE,
                priority=-170,
            ))
        for provider in (() if history_only else self.providers):
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
        payload = self._sanitize_tool_pairs(clean)
        if len(payload) == len(clean) and all(
            before is after for before, after in zip(clean, payload, strict=True)
        ):
            canonical_indices = tuple(source_positions)
        else:
            positions = defaultdict(deque)
            for index, message in zip(source_positions, clean, strict=True):
                positions[id(message)].append(index)
            canonical_indices = tuple(positions[id(message)].popleft() for message in payload)
        payload = tuple(strip_skill_tags(message) for message in payload)
        messages = (*system, *payload)
        # These scope fields are fixed at admission. The default driver can
        # reuse its commit result without a second distributed read.
        run = None
        if run_id is not None and self.history is not None and self.reducer is not None:
            run = (
                run_snapshot if run_snapshot is not None and run_snapshot.run_id == run_id
                else await self.history.reader.get_run(run_id)
            )
        scope = ContextReductionScope(
            context_key=self._summary_context_key(
                run.session_id if run is not None else run_id or command.agent_id,
                # A session-wide summary may contain turns excluded by this Run.
                run_id=run_id
                if run is not None
                and (start or run.concurrency_mode == SessionConcurrencyMode.SNAPSHOT_ISOLATED)
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
            force=not history_only and run_id in self._compression_requested,
            allow_summary_rewrite=(
                not history_only and self._compression_requested.get(run_id, False)
            ),
            # References only shrink this request view; canonical history keeps
            # the full results, so pressure that survives them must summarize.
            allow_reference_compaction=not (
                run_id in self._compression_requested
                and self._projection_signatures.get(run_id, (None, None))[1]
                == "reference_compaction"
            ),
        )
        required = not history_only and self._compression_requested.get(run_id, False)
        budget = None if history_only else self.budget
        try:
            projection = await self.reducer.reduce(messages, budget, scope=scope)
        except SageV2Error as exc:
            if required or exc.info.code not in {
                "context.no_reducible_history",
                "context.summary_no_progress",
            }:
                raise
            projection = await self.reducer.reduce(
                messages, budget, scope=scope.model_copy(update={"force": False})
            )
        if omitted:
            # Expose both sources of omitted history to the Session search index.
            projection = projection.model_copy(update={
                "historical_messages": (
                    *omitted, *projection.historical_messages,
                ),
                "source_message_count": projection.source_message_count + len(omitted),
                "dropped_message_count": projection.dropped_message_count + len(omitted),
                "dropped_digest": None,
                "strategy": (
                    "history_window" if projection.strategy == "none" else projection.strategy
                ),
            })
        if history_only:
            await self._observe_projection(run_id, run, projection, source_ledger)
            return projection
        self._compression_requested.pop(run_id, None)
        view = self._deduplicate_submission_images(
            projection.messages, continuation_of=command.continuation_of_run_id,
        )
        view = self._apply_inference_view(view, volatile)
        artifact_store = self.artifact_store
        if artifact_store is None and run_id is not None and self.history is not None:
            from sagents.v2.runtime.artifact import SessionArtifactStore

            artifact_store = SessionArtifactStore(self.history.reader, run_id)
        # Expand compatibility images only in the final inference view. Summary
        # coverage/digests must depend on immutable ledger content, not files.
        view = await hydrate_wishseen_history(view, command.config.metadata)
        view = await hydrate_image_blocks(view, artifact_store)
        view = await hydrate_media_blocks(view, artifact_store, media_capabilities)
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
        await self._observe_projection(run_id, run, projection, source_ledger)
        return projection

    async def _observe_projection(self, run_id, run, projection, source_ledger) -> None:
        if self.projection_observer is not None and run_id is not None:
            await self.projection_observer.observe_projection(
                run_id,
                projection,
                session_id=run.session_id if run is not None else None,
                source_messages=source_ledger,
            )

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
            if input_tokens >= maximum:
                LOGGER.bind(run_id=run_id).info(
                    "context.compression.usage_pressure",
                    "Provider-reported input usage reached the compression threshold",
                    attributes={"input_tokens": input_tokens, "threshold_tokens": maximum},
                )
                self.request_compression(run_id, required=False)

    @staticmethod
    def _deduplicate_submission_images(
        messages: tuple[ModelMessage, ...], *, continuation_of: str | None,
    ) -> tuple[ModelMessage, ...]:
        seen_submissions: set[tuple[str, str]] = set()
        continuation_batches = {
            tuple(block.uri for block in message.content if isinstance(block, ImageBlock))
            for message in messages
            if continuation_of is not None
            and message.metadata.get("source_run_id") == continuation_of
            and is_user_request(message)
        }
        prepared = []
        for message in reversed(messages):
            if not is_user_request(message):
                prepared.append(message)
                continue
            images = tuple(block for block in message.content if isinstance(block, ImageBlock))
            if not images:
                prepared.append(message)
                continue
            submission_id = message.metadata.get("client_message_id")
            source_run = message.metadata.get("source_run_id")
            duplicate = False
            if isinstance(submission_id, str) and submission_id:
                digest = hashlib.sha256()
                for block in message.content:
                    digest.update(block.model_dump_json().encode())
                    digest.update(b"\0")
                key = (submission_id, digest.hexdigest())
                duplicate = key in seen_submissions
                seen_submissions.add(key)
            elif len(images) > 1 and source_run and source_run != continuation_of:
                duplicate = tuple(block.uri for block in images) in continuation_batches
            if duplicate:
                message = message.model_copy(update={
                    "content": tuple(block for block in message.content if not isinstance(block, ImageBlock)),
                })
            if message.content:
                prepared.append(message)
        return tuple(reversed(prepared))

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
        if index is None:
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
        if not re.search(r"<current_time\b", runtime_text, flags=re.IGNORECASE):
            frozen = historical_time_context(original)
            if frozen:
                runtime_text = f"{frozen}\n{runtime_text}"
        if not runtime_text:
            return tuple(prepared)
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
        return historical_time_context(message)

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
        """Prune historical Memory pairs only when they have no opaque state."""

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
            # Protocol-owned state may sign the whole assistant/tool-call group.
            # Context cannot safely rewrite it or remove an individual call.
            if not message.provider_state
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
