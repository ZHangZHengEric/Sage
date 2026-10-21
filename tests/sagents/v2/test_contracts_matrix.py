from __future__ import annotations

from typing import Any, TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Literal

from tests.sagents.v2.event_fixture import event_data

from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from sagents.v2.contracts.commands import (
    CommandDecision,
    CommandReceipt,
    InputItem,
    RunConfig,
    StartRun,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.events import (
    EVENT_CATALOG,
    EventDurability,
    EventSource,
    EventSourceType,
    FlowEventData,
    ItemEventData,
    JobEventData,
    ProtocolEventData,
    RunEventData,
    RuntimeEvent,
    TurnEventData,
)
from sagents.v2.contracts.items import (
    ContentBlock,
    MessageItemData,
    TextBlock,
)
from sagents.v2.contracts.principals import ActorRef, PrincipalType
from sagents.v2.contracts.run_state import (
    EventCursor,
    RunResult,
    RunState,
    SessionConcurrencyMode,
)
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelRequest,
    ModelStreamEvent,
    ModelToolDefinition,
)


NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)
ACTOR = ActorRef(
    principal_id="user_test",
    principal_type=PrincipalType.USER,
    tenant_id="tenant_test",
)
SOURCE = EventSource(source_type=EventSourceType.RUNTIME, source_id="runtime_test")


def test_streaming_text_deltas_preserve_markdown_whitespace():
    markdown_delta = "\n\n## 实时标题\n\n"

    model_event = ModelStreamEvent(
        kind=ModelEventKind.TEXT_DELTA,
        delta=markdown_delta,
    )
    runtime_data = ItemEventData(operation="delta", delta=model_event.delta)
    restored = ItemEventData.model_validate_json(runtime_data.model_dump_json())

    assert model_event.delta == markdown_delta
    assert runtime_data.delta == markdown_delta
    assert restored.delta == markdown_delta


def test_model_request_canonicalizes_tool_wire_order_for_prompt_cache():
    alpha = ModelToolDefinition(
        name="alpha",
        description="Alpha tool",
        input_schema={"type": "object"},
    )
    zeta = ModelToolDefinition(
        name="zeta",
        description="Zeta tool",
        input_schema={"type": "object"},
    )

    first = ModelRequest(
        request_id="request_1",
        run_id="run_1",
        model_binding="primary",
        messages=(),
        tools=(zeta, alpha),
    )
    second = ModelRequest(
        request_id="request_2",
        run_id="run_1",
        model_binding="primary",
        messages=(),
        tools=(alpha, zeta),
    )

    assert tuple(tool.name for tool in first.tools) == ("alpha", "zeta")
    assert first.tools == second.tools


def _error() -> RuntimeErrorInfo:
    return RuntimeErrorInfo(
        code="test.error",
        category=ErrorCategory.INTERNAL,
        message="test failure",
    )


@pytest.mark.parametrize("event_type", sorted(EVENT_CATALOG))
def test_every_catalog_event_accepts_its_declared_kind_and_durability(event_type):
    definition = EVENT_CATALOG[event_type]
    durable = definition.durability == EventDurability.DURABLE

    event = RuntimeEvent(
        event_id=f"event_{event_type.replace('.', '_')}",
        type=event_type,
        occurred_at=NOW,
        durability=definition.durability,
        session_id="session_1",
        run_id="run_1",
        session_sequence=1 if durable else None,
        run_sequence=1,
        actor=ACTOR,
        source=SOURCE,
        data=event_data(definition.data_kind),
    )

    restored = RuntimeEvent.model_validate_json(event.model_dump_json())
    assert restored == event
    assert restored.data.kind == definition.data_kind


@pytest.mark.parametrize(
    ("event_type", "wrong_data"),
    [
        ("run.started", TurnEventData(state="started")),
        ("tool.call.started", RunEventData(state="running")),
        ("interaction.requested", JobEventData(job_id="job_1", state="running")),
        ("stream.snapshot", FlowEventData(state="started")),
    ],
)
def test_catalog_rejects_mismatched_payload_family(event_type, wrong_data):
    definition = EVENT_CATALOG[event_type]
    with pytest.raises(ValidationError, match="requires data.kind"):
        RuntimeEvent(
            event_id="event_bad_kind",
            type=event_type,
            occurred_at=NOW,
            durability=definition.durability,
            session_id="session_1",
            run_id="run_1",
            session_sequence=(
                1 if definition.durability == EventDurability.DURABLE else None
            ),
            run_sequence=1,
            actor=ACTOR,
            source=SOURCE,
            data=wrong_data,
        )


@pytest.mark.parametrize(
    ("event_type", "ignorable", "valid"),
    [
        ("unknown.event", False, False),
        ("unknown.event", True, False),
        ("extension.vendor.progress", False, False),
        ("extension.vendor.progress", True, True),
    ],
)
def test_unknown_event_requires_extension_namespace_and_ignorable(
    event_type, ignorable, valid
):
    kwargs: dict[str, Any] = dict(
        event_id="event_extension",
        type=event_type,
        occurred_at=NOW,
        durability=EventDurability.REPLAY_BUFFERED,
        session_id="session_1",
        run_id="run_1",
        run_sequence=1,
        actor=ACTOR,
        source=SOURCE,
        data=ProtocolEventData(state="vendor_progress"),
        ignorable=ignorable,
    )
    if valid:
        assert RuntimeEvent(**kwargs).ignorable is True
    else:
        with pytest.raises(ValidationError, match="unknown events"):
            RuntimeEvent(**kwargs)


@pytest.mark.parametrize(
    ("durability", "session_sequence", "valid"),
    [
        (EventDurability.DURABLE, 1, True),
        (EventDurability.DURABLE, None, False),
        (EventDurability.REPLAY_BUFFERED, None, True),
        (EventDurability.REPLAY_BUFFERED, 1, False),
        (EventDurability.TRANSIENT, None, True),
        (EventDurability.TRANSIENT, 1, False),
    ],
)
def test_session_sequence_matrix(durability, session_sequence, valid):
    kwargs: dict[str, Any] = dict(
        event_id="event_extension",
        type="extension.test.event",
        occurred_at=NOW,
        durability=durability,
        session_id="session_1",
        run_id="run_1",
        session_sequence=session_sequence,
        run_sequence=1,
        actor=ACTOR,
        source=SOURCE,
        data=ProtocolEventData(state="test"),
        ignorable=True,
    )
    if valid:
        assert RuntimeEvent(**kwargs).session_sequence == session_sequence
    else:
        with pytest.raises(ValidationError):
            RuntimeEvent(**kwargs)


def test_content_block_discriminator_nested_round_trip_and_extra_rejection():
    adapter = TypeAdapter(ContentBlock)
    block = adapter.validate_python({"kind": "text", "text": "hello"})
    assert block == TextBlock(text="hello")

    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "text", "text": "hello", "extra": 1})

    item = MessageItemData(role="assistant", content=(TextBlock(text="done"),))
    restored = MessageItemData.model_validate_json(item.model_dump_json())
    assert cast(TextBlock, restored.content[0]).text == "done"


def test_start_input_accepts_assistant_history_but_not_external_tool_rows():
    history = InputItem(role="assistant", content=(TextBlock(text="previous"),))
    assert history.role == "assistant"

    with pytest.raises(ValidationError):
        InputItem(role=cast("Literal['user', 'assistant', 'system', 'developer']", "tool"), content=(TextBlock(text="untrusted"),))


def test_run_config_preserves_legacy_skill_names_with_spaces():
    value = RunConfig(enabled_skills=("Excel Analysis",))

    assert value.enabled_skills == ("Excel Analysis",)


@pytest.mark.parametrize(
    ("mode", "session_id", "valid"),
    [
        (SessionConcurrencyMode.SERIAL, None, True),
        (SessionConcurrencyMode.SNAPSHOT_ISOLATED, None, True),
        (SessionConcurrencyMode.FORK, None, False),
        (SessionConcurrencyMode.FORK, "session_parent", True),
    ],
)
def test_start_run_concurrency_contract(mode, session_id, valid):
    kwargs: dict[str, Any] = dict(
        session_id=session_id,
        agent_id="agent_test",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        session_concurrency_mode=mode,
        resolved_spec_hash="sha256:test",
        idempotency_key="request_1",
    )
    if valid:
        assert StartRun(**kwargs).session_concurrency_mode == mode
    else:
        with pytest.raises(ValidationError, match="fork mode"):
            StartRun(**kwargs)


@pytest.mark.parametrize(
    ("decision", "error", "valid"),
    [
        (CommandDecision.ACCEPTED, None, True),
        (CommandDecision.DUPLICATE, None, True),
        (CommandDecision.REJECTED, _error(), True),
        (CommandDecision.REJECTED, None, False),
        (CommandDecision.ACCEPTED, _error(), False),
    ],
)
def test_command_receipt_error_matrix(decision, error, valid):
    kwargs: dict[str, Any] = dict(
        command_id="command_1",
        decision=decision,
        target_id="run_1",
        error=error,
    )
    if valid:
        assert CommandReceipt(**kwargs).decision == decision
    else:
        with pytest.raises(ValidationError):
            CommandReceipt(**kwargs)


@pytest.mark.parametrize(
    ("state", "error", "valid"),
    [
        (RunState.COMPLETED, None, True),
        (RunState.CANCELLED, None, True),
        (RunState.FAILED, _error(), True),
        (RunState.FAILED, None, False),
        (RunState.RUNNING, None, False),
        (RunState.SUSPENDED, None, False),
    ],
)
def test_run_result_terminal_matrix(state, error, valid):
    kwargs: dict[str, Any] = dict(
        session_id="session_1",
        run_id="run_1",
        outcome=state,
        error=error,
        completed_at=NOW,
        final_cursor=EventCursor(run_id="run_1", run_sequence=1),
    )
    if valid:
        assert RunResult(**kwargs).outcome == state
    else:
        with pytest.raises(ValidationError):
            RunResult(**kwargs)


def test_contracts_reject_unknown_fields_at_public_boundary():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ActorRef.model_validate(dict(principal_id="user_1", principal_type=PrincipalType.USER, unexpected="value"))
