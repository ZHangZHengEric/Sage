"""Persistent hierarchical-summary context reduction without ledger mutation."""

from __future__ import annotations

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.items import TextBlock
from sagents.v2.context.contracts import (
    ContextBudget,
    ContextProjection,
    ContextReductionScope,
    ContextUnitCompactor,
)
from sagents.v2.context.plugins.estimator_json import JsonHeuristicTokenEstimator
from sagents.v2.context.plugins.summarizer_extractive import (
    ExtractiveConversationSummarizer,
)
from sagents.v2.context.summary import (
    ConversationSummarizer,
    ConversationSummary,
    ConversationSummaryStore,
    SummarizationRequest,
    create_summary,
    message_digest,
)
from sagents.v2.context.plugins.reference import ReferenceContextUnitCompactor
from sagents.v2.context.token_estimator import TokenEstimator
from sagents.v2.model.contracts import ModelMessage


class PersistentSummaryContextReducer:
    """Replace old history with a durable derived summary plus recent units.

    Raw messages remain in Runtime events and checkpoints.  The summary store is
    an independent replaceable port, so an embedding host may persist it in a
    database, object store, remote service, or memory rather than a filesystem.
    """

    plugin_id = "sage.context.reducer.persistent-summary"

    def __init__(
        self,
        store: ConversationSummaryStore,
        *,
        summarizer: ConversationSummarizer | None = None,
        estimator: TokenEstimator | None = None,
        summary_target_tokens: int = 1_024,
        protected_recent_units: int = 4,
        max_summary_source_tokens: int = 24_000,
        unit_compactor: ContextUnitCompactor | None = None,
    ) -> None:
        if summary_target_tokens <= 0:
            raise ValueError("summary_target_tokens must be positive")
        if protected_recent_units < 1:
            raise ValueError("protected_recent_units must be at least one")
        self.store = store
        self.summarizer = summarizer or ExtractiveConversationSummarizer()
        self.estimator = estimator or JsonHeuristicTokenEstimator()
        self.summary_target_tokens = summary_target_tokens
        self.protected_recent_units = protected_recent_units
        self.max_summary_source_tokens = max_summary_source_tokens
        self.unit_compactor = unit_compactor or ReferenceContextUnitCompactor(
            self.estimator
        )

    async def reduce(
        self,
        messages: tuple[ModelMessage, ...],
        budget: ContextBudget,
        *,
        scope: ContextReductionScope | None = None,
    ) -> ContextProjection:
        if scope is None:
            raise self._error(
                "context.summary_scope_required",
                "persistent summary reduction requires a Session/Run scope",
            )
        maximum = (
            budget.max_input_tokens
            - budget.reserve_output_tokens
            - budget.reserve_input_tokens
        )
        if maximum <= 0:
            raise self._error(
                "context.invalid_budget",
                "output and final-request reserves consume the input budget",
            )
        systems = tuple(message for message in messages if message.role == "system")
        payload = tuple(message for message in messages if message.role != "system")
        stored = await self.store.get(scope.context_key, session_id=scope.session_id)
        previous, remaining = self._validated_previous(stored, payload)
        if stored is not None and previous is None:
            # The context key was reused with a rewritten prefix.  Stale derived
            # state must not block creating a summary for the new canonical view.
            await self.store.delete(
                scope.context_key,
                expected_revision=stored.revision,
                session_id=scope.session_id,
            )
        summary_message = self._summary_message(previous) if previous else None
        current = (
            *systems,
            *((summary_message,) if summary_message else ()),
            *remaining,
        )
        if not self._over(current, maximum, budget.max_messages):
            if previous is None:
                return ContextProjection(
                    messages=messages,
                    estimated_tokens=self.estimator.estimate(messages),
                    source_message_count=len(messages),
                )
            return self._projection(
                messages,
                current,
                previous,
                historical_messages=payload[: len(previous.covered_message_digests)],
            )

        units = self._units(remaining)
        removable_count = self._removable_prefix_count(units)
        if removable_count == 0:
            compacted = await self._compact_units(units)
            if compacted is not None:
                compacted_messages = tuple(
                    message for unit in compacted for message in unit
                )
                result = (*systems, *compacted_messages)
                if not self._over(result, maximum, budget.max_messages):
                    changed = tuple(
                        original
                        for original, replacement in zip(
                            remaining, compacted_messages, strict=True
                        )
                        if original != replacement
                    )
                    return ContextProjection(
                        messages=result,
                        historical_messages=changed,
                        estimated_tokens=self.estimator.estimate(result),
                        source_message_count=len(messages),
                        dropped_message_count=len(changed),
                        strategy="reference_compaction",
                    )
            raise self._error(
                "context.budget_exhausted",
                "protected system, summary, and recent conversation exceed the model budget",
            )

        selected = []
        while removable_count > 0 and self._over(
            (*systems, *remaining), maximum, budget.max_messages
        ):
            selected.extend(units.pop(0))
            removable_count -= 1
            remaining = tuple(message for unit in units for message in unit)
            placeholder = self._placeholder_message(previous)
            if not self._over(
                (*systems, placeholder, *remaining), maximum, budget.max_messages
            ):
                break
        if not selected:
            selected.extend(units.pop(0))
            remaining = tuple(message for unit in units for message in unit)

        prior_covered_count = len(previous.covered_message_digests) if previous else 0
        all_covered = payload[: prior_covered_count + len(selected)]
        covered_digests = tuple(message_digest(message) for message in all_covered)
        text = await self._hierarchical_summary(
            scope,
            previous,
            tuple(selected),
        )
        summary = create_summary(
            scope=scope,
            previous=previous,
            covered_messages=all_covered,
            covered_digests=covered_digests,
            text=text,
            estimator=self.estimator,
        )
        self._require_compression_gain(previous, tuple(selected), summary)
        result = (*systems, self._summary_message(summary), *remaining)
        while self._over(result, maximum, budget.max_messages):
            if len(units) <= self.protected_recent_units:
                raise self._error(
                    "context.budget_exhausted",
                    "summary and protected recent conversation exceed the model budget",
                )
            more = units.pop(0)
            selected.extend(more)
            remaining = tuple(message for unit in units for message in unit)
            all_covered = payload[: prior_covered_count + len(selected)]
            covered_digests = tuple(message_digest(message) for message in all_covered)
            text = await self._hierarchical_summary(scope, previous, tuple(selected))
            summary = create_summary(
                scope=scope,
                previous=previous,
                covered_messages=all_covered,
                covered_digests=covered_digests,
                text=text,
                estimator=self.estimator,
            )
            self._require_compression_gain(previous, tuple(selected), summary)
            result = (*systems, self._summary_message(summary), *remaining)

        saved = await self.store.save(
            summary,
            expected_revision=previous.revision if previous else None,
        )
        return self._projection(
            messages,
            result,
            saved,
            historical_messages=all_covered,
        )

    async def _hierarchical_summary(
        self,
        scope: ContextReductionScope,
        previous: ConversationSummary | None,
        messages: tuple[ModelMessage, ...],
    ) -> str:
        rolling = previous.text if previous else None
        batch: list[ModelMessage] = []
        for message in messages:
            candidate = (*batch, message)
            if (
                batch
                and self.estimator.estimate(candidate) > self.max_summary_source_tokens
            ):
                rolling = await self.summarizer.summarize(
                    SummarizationRequest(
                        scope=scope,
                        messages=tuple(batch),
                        previous_summary=rolling,
                        target_tokens=self.summary_target_tokens,
                    )
                )
                batch = [message]
            else:
                batch.append(message)
        if batch:
            rolling = await self.summarizer.summarize(
                SummarizationRequest(
                    scope=scope,
                    messages=tuple(batch),
                    previous_summary=rolling,
                    target_tokens=self.summary_target_tokens,
                )
            )
        if not rolling or not rolling.strip():
            raise self._error(
                "context.summary_empty", "summarizer returned an empty summary"
            )
        return rolling.strip()

    @staticmethod
    def _validated_previous(
        summary: ConversationSummary | None,
        payload: tuple[ModelMessage, ...],
    ) -> tuple[ConversationSummary | None, tuple[ModelMessage, ...]]:
        if summary is None:
            return None, payload
        count = len(summary.covered_message_digests)
        if count > len(payload):
            return None, payload
        actual = tuple(message_digest(message) for message in payload[:count])
        if actual != summary.covered_message_digests:
            # Never apply a summary to a rewritten or fork-incompatible prefix.
            return None, payload
        return summary, payload[count:]

    def _placeholder_message(self, summary: ConversationSummary | None) -> ModelMessage:
        if summary is not None:
            return self._summary_message(summary)
        approximate_chars = max(256, self.summary_target_tokens * 4)
        return ModelMessage(
            role="system",
            content=(TextBlock(text="S" * approximate_chars),),
            metadata={"context_summary": True},
        )

    @staticmethod
    def _summary_message(summary: ConversationSummary) -> ModelMessage:
        return ModelMessage(
            role="system",
            content=(
                TextBlock(
                    text=(
                        "<conversation_summary>\n"
                        f"{summary.text}\n"
                        "</conversation_summary>"
                    )
                ),
            ),
            metadata={
                "context_summary": True,
                "summary_id": summary.summary_id,
                "summary_revision": summary.revision,
                "source_digest": summary.source_digest,
                "cache_segment": "semi_stable",
            },
        )

    def _projection(
        self,
        source: tuple[ModelMessage, ...],
        result: tuple[ModelMessage, ...],
        summary: ConversationSummary,
        *,
        historical_messages: tuple[ModelMessage, ...],
    ) -> ContextProjection:
        return ContextProjection(
            messages=result,
            historical_messages=historical_messages,
            estimated_tokens=self.estimator.estimate(result),
            source_message_count=len(source),
            dropped_message_count=len(summary.covered_message_digests),
            dropped_digest=summary.source_digest,
            strategy="persistent_summary",
        )

    def _over(
        self,
        messages: tuple[ModelMessage, ...],
        maximum: int,
        max_messages: int | None,
    ) -> bool:
        return self.estimator.estimate(messages) > maximum or (
            max_messages is not None and len(messages) > max_messages
        )

    def _removable_prefix_count(self, units: list[tuple[ModelMessage, ...]]) -> int:
        """Protect recent units and the latest real user request as one suffix."""

        recent_boundary = max(0, len(units) - self.protected_recent_units)
        latest_user_unit = next(
            (
                index
                for index in range(len(units) - 1, -1, -1)
                if any(message.role == "user" for message in units[index])
            ),
            len(units),
        )
        return min(recent_boundary, latest_user_unit)

    async def _compact_units(
        self, units: list[tuple[ModelMessage, ...]]
    ) -> list[tuple[ModelMessage, ...]] | None:
        compacted = []
        changed = False
        for unit in units:
            replacement = await self.unit_compactor.compact(unit)
            compacted.append(replacement or unit)
            changed = changed or replacement is not None
        return compacted if changed else None

    def _require_compression_gain(
        self,
        previous: ConversationSummary | None,
        selected: tuple[ModelMessage, ...],
        summary: ConversationSummary,
    ) -> None:
        """Judge only the reducible source; request reservations never enter here."""

        source = (
            *((self._summary_message(previous),) if previous else ()),
            *selected,
        )
        source_tokens = self.estimator.estimate(source)
        summary_tokens = self.estimator.estimate((self._summary_message(summary),))
        if summary_tokens >= source_tokens:
            raise self._error(
                "context.summary_not_reducing",
                "summary did not reduce the compressible conversation content",
            )

    @staticmethod
    def _units(messages: tuple[ModelMessage, ...]):
        units = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.role == "assistant" and message.tool_calls:
                expected = {call.tool_call_id for call in message.tool_calls}
                unit = [message]
                index += 1
                while index < len(messages) and messages[index].role == "tool":
                    if messages[index].tool_call_id in expected:
                        unit.append(messages[index])
                    index += 1
                units.append(tuple(unit))
                continue
            units.append((message,))
            index += 1
        return units

    @staticmethod
    def _error(code: str, message: str) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message=message,
                safe_to_resume=True,
            )
        )
