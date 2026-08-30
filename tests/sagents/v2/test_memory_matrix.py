from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace

import pytest

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.context import DefaultContextAssembler, RunMetadataContextProvider
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.memory import (
    LLMMemoryRecallQueryGenerator,
    MemoryCapabilities,
    MemoryContextSource,
    MemoryDeleteResult,
    MemoryHit,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryService,
    MemoryWriteResult,
    NoopMemoryProvider,
)
from sagents.v2.memory.plugins.filesystem_bm25 import FilesystemBm25MemoryProvider
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.sagent import SAgent
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog, InMemoryToolExecutor
from sagents.v2.tool import (
    SideEffectLevel,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
    ToolInvocation,
)
from sagents.v2.tool.plugins.official.memory import MemoryTools


CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="user_1",
        principal_type=PrincipalType.USER,
        tenant_id="tenant_1",
    )
)


@dataclass
class FakeMemoryProvider:
    hits: tuple[MemoryHit, ...] = ()
    remembered: list[MemoryRecord] = field(default_factory=list)
    fail_remember: bool = False

    async def capabilities(self):
        return MemoryCapabilities(durable=True)

    async def recall(self, query: MemoryQuery):
        return self.hits[: query.limit]

    async def remember(self, record: MemoryRecord):
        if self.fail_remember:
            raise RuntimeError("memory unavailable")
        self.remembered.append(record)
        return MemoryWriteResult(memory_id=record.memory_id, created=True)

    async def forget(self, memory_id: str, *, scope: MemoryScope):
        return MemoryDeleteResult(memory_id=memory_id, deleted=False)

    async def get(self, memory_id: str, *, scope: MemoryScope):
        return next(
            (value for value in self.remembered if value.memory_id == memory_id), None
        )

    async def health(self):
        return {"status": "ok"}


def command(*, memory: bool = False):
    metadata = (
        {
            "memory_scope": {
                "tenant_id": "tenant_1",
                "principal_id": "user_1",
                "scope": "principal",
                "limit": 4,
            }
        }
        if memory
        else {}
    )
    from sagents.v2.contracts.commands import RunConfig

    return StartRun(
        agent_id="agent_1",
        input=(InputItem(role="user", content=(TextBlock(text="remember me"),)),),
        config=RunConfig(metadata=metadata),
        resolved_spec_hash="sha256:test",
        idempotency_key="start",
    )


@pytest.mark.asyncio
async def test_noop_memory_does_not_change_prompt_context():
    source = MemoryContextSource(MemoryService(NoopMemoryProvider()))
    assert await source.segments(command(memory=True)) == ()


@pytest.mark.asyncio
async def test_recall_enters_context_with_stable_provenance():
    now = utc_now()
    record = MemoryRecord(
        memory_id="memory_1",
        scope=MemoryScope(principal_id="user_1"),
        content="The user prefers concise answers.",
        created_at=now,
        updated_at=now,
    )
    provider = FakeMemoryProvider(
        hits=(MemoryHit(record=record, score=0.9, reason="semantic"),)
    )
    segments = await MemoryContextSource(MemoryService(provider)).segments(
        command(memory=True)
    )

    assert len(segments) == 1
    assert "[memory_1]" in segments[0].content
    assert segments[0].sensitive is True


@pytest.mark.asyncio
async def test_automatic_recall_is_a_real_tool_pair_not_runtime_context():
    runtime = ephemeral_runtime()
    request = command(memory=True).model_copy(
        update={
            "config": command(memory=True).config.model_copy(
                update={
                    "metadata": {
                        **command(memory=True).config.metadata,
                        "current_time": "Sat, 29 Aug 2026 23:17:06 +0800",
                    }
                }
            )
        }
    )
    handle = await runtime.start_run(request, CONTEXT)
    definition = ToolDefinition(
        name="search_memory",
        description="Search long-term Memory.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            "required": ["query", "top_k"],
            "additionalProperties": False,
        },
        side_effect_level=SideEffectLevel.READ,
    )

    async def search(call, _context):
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(
                TextBlock(
                    text=json.dumps(
                        {
                            "status": "success",
                            "results": [
                                {
                                    "memory_id": "memory_1",
                                    "content": "The user prefers concise answers.",
                                }
                            ],
                        }
                    )
                ),
            ),
        )

    executor = InMemoryToolExecutor(
        {"search_memory": definition}, {"search_memory": search}
    )
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="response_1",
                            text="done",
                            finish_reason="stop",
                        ),
                    ),
                )
            ),
        )
    )
    loop = AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog((definition,)),
        tool_executor=executor,
        automatic_memory_recall=True,
        context_assembler=DefaultContextAssembler(
            providers=(RunMetadataContextProvider(),),
            history_reader=runtime.session_store,
        ),
    )

    await loop.execute(handle.run_id, CONTEXT)

    assert len(executor.calls) == 1
    assert executor.calls[0].tool_name == "search_memory"
    assert executor.calls[0].arguments == {"query": "remember me", "top_k": 4}
    messages = model.requests[0].messages
    assert [message.role for message in messages] == ["user", "assistant", "tool"]
    assert messages[1].tool_calls[0].name == "search_memory"
    assert "memory_1" in messages[2].content[0].text
    user_text = messages[0].content[0].text
    assert "<current_time>Sat, 29 Aug 2026 23:17:06 +0800</current_time>" in user_text
    assert "Relevant long-term memory" not in user_text
    assert "memory_1" not in user_text


@pytest.mark.asyncio
async def test_llm_memory_query_plugin_generates_keywords_and_falls_back_safely():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="query_1",
                            text='{"query":"Sage runtime context v1"}',
                            finish_reason="stop",
                        ),
                    ),
                )
            ),
        )
    )
    generator = LLMMemoryRecallQueryGenerator(model, language="zh")

    query = await generator.generate(
        "请把 runtime context 改得和 v1 一样", run_id="run_1"
    )

    assert query == "Sage runtime context v1"
    assert model.requests[0].model_binding == "fast"
    assert model.requests[0].metadata["purpose"] == "memory_recall_query"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_remember", [False, True])
async def test_auto_ingestion_runs_after_commit_and_failure_does_not_rollback(
    fail_remember: bool,
):
    runtime = ephemeral_runtime()
    provider = FakeMemoryProvider(fail_remember=fail_remember)
    service = MemoryService(provider)
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="response_1",
                            text="done",
                            finish_reason="stop",
                        ),
                    ),
                )
            ),
        )
    )
    loop = AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
        context_assembler=DefaultContextAssembler(),
    )
    agent = SAgent(
        runtime=runtime,
        driver_factory=lambda _run_id: loop,
        memory_service=service,
    )

    stream = await agent.run_stream(command(), CONTEXT)
    events = [event async for event in stream.events]
    result = await stream.wait()

    assert result.state.value == "completed"
    assert events[-1].type == "run.completed"
    if fail_remember:
        assert provider.remembered == []
    else:
        assert {value.content for value in provider.remembered} == {"remember me"}
        assert all(value.kind == "conversation.user" for value in provider.remembered)
        assert provider.remembered[0].memory_id.startswith("memory_user_")
        assert provider.remembered[0].source["event_id"] not in provider.remembered[0].memory_id


@pytest.mark.asyncio
async def test_filesystem_bm25_memory_is_durable_scoped_and_deletable(tmp_path):
    scope = MemoryScope(
        tenant_id="tenant_1",
        principal_id="user_1",
        agent_id="agent_1",
    )
    other_scope = scope.model_copy(update={"principal_id": "user_2"})
    now = utc_now()
    provider = FilesystemBm25MemoryProvider(tmp_path / "memory")
    record = MemoryRecord(
        memory_id="memory_1",
        scope=scope,
        content="The deployment uses a blue green release strategy.",
        kind="fact",
        created_at=now,
        updated_at=now,
    )

    assert (await provider.remember(record)).created is True
    reopened = FilesystemBm25MemoryProvider(tmp_path / "memory")
    hits = await reopened.recall(
        MemoryQuery(scope=scope, text="deployment release", limit=5)
    )

    assert [value.record.memory_id for value in hits] == ["memory_1"]
    assert (
        await reopened.recall(
            MemoryQuery(scope=other_scope, text="deployment", limit=5)
        )
        == ()
    )
    assert await reopened.get("memory_1", scope=scope) == record
    assert (await reopened.forget("memory_1", scope=scope)).deleted is True
    assert await reopened.get("memory_1", scope=scope) is None


@pytest.mark.asyncio
async def test_filesystem_bm25_upsert_updates_only_one_index_row(tmp_path):
    scope = MemoryScope(principal_id="user_1")
    now = utc_now()
    provider = FilesystemBm25MemoryProvider(tmp_path / "memory")
    original = MemoryRecord(
        memory_id="preference.language",
        scope=scope,
        content="The user prefers English responses.",
        kind="preference",
        created_at=now,
        updated_at=now,
    )
    replacement = original.model_copy(
        update={
            "content": "The user prefers Chinese responses.",
            "created_at": now + timedelta(hours=1),
            "updated_at": now + timedelta(hours=1),
        }
    )

    assert (await provider.remember(original)).created is True
    assert (await provider.remember(replacement)).created is False
    stored = await provider.get("preference.language", scope=scope)

    assert stored is not None
    assert stored.content == replacement.content
    assert stored.created_at == now
    assert stored.updated_at == replacement.updated_at
    assert await provider.recall(MemoryQuery(scope=scope, text="English")) == ()
    assert [
        hit.record.memory_id
        for hit in await provider.recall(MemoryQuery(scope=scope, text="Chinese"))
    ] == ["preference.language"]
    with sqlite3.connect(provider.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_filesystem_bm25_imports_legacy_json_once_without_resurrection(tmp_path):
    root = tmp_path / "memory"
    legacy_directory = root / "scopes" / "legacy-scope"
    legacy_directory.mkdir(parents=True)
    scope = MemoryScope(principal_id="user_1")
    now = utc_now()
    record = MemoryRecord(
        memory_id="legacy_1",
        scope=scope,
        content="旧版记忆使用蓝绿发布。",
        created_at=now,
        updated_at=now,
    )
    (legacy_directory / "legacy_1.json").write_text(
        record.model_dump_json(), encoding="utf-8"
    )

    provider = FilesystemBm25MemoryProvider(root)
    assert [
        hit.record.memory_id
        for hit in await provider.recall(MemoryQuery(scope=scope, text="蓝绿发布"))
    ] == ["legacy_1"]
    assert (await provider.forget("legacy_1", scope=scope)).deleted is True

    reopened = FilesystemBm25MemoryProvider(root)
    assert await reopened.get("legacy_1", scope=scope) is None
    assert await reopened.recall(MemoryQuery(scope=scope, text="蓝绿发布")) == ()
    assert (await reopened.health())["storage"] == "sqlite-fts5"


@pytest.mark.asyncio
async def test_search_memory_uses_the_memory_service_agent_scope(tmp_path):
    provider = FilesystemBm25MemoryProvider(tmp_path / "memory")
    service = MemoryService(provider, scope_mode="agent")
    scope = service.scope(
        tenant_id="tenant_1",
        principal_id="user_1",
        agent_id="agent_1",
        session_id="session_1",
    )
    now = utc_now()
    await provider.remember(
        MemoryRecord(
            memory_id="memory_agent_1",
            scope=scope,
            content="The release uses a blue green deployment.",
            created_at=now,
            updated_at=now,
        )
    )
    invocation = ToolInvocation(
        call=ToolCall(
            tool_call_id="call_1",
            tool_name="search_memory",
            arguments={"query": "blue green release"},
            operation_id="operation_1",
            idempotency_key="key_1",
            owner_run_id="run_1",
            owner_agent_id="agent_1",
            owner_session_id="session_1",
        ),
        request_context=CONTEXT,
    )

    result = await MemoryTools(SimpleNamespace(memory_service=service)).search_memory(
        "blue green release", invocation=invocation
    )

    assert [value["memory_id"] for value in result["results"]] == ["memory_agent_1"]


@pytest.mark.parametrize(
    ("scope_mode", "expected_agent", "expected_session"),
    [
        ("principal", None, None),
        ("agent", "agent_1", None),
        ("session", "agent_1", "session_1"),
    ],
)
def test_memory_service_owns_provider_neutral_scope_resolution(
    scope_mode: str,
    expected_agent: str | None,
    expected_session: str | None,
):
    scope = MemoryService(FakeMemoryProvider(), scope_mode=scope_mode).scope(
        tenant_id="tenant_1",
        principal_id="user_1",
        agent_id="agent_1",
        session_id="session_1",
    )

    assert scope.agent_id == expected_agent
    assert scope.session_id == expected_session
