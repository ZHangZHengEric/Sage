from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.context import DefaultContextAssembler
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.memory import (
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
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.sagent import SAgent
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog, InMemoryToolExecutor


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
@pytest.mark.parametrize("fail_remember", [False, True])
async def test_auto_ingestion_runs_after_commit_and_failure_does_not_rollback(
    fail_remember: bool,
):
    runtime = HarnessRuntime()
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
        assert {value.content for value in provider.remembered} >= {
            "remember me",
            "done",
        }


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
