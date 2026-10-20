from __future__ import annotations

from tests.sagents.v2.event_fixture import event_data

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sagents.v2.contracts.events import (
    EVENT_CATALOG,
    EventDurability,
    EventSource,
    EventSourceType,
    InteractionEventData,
    ItemEventData,
    RunEventData,
    RuntimeEvent,
)
from sagents.v2.contracts.items import (
    ItemSnapshot,
    ItemStatus,
    JsonBlock,
    MessageItemData,
    ReasoningItemData,
    TextBlock,
    ToolCallItemData,
    ToolResultItemData,
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


def event(event_type, *, data=None, sequence=1, item_id=None):
    definition = EVENT_CATALOG[event_type]
    value = data or event_data(definition.data_kind)
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


# Minimal catalog payloads deliberately omit Item snapshots. The lifecycle tests
# below exercise completed text, reasoning, tool calls, and structured results.
AG_UI_EXTENSION = (("CUSTOM",), ("ag_ui.sage_extension",))
EXPECTED_FAMILY_PROJECTIONS = {
    "ag-ui": {
        **dict.fromkeys((
            "run", "item", "usage", "interaction", "flow", "sandbox", "policy",
            "steering", "job", "protocol", "session_commit", "checkpoint",
        ), AG_UI_EXTENSION),
        **dict.fromkeys(("continuation", "skill_state", "step", "turn"),
                        ((), ("ag_ui.unsupported",))),
        "artifact": (("ACTIVITY_SNAPSHOT",), ()),
        "tool": (("CUSTOM",), ("ag_ui.tool_state_extension",)),
    },
    "acp": {
        **dict.fromkeys((
            "run", "usage", "interaction", "flow", "sandbox", "policy", "steering",
            "job", "protocol", "session_commit", "checkpoint", "continuation",
            "skill_state", "step", "turn",
        ), ((), ("acp.unsupported",))),
        "item": ((), ("acp.item_incomplete",)),
        "artifact": (("session/update",), ()),
        "tool": (("session/update",), ()),
    },
    "mcp": {
        **dict.fromkeys((
            "run", "item", "usage", "interaction", "flow", "sandbox", "policy",
            "steering", "protocol", "session_commit", "checkpoint", "continuation",
            "skill_state", "step", "turn", "artifact",
        ), ((), ("mcp.not_run_protocol",))),
        "tool": (("notifications/progress",), ("mcp.progress_only",)),
        "job": (("notifications/progress",), ("mcp.progress_only",)),
    },
    "a2a": {
        **dict.fromkeys((
            "run", "item", "usage", "interaction", "flow", "sandbox", "policy",
            "steering", "job", "protocol", "session_commit", "checkpoint",
            "continuation", "skill_state", "step", "turn", "tool",
        ), ((), ("a2a.unsupported",))),
        "artifact": (("task/artifact-update",), ()),
    },
}
EXPECTED_EVENT_PROJECTIONS = {
    "ag-ui": {
        "run.started": (("RUN_STARTED",), ()),
        "run.completed": (("RUN_FINISHED",), ()),
        "run.failed": (("RUN_ERROR",), ()),
        "message.started": (("TEXT_MESSAGE_START",), ()),
        "message.delta": (("TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT"), ()),
        "reasoning.started": (("REASONING_START", "REASONING_MESSAGE_START"), ()),
        "reasoning.delta": (("REASONING_START", "REASONING_MESSAGE_START",
                             "REASONING_MESSAGE_CONTENT"), ()),
    },
    "acp": {
        **dict.fromkeys(("run.started", "run.completed", "run.failed", "run.cancelled"),
                        (("session/update",), ())),
        "interaction.requested": (("session/request_permission",), ()),
    },
    "mcp": {"interaction.requested": (("elicitation/create",), ())},
    "a2a": {
        **dict.fromkeys((
            "run.queued", "run.accepted", "run.started", "run.resumed",
            "run.completed", "run.failed", "run.cancelled", "run.suspended",
            "interaction.requested", "message.delta",
        ), (("task/status-update",), ())),
        "artifact.deleted": ((), ("a2a.artifact_delete",)),
    },
}
EXPECTED_LOSS_FIDELITY = {
    "ag_ui.sage_extension": ("extension", True),
    "ag_ui.tool_state_extension": ("extension", True),
    "ag_ui.unsupported": ("unsupported", False),
    "acp.unsupported": ("unsupported", False),
    "acp.item_incomplete": ("unsupported", False),
    "mcp.not_run_protocol": ("unsupported", False),
    "mcp.progress_only": ("lossy", False),
    "a2a.unsupported": ("unsupported", False),
    "a2a.artifact_delete": ("unsupported", False),
}


@pytest.mark.parametrize(
    "adapter_factory",
    [AgUiProtocolAdapter, AcpProtocolAdapter, McpProtocolAdapter, A2AProtocolAdapter],
)
@pytest.mark.parametrize("event_type", sorted(EVENT_CATALOG))
def test_every_catalog_event_keeps_its_expected_mapping_and_loss_fidelity(
    adapter_factory, event_type
):
    adapter = adapter_factory()
    result = adapter.translate(event(event_type))
    expected_frames, expected_losses = EXPECTED_EVENT_PROJECTIONS[adapter.protocol].get(
        event_type,
        EXPECTED_FAMILY_PROJECTIONS[adapter.protocol][EVENT_CATALOG[event_type].data_kind],
    )
    assert tuple(frame.name for frame in result.frames) == expected_frames
    assert tuple(loss.code for loss in result.losses) == expected_losses
    assert tuple((loss.fidelity.value, loss.preserved_by_extension) for loss in result.losses) == tuple(
        EXPECTED_LOSS_FIDELITY[code] for code in expected_losses
    )
    assert all(frame.source_event_id == "event_1" for frame in result.frames)
    assert all(loss.source_event_id == "event_1" for loss in result.losses)
    assert all(frame.source_run_sequence == 1 for frame in result.frames)
    assert all(loss.source_event_type == event_type for loss in result.losses)


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


@pytest.mark.parametrize(
    "content, expected",
    [
        ((TextBlock(text='{"status":"success"}'),), '{"status":"success"}'),
        ((JsonBlock(value={"status": "success", "message": "写入成功"}),),
         '{"status": "success", "message": "写入成功"}'),
        ((JsonBlock(value=[1, "中文"]),), '[1, "中文"]'),
        ((JsonBlock(value={}),), '{}'),
        ((JsonBlock(value=[]),), '[]'),
        ((JsonBlock(value=False),), 'false'),
        ((JsonBlock(value=0),), '0'),
        ((JsonBlock(value=None),), 'null'),
        ((TextBlock(text="before"), JsonBlock(value={"ok": True}),
          TextBlock(text="after")), 'before\n{"ok": true}\nafter'),
        ((), ''),
    ],
)
def test_ag_ui_tool_results_preserve_text_and_structured_values(content, expected):
    result = AgUiProtocolAdapter().translate(
        event(
            "item.completed",
            item_id="item_result",
            data=ItemEventData(
                operation="completed",
                item=item_snapshot(
                    "item_result",
                    ToolResultItemData(tool_call_id="call_1", content=content),
                ),
            ),
        )
    )
    assert len(result.frames) == 1
    frame = result.frames[0]
    assert frame.name == "TOOL_CALL_RESULT"
    assert frame.payload == {
        "messageId": "item_result",
        "toolCallId": "call_1",
        "content": expected,
        "role": "tool",
    }


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

    a2a = A2AProtocolAdapter().translate(source).frames[0].payload
    mcp = McpProtocolAdapter().translate(source).frames[0].payload

    assert a2a["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    assert a2a["metadata"]["sage.allowedDecisions"] == ["submit", "cancel"]
    assert a2a["metadata"]["sage.payload"]["questions"][0]["id"] == "target"
    assert mcp["requestedSchema"]["properties"]["target"] == {
        "type": "array",
        "title": "Targets",
        "items": {"type": "string", "enum": ["staging", "production"]},
    }
    assert mcp["sageInteraction"]["payload"] == source.data.payload


@pytest.mark.parametrize("adapter", [AcpProtocolAdapter()])
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


def test_a2a_terminal_error_survives_as_status_message_and_metadata():
    """A2A 1.0 has no error code on TaskStatus, so the code rides metadata."""

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
    payload = A2AProtocolAdapter().translate(source).frames[0].payload
    assert payload["status"]["state"] == "TASK_STATE_FAILED"
    assert payload["status"]["message"]["parts"][0]["text"] == (
        "模型服务暂时不可用，请稍后重试。"
    )
    assert payload["metadata"]["sage.errorCode"] == "model.provider_error"


def test_mcp_explicitly_refuses_to_masquerade_as_run_protocol():
    result = McpProtocolAdapter().translate(event("run.started"))
    assert result.frames == ()
    assert result.losses[0].code == "mcp.not_run_protocol"


@pytest.mark.parametrize(
    ("event_type", "state"),
    [
        ("run.queued", "TASK_STATE_SUBMITTED"),
        ("run.started", "TASK_STATE_WORKING"),
        ("run.suspended", "TASK_STATE_INPUT_REQUIRED"),
        ("run.completed", "TASK_STATE_COMPLETED"),
        ("run.failed", "TASK_STATE_FAILED"),
        ("run.cancelled", "TASK_STATE_CANCELED"),
    ],
)
def test_a2a_task_status_mapping_matrix(event_type, state):
    result = A2AProtocolAdapter().translate(event(event_type))
    assert result.frames[0].payload["status"]["state"] == state


@pytest.mark.parametrize("reasoning", [False, True])
@pytest.mark.parametrize("with_preview", [False, True])
def test_agui_durable_start_restores_content_when_previews_are_unavailable(
    reasoning,
    with_preview,
):
    family = "reasoning" if reasoning else "message"
    adapter = AgUiProtocolAdapter()
    started = event(f"{family}.started", item_id="item_1")
    frames = list(adapter.translate(started).frames)
    duplicate = adapter.translate(started)
    assert all("START" not in frame.name for frame in duplicate.frames)
    if with_preview:
        frames.extend(
            adapter.translate(
                event(
                    f"{family}.delta",
                    item_id="item_1",
                    sequence=2,
                    data=ItemEventData(operation="delta", delta="answer"),
                )
            ).frames
        )
    data = (
        ReasoningItemData(content=(TextBlock(text="answer"),))
        if reasoning
        else MessageItemData(role="assistant", content=(TextBlock(text="answer"),))
    )
    frames.extend(
        adapter.translate(
            event(
                f"{family}.completed",
                item_id="item_1",
                sequence=3,
                data=ItemEventData(
                    operation="completed", item=item_snapshot("item_1", data)
                ),
            )
        ).frames
    )
    expected = (
        [
            "REASONING_START",
            "REASONING_MESSAGE_START",
            "REASONING_MESSAGE_CONTENT",
            "REASONING_MESSAGE_END",
            "REASONING_END",
        ]
        if reasoning
        else ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END"]
    )
    assert [frame.name for frame in frames] == expected
    assert [frame.payload["delta"] for frame in frames if "delta" in frame.payload] == [
        "answer"
    ]
