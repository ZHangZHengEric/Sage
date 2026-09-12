"""Persistent hierarchical-summary context reduction without ledger mutation."""

from __future__ import annotations

import json

from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.items import JsonBlock, TextBlock
from sagents.v2.context.contracts import (
    ContextBudget,
    ContextProjection,
    ContextReductionScope,
    ContextUnitCompactor,
)
from sagents.v2.context.summary import (
    ConversationSummarizer,
    ConversationSummary,
    ConversationSummaryStore,
    SummarizationRequest,
    create_summary,
    message_digests_async,
)
from sagents.v2.context.token_estimator import TokenEstimator, MessageTokenCounter
from sagents.v2.context.estimation import WireSizeTokenEstimator
from sagents.v2.context.partition import (
    conversation_units,
    current_turn_boundary,
    protected_boundary,
)
from sagents.v2.model.contracts import ModelMessage


class _ExtractiveConversationSummarizer:
    async def summarize(self, request: SummarizationRequest) -> str:
        labels = {
            "en": (
                "Previous summary:",
                "New history:",
                "Tool calls:",
                "[...history condensed...]",
            ),
            "zh": ("之前的摘要：", "新增历史：", "工具调用：", "[……历史已压缩……]"),
            "pt": (
                "Resumo anterior:",
                "Novo histórico:",
                "Chamadas de ferramentas:",
                "[...histórico condensado...]",
            ),
        }[request.response_language]
        lines = []
        if request.previous_summary:
            lines.extend([labels[0], request.previous_summary.strip(), labels[1]])
        for message in request.messages:
            values = []
            for block in message.content:
                if isinstance(block, TextBlock):
                    values.append(block.text)
                elif isinstance(block, JsonBlock):
                    values.append(
                        json.dumps(block.value, ensure_ascii=False, sort_keys=True)
                    )
                else:
                    values.append(
                        json.dumps(block.model_dump(mode="json"), ensure_ascii=False)
                    )
            content = "\n".join(values)
            if message.tool_calls:
                calls = ", ".join(
                    f"{call.name}({json.dumps(call.arguments, ensure_ascii=False, sort_keys=True)})"
                    for call in message.tool_calls
                )
                content = f"{content}\n{labels[2]} {calls}".strip()
            lines.append(f"{message.role.upper()}: {content}".strip())
        maximum = max(256, request.target_tokens * 4)
        value = "\n".join(lines).strip()
        if len(value) <= maximum:
            return value
        head = value[: maximum // 3]
        tail = value[-(maximum - len(head) - 32) :]
        return f"{head}\n{labels[3]}\n{tail}"


class _ReferenceContextUnitCompactor:
    def __init__(self, estimator: TokenEstimator) -> None:
        self.estimator = estimator

    async def compact(
        self, unit: tuple[ModelMessage, ...]
    ) -> tuple[ModelMessage, ...] | None:
        result = []
        changed = False
        for message in unit:
            reference = message.metadata.get("context_reference")
            if message.role != "tool" or not isinstance(reference, (dict, str)):
                result.append(message)
                continue
            encoded = json.dumps(
                reference,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            replacement = message.model_copy(
                update={
                    "content": (
                        TextBlock(
                            text=f"<tool_result_reference>{encoded}</tool_result_reference>"
                        ),
                    ),
                    "metadata": {
                        **message.metadata,
                        "context_compacted_to_reference": True,
                    },
                }
            )
            if self.estimator.estimate((replacement,)) < self.estimator.estimate(
                (message,)
            ):
                result.append(replacement)
                changed = True
            else:
                result.append(message)
        return tuple(result) if changed else None


class PersistentSummaryContextReducer:
    """Replace old history with a durable derived summary plus recent units.

    Raw messages remain in Runtime events and checkpoints.  The summary store is
    an independent replaceable port, so an embedding host may persist it in a
    database, object store, remote service, or memory rather than a filesystem.
    """

    plugin_id = "sage.context.reducer.persistent-summary"
    name = "Persistent summary context reducer"
    description = "Summarizes older units into a durable rolling conversation summary."

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
        max_summary_calls: int = 4,
    ) -> None:
        if summary_target_tokens <= 0:
            raise ValueError("summary_target_tokens must be positive")
        if protected_recent_units < 1:
            raise ValueError("protected_recent_units must be at least one")
        if max_summary_source_tokens <= 0:
            raise ValueError("max_summary_source_tokens must be positive")
        if max_summary_calls < 1:
            raise ValueError("max_summary_calls must be positive")
        self.max_summary_calls = max_summary_calls
        self.store = store
        self.summarizer = summarizer or _ExtractiveConversationSummarizer()
        self.estimator = estimator or WireSizeTokenEstimator()
        self.summary_target_tokens = summary_target_tokens
        self.protected_recent_units = protected_recent_units
        self.max_summary_source_tokens = max_summary_source_tokens
        self.unit_compactor = unit_compactor or _ReferenceContextUnitCompactor(
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
        systems = tuple(
            message for message in messages if message.role in {"system", "developer"}
        )
        payload = tuple(
            message
            for message in messages
            if message.role not in {"system", "developer"}
        )
        counter = await MessageTokenCounter.create(self.estimator, messages)
        system_tokens = counter.estimate(systems)
        if system_tokens > budget.max_system_tokens:
            raise self._error(
                "context.system_budget_exhausted",
                "system instructions exceed their token budget",
            )
        stored = await self.store.get(scope.context_key, session_id=scope.session_id)
        previous, remaining = await self._validated_previous(stored, payload)
        if stored is not None and previous is None:
            await self.store.delete(
                scope.context_key,
                expected_revision=stored.revision,
                session_id=scope.session_id,
            )
        summary_prefix = (self._summary_message(previous),) if previous else ()
        current = (*systems, *summary_prefix, *remaining)

        def over(values):
            return counter.estimate(values) > maximum or (
                budget.max_messages is not None and len(values) > budget.max_messages
            )

        if not over(current):
            return ContextProjection(
                messages=current,
                historical_messages=payload[: len(payload) - len(remaining)],
                estimated_tokens=counter.estimate(current),
                source_message_count=len(messages),
                dropped_message_count=len(payload) - len(remaining),
                dropped_digest=previous.source_digest if previous else None,
                strategy="persistent_summary" if previous else "none",
            )

        units = self._units(remaining)
        costs = [counter.estimate(unit) for unit in units]
        mandatory = current_turn_boundary(units)
        changed = []
        # Before any model call, compact oversized mandatory tool results using
        # their durable references. Never lose an existing summary on this path.
        mandatory_messages = tuple(
            message for unit in units[mandatory:] for message in unit
        )
        if over((*systems, *summary_prefix, *mandatory_messages)):
            for index in range(mandatory, len(units)):
                replacement = await self.unit_compactor.compact(units[index])
                if replacement is not None:
                    changed.extend(
                        original
                        for original, new in zip(units[index], replacement, strict=True)
                        if original != new
                    )
                    units[index] = replacement
                    costs[index] = counter.estimate(replacement)
            mandatory_messages = tuple(
                message for unit in units[mandatory:] for message in unit
            )
            if over((*systems, *mandatory_messages)) or (
                mandatory == 0
                and over((*systems, *summary_prefix, *mandatory_messages))
            ):
                raise self._error(
                    "context.budget_exhausted",
                    "system, summary and current user turn exceed the model budget",
                )
        if mandatory == 0:
            result = (*systems, *summary_prefix, *mandatory_messages)
            historical = (*payload[: len(payload) - len(remaining)], *changed)
            return ContextProjection(
                messages=result,
                historical_messages=historical,
                estimated_tokens=counter.estimate(result),
                source_message_count=len(messages),
                dropped_message_count=len(historical),
                dropped_digest=previous.source_digest if previous else None,
                strategy="reference_compaction",
            )

        soft_tokens = min(
            budget.protected_recent_tokens, max(0, maximum - system_tokens) // 3
        )
        boundary = protected_boundary(
            units,
            costs,
            recent_units=self.protected_recent_units,
            recent_tokens=soft_tokens,
        )
        placeholder = self._placeholder_message(previous)
        placeholder_tokens = counter.estimate((placeholder,))
        # Linear accounting for additive built-ins; arbitrary custom estimators
        # retain complete-request semantics instead of unsafe token subtraction.
        suffix_tokens = [0] * (len(units) + 1)
        suffix_counts = [0] * (len(units) + 1)
        for index in range(len(units) - 1, -1, -1):
            suffix_tokens[index] = suffix_tokens[index + 1] + costs[index]
            suffix_counts[index] = suffix_counts[index + 1] + len(units[index])

        def candidate_over(index):
            if counter.costs is None:
                return over(
                    (
                        *systems,
                        placeholder,
                        *(m for unit in units[index:] for m in unit),
                    )
                )
            return system_tokens + placeholder_tokens + suffix_tokens[
                index
            ] > maximum or (
                budget.max_messages is not None
                and len(systems) + 1 + suffix_counts[index] > budget.max_messages
            )

        # Summarize the eligible prefix once, leaving a bounded recent suffix.
        # This creates headroom instead of re-triggering on every new message.
        selected_count = boundary
        # Recent historical protection is soft. Relax it before failing a Run.
        while selected_count < mandatory and candidate_over(selected_count):
            selected_count += 1
        selected_count = max(1, selected_count)
        selected = tuple(message for unit in units[:selected_count] for message in unit)
        retained = tuple(message for unit in units[selected_count:] for message in unit)
        available = maximum - counter.estimate((*systems, *retained))
        if available <= 0 or (
            budget.max_messages is not None
            and len(systems) + 1 + len(retained) > budget.max_messages
        ):
            raise self._error(
                "context.budget_exhausted", "no space remains for a history summary"
            )
        target = max(1, min(self.summary_target_tokens, available - 128))
        prior_count = len(previous.covered_message_digests) if previous else 0
        all_covered = payload[: prior_count + len(selected)]
        covered_digests = await message_digests_async(all_covered)
        text = await self._hierarchical_summary(
            scope, previous, selected, target_tokens=target
        )
        summary = create_summary(
            scope=scope,
            previous=previous,
            covered_messages=all_covered,
            covered_digests=covered_digests,
            text=text,
            estimator=self.estimator,
        )
        self._require_compression_gain(previous, selected, summary)
        result = (*systems, self._summary_message(summary), *retained)
        # Do not retry progressively larger overlapping sources. A plugin that
        # ignores its requested target must fail without committing derived state.
        if over(result):
            raise self._error(
                "context.budget_exhausted",
                "summary exceeds its reserved request budget",
            )
        saved = await self.store.save(
            summary, expected_revision=previous.revision if previous else None
        )
        return self._projection(
            messages, result, saved, historical_messages=(*all_covered, *changed)
        )

    async def _hierarchical_summary(
        self, scope, previous, messages, *, target_tokens=None
    ):
        target = target_tokens or self.summary_target_tokens
        counter = await MessageTokenCounter.create(self.estimator, messages)
        batches = []
        batch = []
        batch_tokens = 0
        # Reserve room for the rolling summary as well as framing on every call.
        previous_tokens = (
            counter.estimate((self._summary_message(previous),)) if previous else 0
        )
        reserve = max(target + 256, previous_tokens)
        limit = self.max_summary_source_tokens - reserve
        if limit <= 0:
            raise self._error(
                "context.summary_source_too_large",
                "rolling summary consumes the source budget",
            )
        for unit in self._units(messages):
            cost = counter.estimate(unit)
            if cost > limit:
                replacement = await self.unit_compactor.compact(unit)
                if replacement is not None:
                    unit = replacement
                    cost = counter.estimate(unit)
                if cost > limit:
                    raise self._error(
                        "context.summary_source_too_large",
                        "indivisible history unit exceeds the summary source budget",
                    )
            candidate_tokens = (
                batch_tokens + cost
                if counter.costs is not None
                else counter.estimate((*batch, *unit))
            )
            if batch and candidate_tokens > limit:
                batches.append(tuple(batch))
                batch, batch_tokens = [], 0
            batch.extend(unit)
            batch_tokens += cost
        if batch:
            batches.append(tuple(batch))
        if len(batches) > self.max_summary_calls:
            raise self._error(
                "context.summary_work_limit",
                "history exceeds the bounded summary work per projection",
            )
        rolling = previous.text if previous else None
        for batch in batches:
            # Intermediate output can be larger than the requested target. Check
            # its actual size before sending it to the next summary request.
            prefix = (
                (ModelMessage(role="system", content=(TextBlock(text=rolling),)),)
                if rolling
                else ()
            )
            if counter.estimate((*prefix, *batch)) > self.max_summary_source_tokens:
                raise self._error(
                    "context.summary_source_too_large",
                    "rolling summary exceeds the source budget",
                )
            rolling = await self.summarizer.summarize(
                SummarizationRequest(
                    scope=scope,
                    messages=batch,
                    previous_summary=rolling,
                    target_tokens=target,
                )
            )
            if not rolling or not rolling.strip():
                raise self._error(
                    "context.summary_empty", "summarizer returned an empty summary"
                )
        return rolling.strip()

    @staticmethod
    async def _validated_previous(
        summary: ConversationSummary | None,
        payload: tuple[ModelMessage, ...],
    ) -> tuple[ConversationSummary | None, tuple[ModelMessage, ...]]:
        if summary is None:
            return None, payload
        count = len(summary.covered_message_digests)
        if count > len(payload):
            return None, payload
        actual = await message_digests_async(payload[:count])
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

    _units = staticmethod(conversation_units)

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
