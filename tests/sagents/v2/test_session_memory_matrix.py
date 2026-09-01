from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from sagents.v2.context import ContextProjection
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.model import ModelMessage, ModelToolCall
from sagents.v2.session_memory import (
    SessionMemoryQuery,
    SessionMemoryRecord,
    SessionMemoryService,
    SessionMemoryHit,
    SqliteBm25SessionMemoryProvider,
)
from sagents.v2.tool import ToolCall, ToolInvocation
from sagents.v2.tool.official.memory import MemoryTools


@pytest.mark.asyncio
async def test_sqlite_session_memory_is_incremental_scoped_and_excludable(tmp_path):
    provider = SqliteBm25SessionMemoryProvider(tmp_path / "session-memory")
    old = SessionMemoryRecord(
        record_id="old",
        session_id="session_1",
        role="user",
        content="The historic deployment used a canary release.",
        position=0,
    )
    current = SessionMemoryRecord(
        record_id="current",
        session_id="session_1",
        role="user",
        content="The current deployment also discusses canary release.",
        position=1,
    )
    await provider.sync((old, current))
    await provider.sync((old, current))

    hits = await provider.recall(
        SessionMemoryQuery(
            session_id="session_1",
            run_id="run_1",
            text="canary deployment",
            included_record_ids=("old", "current"),
            excluded_record_ids=("current",),
        )
    )

    assert [hit.record.record_id for hit in hits] == ["old"]
    assert (
        await provider.recall(
            SessionMemoryQuery(
                session_id="session_2",
                run_id="run_2",
                text="canary deployment",
            )
        )
        == ()
    )
    await provider.forget_session("session_1")
    assert (
        await provider.recall(
            SessionMemoryQuery(
                session_id="session_1",
                run_id="run_1",
                text="canary deployment",
            )
        )
        == ()
    )


@dataclass
class _Reader:
    command: StartRun

    async def get_start_command(self, run_id: str) -> StartRun:
        del run_id
        return self.command


@dataclass
class _History:
    messages: tuple[ModelMessage, ...]

    async def rebuild(self, command, *, run_id, through_run_sequence=None):
        del command, run_id, through_run_sequence
        return self.messages


class _RecordingProvider:
    def __init__(self):
        self.recall_queries = []

    async def sync(self, records):
        self.records = records

    async def recall(self, query):
        self.recall_queries.append(query)
        return ()

    async def forget_session(self, session_id):
        del session_id


@pytest.mark.asyncio
async def test_session_memory_service_returns_only_messages_absent_from_request(
    tmp_path,
):
    old = ModelMessage(
        role="user",
        content=(TextBlock(text="The old release codename was Saturn."),),
        metadata={"source_item_id": "item_old", "source_run_id": "run_old"},
    )
    current = ModelMessage(
        role="user",
        content=(TextBlock(text="What was the release codename?"),),
        metadata={"source_item_id": "item_current", "source_run_id": "run_1"},
    )
    current_search_call = ModelMessage(
        role="assistant",
        content=(),
        tool_calls=(
            ModelToolCall(
                tool_call_id="call_1",
                name="search_memory",
                arguments={"query": "release codename Saturn"},
            ),
        ),
        metadata={"source_item_id": "item_search", "source_run_id": "run_1"},
    )
    command = StartRun(
        agent_id="agent_1",
        input=(InputItem(role="user", content=current.content),),
        resolved_spec_hash="sha256:test",
        idempotency_key="start",
    )
    service = SessionMemoryService(
        SqliteBm25SessionMemoryProvider(tmp_path / "session-memory"),
        _Reader(command),  # type: ignore[arg-type]
        history_builder=_History(
            (old, current, current_search_call)
        ),  # type: ignore[arg-type]
    )
    await service.observe_projection(
        "run_1",
        ContextProjection(
            messages=(current,),
            historical_messages=(old,),
            estimated_tokens=10,
            source_message_count=2,
        ),
    )

    hits = await service.recall(
        run_id="run_1",
        session_id="session_1",
        text="release codename Saturn",
        limit=5,
        tool_call_id="call_1",
    )
    assert [hit.record.record_id for hit in hits] == ["item_old"]

    await service.observe_projection(
        "run_1",
        ContextProjection(
            messages=(old, current), estimated_tokens=20, source_message_count=2
        ),
    )
    assert (
        await service.recall(
            run_id="run_1",
            session_id="session_1",
            text="release codename Saturn",
            limit=5,
            tool_call_id="call_1",
        )
        == ()
    )


@pytest.mark.asyncio
async def test_session_memory_never_infers_history_when_reducer_declares_none():
    old = ModelMessage(
        role="user",
        content=(TextBlock(text="Visible history"),),
        metadata={"source_item_id": "item_old"},
    )
    current = ModelMessage(
        role="user",
        content=(TextBlock(text="Current question"),),
        metadata={"source_item_id": "item_current"},
    )
    command = StartRun(
        agent_id="agent_1",
        input=(InputItem(role="user", content=current.content),),
        resolved_spec_hash="sha256:test",
        idempotency_key="start-visible",
    )
    provider = _RecordingProvider()
    service = SessionMemoryService(
        provider,  # type: ignore[arg-type]
        _Reader(command),  # type: ignore[arg-type]
        history_builder=_History((old, current)),  # type: ignore[arg-type]
    )

    assert (
        await service.recall(
            run_id="run_1",
            session_id="session_1",
            text="history",
            limit=5,
        )
        == ()
    )
    assert provider.recall_queries == []

    await service.observe_projection(
        "run_1",
        ContextProjection(
            # The old message is absent from the request, but the reducer did
            # not declare it as history. Session Memory must not guess.
            messages=(current,), estimated_tokens=20, source_message_count=2
        ),
    )

    assert (
        await service.recall(
            run_id="run_1",
            session_id="session_1",
            text="history",
            limit=5,
        )
        == ()
    )
    assert provider.recall_queries == []


class _SessionSearch:
    async def recall(self, **kwargs):
        assert kwargs["tool_call_id"] == "call_1"
        return (
            SessionMemoryHit(
                record=SessionMemoryRecord(
                    record_id="item_old",
                    session_id="session_1",
                    role="user",
                    content="The old release codename was Saturn.",
                    position=0,
                ),
                score=0.8,
            ),
        )


@pytest.mark.asyncio
async def test_search_memory_can_return_session_results_without_long_term_provider():
    invocation = ToolInvocation(
        call=ToolCall(
            tool_call_id="call_1",
            tool_name="search_memory",
            arguments={"query": "release codename"},
            operation_id="operation_1",
            idempotency_key="key_1",
            owner_run_id="run_1",
            owner_agent_id="agent_1",
            owner_session_id="session_1",
        ),
        request_context=RequestContext(
            actor=ActorRef(
                principal_id="user_1",
                principal_type=PrincipalType.USER,
            )
        ),
    )
    result = await MemoryTools(
        SimpleNamespace(
            memory_service=None,
            session_memory_service=_SessionSearch(),
        )
    ).search_memory("release codename", invocation=invocation)

    assert result["long_term_results"] == []
    assert result["results"] == result["session_results"]
    assert result["results"][0]["memory_type"] == "session"
