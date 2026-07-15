import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sagents.agent.fibre.agent_definition import AgentDefinition
from sagents.agent.fibre.orchestrator import FibreOrchestrator
from sagents.context.messages.message import MessageChunk
from sagents.context.session_context import SessionContext
from sagents.tool import ToolManager


def test_ordered_stream_batch_waits_until_downstream_resumes():
    async def scenario():
        orchestrator = FibreOrchestrator.__new__(FibreOrchestrator)
        queue = asyncio.Queue()
        chunks = [MessageChunk(role="assistant", content="first")]
        producer = asyncio.create_task(
            orchestrator._queue_container_stream_batch(queue, chunks)
        )

        queued_item = await queue.get()
        await asyncio.sleep(0)
        assert producer.done() is False

        stream = orchestrator._yield_queued_stream_item(queued_item)
        assert await anext(stream) == chunks
        assert producer.done() is False

        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        await asyncio.wait_for(producer, timeout=1)

    asyncio.run(scenario())


def test_ordered_stream_batch_close_cancels_waiting_producer():
    async def scenario():
        orchestrator = FibreOrchestrator.__new__(FibreOrchestrator)
        queue = asyncio.Queue()
        chunks = [MessageChunk(role="assistant", content="first")]
        producer = asyncio.create_task(
            orchestrator._queue_container_stream_batch(queue, chunks)
        )

        queued_item = await queue.get()
        stream = orchestrator._yield_queued_stream_item(queued_item)
        assert await anext(stream) == chunks
        await stream.aclose()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(producer, timeout=1)
        assert queued_item.persisted.cancelled() is True

    asyncio.run(scenario())


def test_ordered_stream_batch_downstream_error_cancels_ack():
    async def scenario():
        orchestrator = FibreOrchestrator.__new__(FibreOrchestrator)
        queue = asyncio.Queue()
        chunks = [MessageChunk(role="assistant", content="first")]
        producer = asyncio.create_task(
            orchestrator._queue_container_stream_batch(queue, chunks)
        )

        queued_item = await queue.get()
        stream = orchestrator._yield_queued_stream_item(queued_item)
        assert await anext(stream) == chunks
        with pytest.raises(RuntimeError, match="persistence failed"):
            await stream.athrow(RuntimeError("persistence failed"))
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(producer, timeout=1)
        assert queued_item.persisted.cancelled() is True

    asyncio.run(scenario())


def test_ordered_stream_batch_producer_cancellation_cancels_ack():
    async def scenario():
        orchestrator = FibreOrchestrator.__new__(FibreOrchestrator)
        queue = asyncio.Queue()
        producer = asyncio.create_task(
            orchestrator._queue_container_stream_batch(
                queue, [MessageChunk(role="assistant", content="first")]
            )
        )

        queued_item = await queue.get()
        producer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await producer
        assert queued_item.persisted.cancelled() is True

    asyncio.run(scenario())


def test_ordered_stream_ack_keeps_runtime_correction_after_previous_batch():
    async def scenario():
        orchestrator = FibreOrchestrator.__new__(FibreOrchestrator)
        queue = asyncio.Queue()
        ledger = []
        previous = MessageChunk(role="tool", content="result", tool_call_id="call-1")
        correction = MessageChunk(
            role="assistant",
            content="correct the next attempt",
            metadata={"llm_scope": "next_request", "sse_visible": False},
        )

        async def producer():
            await orchestrator._queue_container_stream_batch(queue, [previous])
            ledger.append(correction)

        producer_task = asyncio.create_task(producer())
        queued_item = await queue.get()
        stream = orchestrator._yield_queued_stream_item(queued_item)
        yielded = await anext(stream)
        ledger.extend(yielded)
        assert ledger == [previous]

        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        await asyncio.wait_for(producer_task, timeout=1)
        assert ledger == [previous, correction]

    asyncio.run(scenario())


class _FakeSessionManager:
    def __init__(self, session):
        self._session = session

    def get_live_session(self, session_id):
        return self._session


class _FakeBackendClient:
    def __init__(self):
        self.create_agent_kwargs = None

    async def check_health(self):
        return True

    async def create_agent(self, **kwargs):
        self.create_agent_kwargs = kwargs
        return kwargs["agent_id"]


def test_spawn_agent_defaults_empty_name_to_display_name():
    session_context = SimpleNamespace(
        agent_config={
            "agent_mode": "fibre",
            "available_tools": [],
            "available_skills": [],
            "available_workflows": {},
            "max_loop_count": 3,
        },
        custom_sub_agents=[],
        system_context={},
        user_id="user_1",
    )
    parent_session = SimpleNamespace(session_context=session_context)
    backend_client = _FakeBackendClient()

    orchestrator = FibreOrchestrator.__new__(FibreOrchestrator)
    orchestrator.agent = SimpleNamespace(
        agent_name="主Agent", model=None, model_config={}
    )
    orchestrator.backend_client = backend_client  # pyright: ignore[reportAttributeAccessIssue]
    orchestrator.sub_session_manager = _FakeSessionManager(parent_session)  # pyright: ignore[reportAttributeAccessIssue]
    orchestrator.sub_agents = {}
    orchestrator._get_fibre_system_prompt_content = lambda **kwargs: kwargs[  # pyright: ignore[reportAttributeAccessIssue]
        "custom_system_prompt"
    ]

    with patch("sagents.agent.fibre.orchestrator.random.choice", return_value="x"):
        agent_id = asyncio.run(
            orchestrator.spawn_agent(
                parent_session_id="parent_session",
                agent_id="agent_test",
                name="",
                description="Python expert",
                system_prompt="You are a Python expert.",
            )
        )

    assert agent_id == "agent_test"
    assert backend_client.create_agent_kwargs["name"] == "主Agent的子Agentx"  # pyright: ignore[reportOptionalSubscript]
    assert orchestrator.sub_agents["agent_test"].name == "主Agent的子Agentx"
    assert backend_client.create_agent_kwargs["agent_mode"] == "simple"  # pyright: ignore[reportOptionalSubscript]
    assert session_context.system_context["available_sub_agents"] == [
        {
            "agent_id": "agent_test",
            "name": "主Agent的子Agentx",
            "description": "Python expert",
        }
    ]


def test_get_configured_sub_agents_preserves_explicit_empty_list():
    session_context = SimpleNamespace(
        custom_sub_agents=[],
        agent_config={"custom_sub_agents": [{"agent_id": "fallback"}]},
        system_context={"custom_sub_agents": [{"agent_id": "system"}]},
    )

    assert FibreOrchestrator._get_configured_sub_agents(session_context) == []


def test_get_configured_sub_agents_returns_none_when_unconfigured():
    session_context = SimpleNamespace(
        custom_sub_agents=None,
        agent_config={},
        system_context={},
    )

    assert FibreOrchestrator._get_configured_sub_agents(session_context) is None


def test_publish_child_stream_coerces_roleless_stream_end_to_message_chunk():
    orchestrator = FibreOrchestrator.__new__(FibreOrchestrator)
    orchestrator.output_queue = asyncio.Queue()

    asyncio.run(
        orchestrator._publish_child_stream_chunks(
            [
                {
                    "type": "stream_end",
                    "session_id": "child",
                    "total_stream_count": 2,
                }
            ]
        )
    )

    published = orchestrator.output_queue.get_nowait()

    assert len(published) == 1
    assert isinstance(published[0], MessageChunk)
    assert published[0].session_id == "child"
    assert published[0].type == "stream_end"
    assert published[0].message_type == "stream_end"
    assert published[0].content == ""
    assert published[0].metadata["raw_stream_payload"]["total_stream_count"] == 2


class _FakeFibreSession:
    def __init__(self, session_id, session_context=None):
        self.session_id = session_id
        self.session_context = session_context
        self.child_session_ids = []

    def configure_runtime(self, **kwargs):
        self.runtime_kwargs = kwargs

    async def _ensure_session_context(self, **kwargs):
        context = SessionContext(
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            agent_id=kwargs["session_id"],
            session_root_space="/tmp/sage-test-sessions",
            sandbox_agent_workspace=self.runtime_kwargs.get("sandbox_agent_workspace"),
            system_context=kwargs.get("system_context"),
            tool_manager=kwargs.get("tool_manager"),
            skill_manager=kwargs.get("skill_manager"),
            parent_session_id=kwargs.get("parent_session_id"),
        )
        self.session_context = context
        return context

    def add_child_session(self, session_id):
        self.child_session_ids.append(session_id)


class _FakeFibreSessionManager:
    session_root_space = "/tmp/sage-test-sessions"

    def __init__(self, parent_session):
        self.parent_session = parent_session
        self.created = {}

    def get_live_session(self, session_id):
        if session_id == "parent":
            return self.parent_session
        return self.created.get(session_id)

    def get_or_create(self, session_id, session_space):
        session = _FakeFibreSession(session_id)
        self.created[session_id] = session
        return session


def _build_parent_fibre_session():
    context = SessionContext(
        session_id="parent",
        user_id="user_1",
        agent_id="leader",
        session_root_space="/tmp/sage-test-sessions",
        sandbox_agent_workspace="/tmp/fibre-workspace",
        system_context={},
        tool_manager=ToolManager(is_auto_discover=False, isolated=True),
    )
    context.set_agent_config(
        model="model",
        model_config={},
        system_prefix="",
        available_tools=["sys_spawn_agent", "sys_delegate_task"],
        available_skills=[],
        system_context={},
        available_workflows={},
        deep_thinking=False,
        agent_mode="fibre",
        more_suggest=False,
        max_loop_count=3,
        agent_id="leader",
    )
    return _FakeFibreSession("parent", context)


def test_fibre_child_without_mode_defaults_to_simple_not_parent_fibre():
    parent_session = _build_parent_fibre_session()
    orchestrator = FibreOrchestrator.__new__(FibreOrchestrator)
    orchestrator.agent = SimpleNamespace(model="model", model_config={})
    orchestrator.session_manager = _FakeFibreSessionManager(parent_session)
    orchestrator.sub_agents = {
        "worker": AgentDefinition(
            agent_id="worker",
            name="Worker",
            system_prompt="Work.",
            description="Worker",
            system_context={},
        )
    }

    sub_session = asyncio.run(
        orchestrator._get_or_create_sub_session(
            session_id="child", agent_id="worker", parent_session_id="parent"
        )
    )

    assert sub_session.session_context.agent_config["agent_mode"] == "simple"
    assert sub_session.session_context.sandbox_agent_workspace == (
        "/tmp/fibre-workspace/.sage/fibre_subagents/worker/child"
    )
    assert (
        sub_session.session_context.sandbox_agent_workspace
        != parent_session.session_context.sandbox_agent_workspace
    )


def test_fibre_child_uses_its_own_explicit_mode():
    parent_session = _build_parent_fibre_session()
    orchestrator = FibreOrchestrator.__new__(FibreOrchestrator)
    orchestrator.agent = SimpleNamespace(model="model", model_config={})
    orchestrator.session_manager = _FakeFibreSessionManager(parent_session)
    orchestrator.sub_agents = {
        "planner": AgentDefinition(
            agent_id="planner",
            name="Planner",
            system_prompt="Plan.",
            description="Planner",
            system_context={"agent_mode": "fibre"},
        )
    }

    sub_session = asyncio.run(
        orchestrator._get_or_create_sub_session(
            session_id="child", agent_id="planner", parent_session_id="parent"
        )
    )

    assert sub_session.session_context.agent_config["agent_mode"] == "fibre"
