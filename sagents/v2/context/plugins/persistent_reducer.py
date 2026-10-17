"""Durable, API-triggered history compression. Canonical history is immutable."""

from __future__ import annotations

from sagents.v2.context.contracts import ContextProjection
from sagents.v2.context.partition import conversation_units, current_turn_boundary
from sagents.v2.context.references import compact_unit_to_references
from sagents.v2.context.progress_summary import bounded_snapshot
from sagents.v2.context.summary import (
    create_summary,
    message_digests_async,
    ConversationSummary,
    SummarizationRequest,
)
from sagents.v2.contracts.conversation import is_user_request
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.model.recovery import model_call_budget


class _ExtractiveConversationSummarizer:
    async def summarize(self, request):
        return bounded_snapshot(request)


class PersistentSummaryContextReducer:
    plugin_id = "sage.context.reducer.persistent-summary"
    name = "Persistent summary context reducer"
    description = "Summarizes complete history only after API rejection or reported usage reaches a configured limit."

    def __init__(
        self,
        store,
        *,
        summarizer=None,
        summary_target_tokens=1024,
        protected_recent_units=4,
        max_summary_calls=64,
        unit_compactor=None,
        max_summary_source_tokens=None,
    ):
        # max_summary_source_tokens is accepted for existing manifests only.
        # It is deliberately never used to estimate or reject input.
        if (
            summary_target_tokens < 1
            or max_summary_calls < 1
            or protected_recent_units < 1
        ):
            raise ValueError("summary output and recovery limits must be positive")
        self.store = store
        self.summarizer = summarizer or _ExtractiveConversationSummarizer()
        self.summary_target_tokens = summary_target_tokens
        self.max_summary_calls = max_summary_calls
        self.protected_recent_units = protected_recent_units
        self.unit_compactor = unit_compactor

    async def reduce(self, messages, budget=None, *, scope=None):
        if scope is None:
            raise self._error(
                "context.summary_scope_required",
                "Persistent summaries require a session/run scope",
            )
        systems = tuple(m for m in messages if m.role in {"system", "developer"})
        payload = tuple(m for m in messages if m.role not in {"system", "developer"})
        canonical = (
            scope.canonical_messages
            if scope.canonical_messages is not None
            else payload
        )
        indices = (
            scope.canonical_indices
            if scope.canonical_messages is not None
            else tuple(range(len(payload)))
        )
        if (
            len(indices) != len(payload)
            or len(set(indices)) != len(indices)
            or any(i < 0 or i >= len(canonical) for i in indices)
        ):
            raise self._error(
                "context.invalid_source_mapping", "invalid canonical history mapping"
            )
        stored = await self.store.get(scope.context_key, session_id=scope.session_id)
        previous, _ = await self._validated_previous(stored, canonical)
        canonical_covered = len(previous.covered_message_digests) if previous else 0
        covered = sum(i < canonical_covered for i in indices)
        if any(i >= canonical_covered for i in indices[:covered]) or any(
            i < canonical_covered for i in indices[covered:]
        ):
            raise self._error(
                "context.invalid_source_mapping",
                "Canonical coverage is not a contiguous projection prefix",
            )
        remaining = payload[covered:]
        request_index = next(
            (i for i in range(len(payload) - 1, -1, -1) if is_user_request(payload[i])),
            None,
        )
        anchor = (
            (payload[request_index],)
            if request_index is not None and request_index < covered
            else ()
        )
        prefix = (self._summary_message(previous),) if previous else ()
        current = (*systems, *prefix, *anchor, *remaining)
        force = scope.force or (
            budget is not None
            and budget.max_messages is not None
            and len(current) > budget.max_messages
        )
        if not force:
            return ContextProjection(
                messages=current,
                historical_messages=canonical[:canonical_covered],
                source_message_count=len(messages),
                dropped_message_count=canonical_covered,
                strategy="persistent_summary" if previous else "none",
            )
        units = conversation_units(remaining)
        boundary = current_turn_boundary(units)
        # A single long turn can compress completed batches while retaining the
        # exact real user request and the latest complete tool/image batch.
        same_turn = boundary == 0
        if same_turn:
            boundary = max(0, len(units) - 1) if len(units) > 2 else 0
        selected_count = (
            max(2 if same_turn else 1, (boundary + 1) // 2) if boundary else 0
        )
        if (
            budget is not None
            and budget.max_messages is not None
            and len(current) > budget.max_messages
        ):
            removed = 0
            for index, unit in enumerate(units[:boundary]):
                removed += len(unit)
                selected_count = index + 1
                if (
                    len(current)
                    - removed
                    + (0 if previous else 1)
                    + (1 if same_turn else 0)
                    <= budget.max_messages
                ):
                    break
        if scope.force:
            # API pressure must also retire completed work in the active turn.
            # Stopping at the latest user boundary leaves long agent/tool loops
            # mostly intact. Keep a recent window of whole batches instead;
            # the exact latest user request is reinserted as an anchor below.
            selected_count = max(
                selected_count, len(units) - self.protected_recent_units
            )
        compacted = []
        changed = []
        for unit in units if scope.allow_reference_compaction else ():
            replacement = await (
                self.unit_compactor.compact(unit)
                if self.unit_compactor is not None
                else compact_unit_to_references(unit)
            )
            compacted.extend(replacement if replacement is not None else unit)
            if replacement is not None:
                changed.extend(
                    original
                    for original, projected in zip(unit, replacement, strict=True)
                    if original != projected
                )
        if changed:
            return ContextProjection(
                messages=(*systems, *prefix, *anchor, *compacted),
                historical_messages=(*canonical[:canonical_covered], *changed),
                source_message_count=len(messages),
                dropped_message_count=canonical_covered + len(changed),
                strategy="reference_compaction",
            )
        if not selected_count and units:
            latest = units[-1]
            expected = {c.tool_call_id for c in latest[0].tool_calls}
            actual = {m.tool_call_id for m in latest if m.role == "tool"}
            if expected and expected == actual:
                # A single oversized completed batch is reducible as a whole.
                # Keep the exact user anchor and retain all facts in the ledger.
                selected_count = len(units)
        if selected_count or previous is not None:
            selected = tuple(m for unit in units[:selected_count] for m in unit)
            end = covered + len(selected)
            canonical_end = max(indices[:end]) + 1 if selected else canonical_covered
            if any(i < canonical_end for i in indices[end:]):
                raise self._error(
                    "context.invalid_source_mapping",
                    "Compression would cover unprocessed canonical messages",
                )
            retained = tuple(m for unit in units[selected_count:] for m in unit)
            anchor = (
                (payload[request_index],)
                if request_index is not None and request_index < end
                else ()
            )
            with model_call_budget() as quota:
                quota.remaining = min(quota.remaining, self.max_summary_calls)
                text = await self.summarizer.summarize(
                    SummarizationRequest(
                        scope=scope,
                        messages=selected,
                        previous_summary=previous.text if previous else None,
                        target_tokens=self.summary_target_tokens,
                    )
                )
            if not text or not text.strip():
                raise self._error(
                    "context.summary_empty", "summarizer returned an empty summary"
                )
            source_characters = sum(len(m.model_dump_json()) for m in selected) + (
                len(previous.text) if previous else 0
            )
            if len(text.strip()) >= source_characters:
                raise self._error(
                    "context.summary_no_progress",
                    "Summary did not reduce the selected source",
                )
            # A failed or cancelled summary never advances canonical coverage.
            summary = create_summary(
                scope=scope,
                previous=previous,
                covered_messages=canonical[:canonical_end],
                covered_digests=await message_digests_async(canonical[:canonical_end]),
                text=text.strip(),
            )
            if stored is not None and previous is None:
                summary = summary.model_copy(update={"revision": stored.revision + 1})
            candidate = (*systems, self._summary_message(summary), *anchor, *retained)
            fewer_messages = (
                budget is not None
                and budget.max_messages is not None
                and len(candidate) < len(current)
            )
            if not fewer_messages and sum(
                len(m.model_dump_json()) for m in candidate
            ) >= sum(len(m.model_dump_json()) for m in current):
                raise self._error(
                    "context.summary_no_progress",
                    "Summarizer did not reduce the complete request view",
                )
            try:
                saved = await self.store.save(
                    summary, expected_revision=stored.revision if stored else None
                )
            except ValueError:
                # A competing identical projection may have won the CAS. Reuse
                # its validated complete prefix; never overwrite divergent work.
                winner = await self.store.get(
                    scope.context_key, session_id=scope.session_id
                )
                if winner is None or winner.revision == (
                    stored.revision if stored else None
                ):
                    raise
                valid, _ = await self._validated_previous(winner, canonical)
                if valid is None or len(valid.covered_message_digests) < canonical_end:
                    raise self._error(
                        "context.summary_revision_conflict",
                        "Another summary changed incompatible canonical coverage",
                    )
                canonical_end = len(valid.covered_message_digests)
                end = sum(i < canonical_end for i in indices)
                retained = payload[end:]
                anchor = (
                    (payload[request_index],)
                    if request_index is not None and request_index < end
                    else ()
                )
                saved = valid
            return ContextProjection(
                messages=(*systems, self._summary_message(saved), *anchor, *retained),
                historical_messages=canonical[:canonical_end],
                source_message_count=len(messages),
                dropped_message_count=canonical_end,
                dropped_digest=saved.source_digest,
                strategy="persistent_summary",
            )
        raise self._error(
            "context.no_reducible_history",
            "The API rejected mandatory instructions, the current request or latest Tool batch; no completed history remains to compress",
        )

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
            # Existing checkpoints used full message metadata. Accept their
            # exact legacy hash or the provenance-free hash for each message;
            # an active Run can contain both reconstructed and new messages.
            legacy = await message_digests_async(
                payload[:count], include_source_metadata=True
            )
            if all(
                saved in {current, old}
                for saved, current, old in zip(
                    summary.covered_message_digests, actual, legacy, strict=True
                )
            ):
                return summary, payload[count:]
            # Never apply a summary to a rewritten or fork-incompatible prefix.
            # The caller keeps the checkpoint so a later turn can replace it.
            return None, payload
        return summary, payload[count:]

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
