from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sagents.v2.contracts.events import (
    EVENT_CATALOG,
    ArtifactEventData,
    CheckpointEventData,
    ContinuationEventData,
    EventDurability,
    EventSource,
    EventSourceType,
    FlowEventData,
    InteractionEventData,
    ItemEventData,
    JobEventData,
    PolicyEventData,
    ProtocolEventData,
    RunEventData,
    RuntimeEvent,
    SandboxEventData,
    SessionCommitEventData,
    SteeringEventData,
    StepEventData,
    ToolEventData,
    TurnEventData,
    UsageEventData,
)
from sagents.v2.contracts.items import (
    ArtifactRef,
    ItemSnapshot,
    ItemStatus,
    MessageItemData,
    ReasoningItemData,
    TextBlock,
    ToolCallItemData,
    ToolResultItemData,
    UsageSummary,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.principals import ActorRef, PrincipalType
from sagents.v2.interfaces.protocols.a2a import A2AProtocolAdapter
from sagents.v2.interfaces.protocols.acp import AcpProtocolAdapter
from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
from sagents.v2.interfaces.protocols.contracts import AdapterResult
from sagents.v2.interfaces.protocols.mcp import McpProtocolAdapter
from sagents.v2.interfaces.protocols.native import NativeProtocolAdapter


NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)
ACTOR = ActorRef(principal_id="agent_1", principal_type=PrincipalType.AGENT)
SOURCE = EventSource(source_type=EventSourceType.AGENT)


def data_for(kind):
    if kind == "run":
        return RunEventData(state="running")
    if kind == "turn":
        return TurnEventData(state="started")
    if kind == "step":
        return StepEventData(state="started")
    if kind == "item":
        return ItemEventData(operation="started")
    if kind == "tool":
        return ToolEventData(tool_call_id="call_1", tool_name="tool", state="started")
    if kind == "job":
        return JobEventData(job_id="job_1", state="running")
    if kind == "interaction":
        return InteractionEventData(
            interaction_id="interaction_1",
            interaction_type="approval",
            state="requested",
        )
    if kind == "checkpoint":
        return CheckpointEventData(
            checkpoint_id="checkpoint_1",
            checkpoint_codec_version="1",
            run_sequence=1,
            session_revision=1,
        )
    if kind == "steering":
        return SteeringEventData(steer_id="steer_1", state="accepted")
    if kind == "continuation":
        return ContinuationEventData(
            action="complete_run",
            reason_code="done",
            reason="done",
            decision_hash="sha256:decision",
        )
    if kind == "flow":
        return FlowEventData(state="started", flow_id="flow_1")
    if kind == "artifact":
        return ArtifactEventData(
            state="created",
            artifact=ArtifactRef(
                artifact_id="artifact_1", uri="artifact://1", name="file.txt"
            ),
        )
    if kind == "sandbox":
        return SandboxEventData(sandbox_id="sandbox_1", state="ready")
    if kind == "policy":
        return PolicyEventData(
            decision_id="decision_1", decision="allow", policy_version="1"
        )
    if kind == "usage":
        return UsageEventData(usage=UsageSummary(input_tokens=1))
    if kind == "protocol":
        return ProtocolEventData(state="snapshot")
    if kind == "session_commit":
        return SessionCommitEventData(
            proposal_id="proposal_1",
            source_run_id="run_1",
            state="proposed",
            base_session_revision=0,
            base_session_sequence=0,
        )
    raise AssertionError(kind)


def event(event_type, *, data=None, sequence=1, item_id=None):
    definition = EVENT_CATALOG[event_type]
    value = data or data_for(definition.data_kind)
    return RuntimeEvent(
        event_id=f"event_{sequence}",
        type=event_type,
        occurred_at=NOW,
        durability=definition.durability,
        session_id="session_1",
        run_id="run_1",
        session_sequence=(
            sequence if definition.durability == EventDurability.DURABLE else None
        ),
        run_sequence=sequence,
        item_id=item_id,
        job_id="job_1" if definition.data_kind == "job" else None,
        interaction_id=(
            "interaction_1" if definition.data_kind == "interaction" else None
        ),
        actor=ACTOR,
        source=SOURCE,
        data=value,
    )


@pytest.mark.parametrize(
    "adapter_factory",
    [AgUiProtocolAdapter, AcpProtocolAdapter, McpProtocolAdapter, A2AProtocolAdapter],
)
@pytest.mark.parametrize("event_type", sorted(EVENT_CATALOG))
def test_every_catalog_event_is_mapped_or_explicitly_loss_reported(
    adapter_factory, event_type
):
    result = adapter_factory().translate(event(event_type))
    assert result.frames or result.losses
    assert all(frame.source_event_id == "event_1" for frame in result.frames)
    assert all(loss.source_event_id == "event_1" for loss in result.losses)


def test_adapter_result_contract_rejects_silent_drop():
    with pytest.raises(ValidationError, match="silently drop"):
        AdapterResult()


@pytest.mark.asyncio
async def test_capability_negotiation_matrix_is_honest():
    native = await NativeProtocolAdapter().capabilities()
    agui = await AgUiProtocolAdapter().capabilities()
    agui_plain = await AgUiProtocolAdapter(enable_sage_extensions=False).capabilities()
    acp = await AcpProtocolAdapter().capabilities()
    mcp = await McpProtocolAdapter().capabilities()
    a2a = await A2AProtocolAdapter().capabilities()

    assert native.supports_pause_resume and native.supports_exact_cursor_replay
    assert agui.supports_pause_resume and "sage-native-events" in agui.extensions
    assert not agui_plain.supports_pause_resume
    assert acp.supports_interactions and not acp.supports_exact_cursor_replay
    assert mcp.supports_tool_lifecycle and not mcp.supports_run_lifecycle
    assert a2a.supports_run_lifecycle and not a2a.supports_tool_lifecycle


def test_native_adapter_is_lossless_round_trip_for_all_catalog_events():
    adapter = NativeProtocolAdapter()
    for index, event_type in enumerate(sorted(EVENT_CATALOG), start=1):
        source = event(event_type, sequence=index)
        result = adapter.translate(source)
        assert result.losses == ()
        assert RuntimeEvent.model_validate(result.frames[0].payload) == source


def item_snapshot(item_id, data):
    return ItemSnapshot(
        item_id=item_id,
        run_id="run_1",
        status=ItemStatus.COMPLETED,
        data=data,
        created_at=NOW,
        updated_at=NOW,
    )


def test_ag_ui_text_delta_and_completion_form_one_lifecycle_without_duplicate_text():
    adapter = AgUiProtocolAdapter()
    delta = adapter.translate(
        event(
            "message.delta",
            data=ItemEventData(operation="delta", delta="hel"),
            item_id="item_1",
        )
    )
    complete = adapter.translate(
        event(
            "message.completed",
            data=ItemEventData(
                operation="completed",
                item=item_snapshot(
                    "item_1",
                    MessageItemData(
                        role="assistant", content=(TextBlock(text="hello"),)
                    ),
                ),
            ),
            sequence=2,
            item_id="item_1",
        )
    )
    assert [frame.name for frame in delta.frames] == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
    ]
    assert [frame.name for frame in complete.frames] == ["TEXT_MESSAGE_END"]


def test_ag_ui_completed_snapshots_cover_text_reasoning_tool_and_result():
    adapter = AgUiProtocolAdapter()
    cases = [
        (
            "message.completed",
            MessageItemData(role="assistant", content=(TextBlock(text="answer"),)),
            ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"],
        ),
        (
            "reasoning.completed",
            ReasoningItemData(content=(TextBlock(text="thought"),)),
            [
                "REASONING_START",
                "REASONING_MESSAGE_START",
                "REASONING_MESSAGE_CONTENT",
                "REASONING_MESSAGE_END",
                "REASONING_END",
            ],
        ),
        (
            "item.completed",
            ToolCallItemData(
                tool_call_id="call_1", tool_name="read", arguments={"path": "a"}
            ),
            ["TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END"],
        ),
        (
            "item.completed",
            ToolResultItemData(tool_call_id="call_1", content=(TextBlock(text="ok"),)),
            ["TOOL_CALL_RESULT"],
        ),
    ]
    for index, (event_type, data, names) in enumerate(cases, start=1):
        result = adapter.translate(
            event(
                event_type,
                data=ItemEventData(
                    operation="completed",
                    item=item_snapshot(f"item_{index}", data),
                ),
                sequence=index,
                item_id=f"item_{index}",
            )
        )
        assert [frame.name for frame in result.frames] == names


def test_ag_ui_pause_is_extension_or_explicit_loss_never_run_finished():
    source = event(
        "run.suspended", data=RunEventData(state="suspended", reason="approval")
    )
    extended = AgUiProtocolAdapter().translate(source)
    plain = AgUiProtocolAdapter(enable_sage_extensions=False).translate(source)
    assert [frame.name for frame in extended.frames] == ["CUSTOM"]
    assert extended.losses[0].preserved_by_extension is True
    assert plain.frames == ()
    assert plain.losses[0].fidelity.value == "unsupported"


def test_acp_interaction_is_request_with_stable_interaction_id():
    source = event(
        "interaction.requested",
        data=InteractionEventData(
            interaction_id="interaction_1",
            interaction_type="questionnaire",
            state="requested",
            allowed_decisions=("submit", "cancel"),
            payload={
                "prompt": "Choose a target",
                "questions": [
                    {
                        "id": "target",
                        "type": "single",
                        "title": "Target",
                        "options": ["staging", "production"],
                    }
                ],
            },
        ),
    )
    result = AcpProtocolAdapter().translate(source)
    frame_value = result.frames[0]
    assert frame_value.frame_kind == "request"
    assert frame_value.frame_id == "interaction_1"
    assert frame_value.name == "session/request_input"
    assert frame_value.payload["allowedDecisions"] == ["submit", "cancel"]
    assert frame_value.payload["payload"]["questions"][0]["id"] == "target"


def test_questionnaire_survives_a2a_and_mcp_projection():
    source = event(
        "interaction.requested",
        data=InteractionEventData(
            interaction_id="interaction_1",
            interaction_type="questionnaire",
            state="requested",
            allowed_decisions=("submit", "cancel"),
            payload={
                "prompt": "Choose a target",
                "questions": [
                    {
                        "id": "target",
                        "type": "multiple",
                        "title": "Targets",
                        "options": ["staging", "production"],
                    }
                ],
            },
        ),
    )

    a2a = A2AProtocolAdapter().translate(source).frames[0].payload["status"]
    mcp = McpProtocolAdapter().translate(source).frames[0].payload

    assert a2a["allowedDecisions"] == ["submit", "cancel"]
    assert a2a["payload"]["questions"][0]["id"] == "target"
    assert mcp["requestedSchema"]["properties"]["target"] == {
        "type": "array",
        "title": "Targets",
        "items": {"type": "string", "enum": ["staging", "production"]},
    }
    assert mcp["sageInteraction"]["payload"] == source.data.payload


@pytest.mark.parametrize("adapter", [AcpProtocolAdapter(), A2AProtocolAdapter()])
def test_terminal_error_message_and_code_survive_protocol_projection(adapter):
    source = event(
        "run.failed",
        data=RunEventData(
            state="failed",
            error=RuntimeErrorInfo(
                code="model.provider_error",
                category=ErrorCategory.PROVIDER_TRANSIENT,
                message="模型服务暂时不可用，请稍后重试。",
            ),
        ),
    )
    payload = adapter.translate(source).frames[0].payload
    status = payload.get("status") or payload["update"]
    assert status["message"] == "模型服务暂时不可用，请稍后重试。"
    assert status["errorCode"] == "model.provider_error"


def test_mcp_explicitly_refuses_to_masquerade_as_run_protocol():
    result = McpProtocolAdapter().translate(event("run.started"))
    assert result.frames == ()
    assert result.losses[0].code == "mcp.not_run_protocol"


@pytest.mark.parametrize(
    ("event_type", "state"),
    [
        ("run.queued", "submitted"),
        ("run.started", "working"),
        ("run.suspended", "input-required"),
        ("run.completed", "completed"),
        ("run.failed", "failed"),
        ("run.cancelled", "canceled"),
    ],
)
def test_a2a_task_status_mapping_matrix(event_type, state):
    result = A2AProtocolAdapter().translate(event(event_type))
    assert result.frames[0].payload["status"]["state"] == state
