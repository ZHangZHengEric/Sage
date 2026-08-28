"""Project canonical Session events into a provider-neutral model ledger."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.events import ItemEventData, RuntimeEvent
from sagents.v2.contracts.items import (
    ItemStatus,
    MessageItemData,
    TextBlock,
    ToolCallItemData,
    ToolResultItemData,
    Visibility,
)
from sagents.v2.contracts.run_state import (
    RunSnapshot,
    SessionConcurrencyMode,
    SessionSnapshot,
)
from sagents.v2.contracts.session_commit import (
    SessionCommitProposal,
    SessionCommitProposalStatus,
)
from sagents.v2.model import ModelMessage, ModelToolCall


class SessionHistoryReader(Protocol):
    """Read-only repository surface required for model-context reconstruction."""

    async def get_run(self, run_id: str) -> RunSnapshot: ...
    async def get_session(self, session_id: str) -> SessionSnapshot: ...

    async def list_session_runs(self, session_id: str) -> tuple[RunSnapshot, ...]: ...

    async def list_session_commit_proposals(
        self, session_id: str
    ) -> tuple[SessionCommitProposal, ...]: ...

    async def read_session_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> tuple[RuntimeEvent, ...]: ...

    async def read_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> tuple[RuntimeEvent, ...]: ...

    async def read_fork_base_events(self, run_id: str) -> tuple[RuntimeEvent, ...]: ...


class RunLedgerRebuilder(Protocol):
    """Replaceable event-to-model ledger reconstruction boundary."""

    async def rebuild(
        self,
        command: StartRun,
        *,
        run_id: str,
        through_run_sequence: int | None = None,
    ) -> tuple[ModelMessage, ...]: ...


@dataclass
class _ProjectedMessage:
    message: ModelMessage
    step_key: tuple[str, str | None, str | None]


class SessionEventModelProjector:
    """Convert authoritative completed Items into ordered ModelMessages.

    Lifecycle, reasoning, usage, policy, and protocol events are deliberately
    ignored. Tool-call Items are folded into the assistant message from the same
    Step, and ToolResult Items become provider-neutral `tool` messages. The
    normal ContextAssembler sanitizer performs the final complete-pair check.
    """

    _MODEL_VISIBLE_STATUSES = frozenset(
        {ItemStatus.COMPLETED, ItemStatus.FAILED, ItemStatus.DECLINED}
    )
    _MODEL_VISIBLE_VISIBILITIES = frozenset(
        {Visibility.PUBLIC, Visibility.MODEL_VISIBLE}
    )

    def project(self, events: tuple[RuntimeEvent, ...]) -> tuple[ModelMessage, ...]:
        projected: list[_ProjectedMessage] = []
        seen_items: set[str] = set()
        for event in events:
            data = event.data
            if not isinstance(data, ItemEventData) or data.item is None:
                continue
            if data.operation not in {"completed", "snapshot"}:
                continue
            item = data.item
            if item.item_id in seen_items:
                continue
            seen_items.add(item.item_id)
            if item.status not in self._MODEL_VISIBLE_STATUSES:
                continue
            if item.visibility not in self._MODEL_VISIBLE_VISIBILITIES:
                continue

            step_key = (event.run_id, event.turn_id, event.step_id)
            source = item.data
            if isinstance(source, MessageItemData):
                # Tool messages require a tool_call_id, which MessageItemData
                # intentionally does not carry. Native tool history is rebuilt
                # from ToolResultItemData below instead.
                if source.role == "tool":
                    continue
                projected.append(
                    _ProjectedMessage(
                        message=ModelMessage(
                            role=source.role,
                            content=source.content,
                            metadata={
                                **source.metadata,
                                **self._metadata(event, item.item_id),
                            },
                        ),
                        step_key=step_key,
                    )
                )
            elif isinstance(source, ToolCallItemData):
                arguments = self._tool_arguments(source)
                if arguments is None:
                    continue
                call = ModelToolCall(
                    tool_call_id=source.tool_call_id,
                    name=source.tool_name,
                    arguments=arguments,
                )
                assistant = self._assistant_for_step(projected, step_key)
                if assistant is None:
                    projected.append(
                        _ProjectedMessage(
                            message=ModelMessage(
                                role="assistant",
                                tool_calls=(call,),
                                metadata=self._metadata(event, item.item_id),
                            ),
                            step_key=step_key,
                        )
                    )
                else:
                    assistant.message = assistant.message.model_copy(
                        update={"tool_calls": (*assistant.message.tool_calls, call)}
                    )
            elif isinstance(source, ToolResultItemData):
                content = source.content
                if not content and source.error is not None:
                    content = (TextBlock(text=source.error.message),)
                projected.append(
                    _ProjectedMessage(
                        message=ModelMessage(
                            role="tool",
                            tool_call_id=source.tool_call_id,
                            content=content,
                            metadata=self._metadata(event, item.item_id),
                        ),
                        step_key=step_key,
                    )
                )
        return tuple(value.message for value in projected)

    @staticmethod
    def _assistant_for_step(
        projected: list[_ProjectedMessage],
        step_key: tuple[str, str | None, str | None],
    ) -> _ProjectedMessage | None:
        for value in reversed(projected):
            if value.step_key == step_key and value.message.role == "assistant":
                return value
            if value.step_key != step_key:
                break
        return None

    @staticmethod
    def _tool_arguments(source: ToolCallItemData) -> dict | None:
        if source.arguments is not None:
            return source.arguments
        if source.arguments_json is None:
            return {}
        try:
            decoded = json.loads(source.arguments_json)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, dict) else None

    @staticmethod
    def _metadata(event: RuntimeEvent, item_id: str) -> dict[str, str]:
        return {
            "source_session_id": event.session_id,
            "source_run_id": event.run_id,
            "source_item_id": item_id,
        }


class SessionHistoryLedgerBuilder:
    """Rebuild model history from canonical completed Item events.

    Serial Runs read their own Session through ``base_session_sequence``. Fork
    Runs read the immutable parent prefix copied into the child at acceptance,
    so deleting a parent does not break the child. Snapshot Runs may read a
    stale boundary. Their output enters later canonical history only after a
    published SessionCommitProposal reaches the reader's boundary.
    """

    def __init__(
        self,
        reader: SessionHistoryReader,
        projector: SessionEventModelProjector | None = None,
    ) -> None:
        self.reader = reader
        self.projector = projector or SessionEventModelProjector()

    async def build(
        self, command: StartRun, *, run_id: str
    ) -> tuple[ModelMessage, ...]:
        """Build the initial ledger, including only the current acceptance prefix."""

        base_events = await self._base_events(run_id)
        current_prefix = []
        for event in await self.reader.read_events(run_id):
            if event.type == "run.started":
                break
            current_prefix.append(event)
        current_ledger = self.projector.project(tuple(current_prefix))
        if not current_ledger:
            # This fallback supports custom repositories that accept the Run
            # but intentionally do not expose canonical input Items.
            current_ledger = tuple(
                ModelMessage(
                    role=item.role, content=item.content, metadata=item.metadata
                )
                for item in command.input
            )
        return (*self.projector.project(base_events), *current_ledger)

    async def rebuild(
        self,
        command: StartRun,
        *,
        run_id: str,
        through_run_sequence: int | None = None,
    ) -> tuple[ModelMessage, ...]:
        """Rebuild an active Run ledger through an exact checkpoint boundary."""

        base_events = await self._base_events(run_id)
        current_events = await self.reader.read_events(run_id)
        if through_run_sequence is not None:
            current_events = tuple(
                event
                for event in current_events
                if event.run_sequence <= through_run_sequence
            )
        current_ledger = self.projector.project(current_events)
        if not current_ledger:
            current_ledger = tuple(
                ModelMessage(
                    role=item.role, content=item.content, metadata=item.metadata
                )
                for item in command.input
            )
        return (*self.projector.project(base_events), *current_ledger)

    async def _base_events(self, run_id: str) -> tuple[RuntimeEvent, ...]:
        run = await self.reader.get_run(run_id)
        session = await self.reader.get_session(run.session_id)
        if run.concurrency_mode == SessionConcurrencyMode.FORK:
            if session.parent_session_id is None:
                raise ValueError("fork Run requires a parent Session")
            return await self.reader.read_fork_base_events(run_id)

        history_session_id = run.session_id

        history_runs = await self.reader.list_session_runs(history_session_id)
        proposals = await self.reader.list_session_commit_proposals(history_session_id)
        # Publication becomes effective only at its own durable Session event.
        # A Run accepted from an earlier boundary must not retroactively see a
        # proposal that happened to be published before context assembly.
        published_snapshot_run_ids = {
            value.source_run_id
            for value in proposals
            if value.status == SessionCommitProposalStatus.PUBLISHED
            and value.published_session_sequence is not None
            and value.published_session_sequence <= run.base_session_sequence
        }
        canonical_run_ids = {
            value.run_id
            for value in history_runs
            if value.concurrency_mode != SessionConcurrencyMode.SNAPSHOT_ISOLATED
            or value.run_id in published_snapshot_run_ids
        }
        base_events = (
            await self.reader.read_session_events(
                history_session_id, limit=run.base_session_sequence
            )
            if run.base_session_sequence > 0
            else ()
        )
        base_events = tuple(
            event
            for event in base_events
            if event.session_sequence is not None
            and event.session_sequence <= run.base_session_sequence
            and event.run_id in canonical_run_ids
        )

        return base_events
