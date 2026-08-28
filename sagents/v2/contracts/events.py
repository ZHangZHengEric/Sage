"""SAgents V2 module for contracts/events.py."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import Field, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel, ToolName
from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.contracts.items import ArtifactRef, ItemSnapshot, UsageSummary
from sagents.v2.contracts.principals import ActorRef


# RuntimeEvents describe facts after they have happened. Commands request a
# change and InteractionRequests ask for an answer; neither should be encoded as
# a pretend event before the SessionStore accepts the corresponding write.
class EventDurability(str, Enum):
    DURABLE = "durable"
    REPLAY_BUFFERED = "replay_buffered"
    TRANSIENT = "transient"


class EventSourceType(str, Enum):
    RUNTIME = "runtime"
    AGENT = "agent"
    MODEL = "model"
    TOOL = "tool"
    JOB = "job"
    SANDBOX = "sandbox"
    POLICY = "policy"
    PROTOCOL = "protocol"
    USER = "user"


class EventSource(StrictModel):
    source_type: EventSourceType
    source_id: Identifier | None = None
    provider_id: Identifier | None = None
    provider_version: str | None = None


class RunEventData(StrictModel):
    kind: Literal["run"] = "run"
    state: str
    reason: str | None = None
    error: RuntimeErrorInfo | None = None
    retry_of_run_id: Identifier | None = None


class TurnEventData(StrictModel):
    kind: Literal["turn"] = "turn"
    state: str
    stop_reason: str | None = None
    error: RuntimeErrorInfo | None = None


class StepEventData(StrictModel):
    kind: Literal["step"] = "step"
    state: str
    attempt: int = Field(default=1, ge=1)
    retry_at: datetime | None = None
    error: RuntimeErrorInfo | None = None


class ItemEventData(StrictModel):
    kind: Literal["item"] = "item"
    operation: Literal["started", "delta", "completed", "failed", "snapshot"]
    item: ItemSnapshot | None = None
    delta: str | dict[str, Any] | tuple[dict[str, Any], ...] | None = None
    content_hash: str | None = None
    error: RuntimeErrorInfo | None = None

    @model_validator(mode="after")
    def validate_operation_payload(self) -> "ItemEventData":
        if self.operation in {"completed", "snapshot"} and self.item is None:
            raise ValueError(f"{self.operation} item event requires item")
        if self.operation == "delta" and self.delta is None:
            raise ValueError("delta item event requires delta")
        return self


class ToolEventData(StrictModel):
    kind: Literal["tool"] = "tool"
    tool_call_id: Identifier
    tool_name: ToolName
    state: str
    operation_id: Identifier | None = None
    idempotency_key: Identifier | None = None
    arguments: dict[str, Any] | None = None
    result_item_id: Identifier | None = None
    error: RuntimeErrorInfo | None = None


class JobEventData(StrictModel):
    kind: Literal["job"] = "job"
    job_id: Identifier
    state: str
    progress: float | None = Field(default=None, ge=0, le=1)
    output_cursor: int | None = Field(default=None, ge=0)
    error: RuntimeErrorInfo | None = None


class InteractionEventData(StrictModel):
    kind: Literal["interaction"] = "interaction"
    interaction_id: Identifier
    interaction_type: Identifier
    state: str
    decision: str | None = None
    revision: int = Field(default=0, ge=0)


class CheckpointEventData(StrictModel):
    kind: Literal["checkpoint"] = "checkpoint"
    checkpoint_id: Identifier
    checkpoint_codec_version: str
    state: Literal["committed"] = "committed"
    run_sequence: int = Field(ge=0)
    session_revision: int = Field(ge=0)


class SteeringEventData(StrictModel):
    kind: Literal["steering"] = "steering"
    steer_id: Identifier
    state: str
    expected_turn_id: Identifier | None = None
    inbox_sequence: int | None = Field(default=None, ge=0)
    reason: str | None = None


class ContinuationEventData(StrictModel):
    kind: Literal["continuation"] = "continuation"
    action: str
    reason_code: Identifier
    reason: str
    decision_hash: str
    next_agent: Identifier | None = None


class FlowEventData(StrictModel):
    kind: Literal["flow"] = "flow"
    state: str
    flow_id: Identifier | None = None
    node_id: Identifier | None = None
    edge_id: Identifier | None = None
    decided_by: Literal["flow", "model", "policy", "user"] | None = None
    error: RuntimeErrorInfo | None = None


class ArtifactEventData(StrictModel):
    kind: Literal["artifact"] = "artifact"
    state: str
    artifact: ArtifactRef


class SandboxEventData(StrictModel):
    kind: Literal["sandbox"] = "sandbox"
    sandbox_id: Identifier
    state: str
    policy_decision_ref: Identifier | None = None
    violation_code: str | None = None
    error: RuntimeErrorInfo | None = None


class PolicyEventData(StrictModel):
    kind: Literal["policy"] = "policy"
    decision_id: Identifier
    decision: str
    policy_version: str
    reason: str | None = None


class UsageEventData(StrictModel):
    kind: Literal["usage"] = "usage"
    usage: UsageSummary


class ProtocolEventData(StrictModel):
    kind: Literal["protocol"] = "protocol"
    state: str
    from_sequence: int | None = Field(default=None, ge=0)
    to_sequence: int | None = Field(default=None, ge=0)
    snapshot_ref: Identifier | None = None
    capabilities: dict[str, Any] | None = None


class SessionCommitEventData(StrictModel):
    """Audit fact for snapshot proposal, publication, or rejection."""

    kind: Literal["session_commit"] = "session_commit"
    proposal_id: Identifier
    source_run_id: Identifier
    state: Literal["proposed", "published", "rejected"]
    base_session_revision: int = Field(ge=0)
    base_session_sequence: int = Field(ge=0)
    merge_strategy: str | None = None
    conflicting_run_ids: tuple[Identifier, ...] = ()
    reason: str | None = None


EventData = Annotated[
    Union[
        RunEventData,
        TurnEventData,
        StepEventData,
        ItemEventData,
        ToolEventData,
        JobEventData,
        InteractionEventData,
        CheckpointEventData,
        SteeringEventData,
        ContinuationEventData,
        FlowEventData,
        ArtifactEventData,
        SandboxEventData,
        PolicyEventData,
        UsageEventData,
        ProtocolEventData,
        SessionCommitEventData,
    ],
    Field(discriminator="kind"),
]


@dataclass(frozen=True)
class EventDefinition:
    """Catalog metadata governing storage and adapter treatment of an event."""

    data_kind: str
    durability: EventDurability
    terminal: bool = False
    sensitive: bool = False


def _definitions(
    names: tuple[str, ...],
    kind: str,
    durability: EventDurability = EventDurability.DURABLE,
    *,
    terminal: tuple[str, ...] = (),
    sensitive: bool = False,
) -> dict[str, EventDefinition]:
    terminal_names = set(terminal)
    return {
        name: EventDefinition(
            data_kind=kind,
            durability=durability,
            terminal=name in terminal_names,
            sensitive=sensitive,
        )
        for name in names
    }


EVENT_CATALOG: dict[str, EventDefinition] = {}
# Lifecycle and completed Item events are durable facts. High-frequency deltas
# and progress events are replay-buffered because the completed Item or Job is
# the authoritative projection.
EVENT_CATALOG.update(
    _definitions(
        (
            "run.accepted",
            "run.queued",
            "run.started",
            "run.pause_requested",
            "run.suspended",
            "run.resume_requested",
            "run.resumed",
            "run.completed",
            "run.failed",
            "run.cancelled",
        ),
        "run",
        terminal=("run.completed", "run.failed", "run.cancelled"),
    )
)
EVENT_CATALOG.update(_definitions(("checkpoint.committed",), "checkpoint"))
EVENT_CATALOG.update(
    _definitions(
        ("turn.started", "turn.completed", "turn.failed"),
        "turn",
        terminal=("turn.completed", "turn.failed"),
    )
)
EVENT_CATALOG.update(
    _definitions(
        ("step.started", "step.completed", "step.failed", "step.retry_scheduled"),
        "step",
        terminal=("step.completed", "step.failed"),
    )
)
EVENT_CATALOG.update(
    _definitions(
        (
            "item.started",
            "item.completed",
            "item.failed",
            "message.started",
            "message.completed",
            "reasoning.started",
            "reasoning.completed",
        ),
        "item",
        terminal=(
            "item.completed",
            "item.failed",
            "message.completed",
            "reasoning.completed",
        ),
    )
)
EVENT_CATALOG.update(
    _definitions(
        ("item.delta", "message.delta", "reasoning.delta"),
        "item",
        EventDurability.REPLAY_BUFFERED,
    )
)
EVENT_CATALOG.update(
    _definitions(
        (
            "tool.call.proposed",
            "tool.call.awaiting_approval",
            "tool.call.dispatching",
            "tool.call.started",
            "tool.call.succeeded",
            "tool.call.failed",
            "tool.call.unknown",
            "tool.call.cancelled",
            "tool.call.reconciling",
            "tool.call.reconciled",
        ),
        "tool",
        terminal=(
            "tool.call.succeeded",
            "tool.call.failed",
            "tool.call.cancelled",
            "tool.call.reconciled",
        ),
        sensitive=True,
    )
)
EVENT_CATALOG.update(
    _definitions(
        (
            "job.created",
            "job.started",
            "job.stopping",
            "job.completed",
            "job.failed",
            "job.killed",
            "job.orphaned",
            "job.adopted",
        ),
        "job",
        terminal=("job.completed", "job.failed", "job.killed"),
    )
)
EVENT_CATALOG.update(
    _definitions(("job.progress",), "job", EventDurability.REPLAY_BUFFERED)
)
EVENT_CATALOG.update(
    _definitions(
        (
            "interaction.requested",
            "interaction.resolved",
            "interaction.expired",
            "interaction.cancelled",
        ),
        "interaction",
        terminal=(
            "interaction.resolved",
            "interaction.expired",
            "interaction.cancelled",
        ),
        sensitive=True,
    )
)
EVENT_CATALOG.update(
    _definitions(
        ("steer.accepted", "steer.applied", "steer.rejected"),
        "steering",
        terminal=("steer.applied", "steer.rejected"),
    )
)
EVENT_CATALOG.update(_definitions(("continuation.decided",), "continuation"))
EVENT_CATALOG.update(
    _definitions(
        (
            "flow.started",
            "flow.node.started",
            "flow.node.suspended",
            "flow.node.resumed",
            "flow.node.completed",
            "flow.node.failed",
            "flow.edge.selected",
            "flow.completed",
        ),
        "flow",
        terminal=("flow.node.completed", "flow.node.failed", "flow.completed"),
    )
)
EVENT_CATALOG.update(
    _definitions(
        (
            "artifact.created",
            "artifact.updated",
            "artifact.finalized",
            "artifact.deleted",
        ),
        "artifact",
        terminal=("artifact.finalized", "artifact.deleted"),
    )
)
EVENT_CATALOG.update(
    _definitions(
        (
            "sandbox.provisioning",
            "sandbox.ready",
            "sandbox.suspended",
            "sandbox.resumed",
            "sandbox.terminated",
            "sandbox.policy_enforced",
            "sandbox.violation",
        ),
        "sandbox",
        terminal=("sandbox.terminated",),
        sensitive=True,
    )
)
EVENT_CATALOG.update(
    _definitions(
        ("policy.decision.recorded", "budget.updated", "budget.exhausted"),
        "policy",
        terminal=("budget.exhausted",),
        sensitive=True,
    )
)
EVENT_CATALOG.update(_definitions(("usage.recorded",), "usage"))
EVENT_CATALOG.update(
    _definitions(
        ("stream.snapshot", "stream.gap", "stream.cursor_expired"),
        "protocol",
        EventDurability.REPLAY_BUFFERED,
    )
)
EVENT_CATALOG.update(
    _definitions(("capabilities.changed",), "protocol", EventDurability.TRANSIENT)
)
EVENT_CATALOG.update(
    _definitions(
        (
            "session.commit.proposed",
            "session.commit.published",
            "session.commit.rejected",
        ),
        "session_commit",
        terminal=("session.commit.published", "session.commit.rejected"),
    )
)


class RuntimeEvent(StrictModel):
    """Canonical, transport-neutral fact emitted by the v2 runtime.

    Sequence numbers are assigned only by SessionStore during commit.
    Providers and downstream adapters preserve these identities and must not
    invent a second ordering.
    """

    protocol_version: Literal["sage.runtime/v2"] = "sage.runtime/v2"
    event_schema_version: str = "1"
    event_id: Identifier
    type: str
    occurred_at: datetime
    durability: EventDurability
    session_id: Identifier
    run_id: Identifier
    session_sequence: int | None = Field(default=None, ge=1)
    run_sequence: int = Field(ge=1)
    turn_id: Identifier | None = None
    step_id: Identifier | None = None
    item_id: Identifier | None = None
    job_id: Identifier | None = None
    interaction_id: Identifier | None = None
    flow_execution_id: Identifier | None = None
    node_execution_id: Identifier | None = None
    correlation_id: Identifier | None = None
    causation_id: Identifier | None = None
    actor: ActorRef
    source: EventSource
    data: EventData
    ignorable: bool = False

    @model_validator(mode="after")
    def validate_catalog_contract(self) -> "RuntimeEvent":
        definition = EVENT_CATALOG.get(self.type)
        if definition is None:
            if not self.type.startswith("extension.") or not self.ignorable:
                raise ValueError(
                    "unknown events must use the extension. namespace and ignorable=true"
                )
        else:
            if self.data.kind != definition.data_kind:
                raise ValueError(
                    f"event {self.type!r} requires data.kind={definition.data_kind!r}"
                )
            if self.durability != definition.durability:
                raise ValueError(
                    f"event {self.type!r} requires durability={definition.durability.value!r}"
                )
        if self.durability == EventDurability.DURABLE:
            if self.session_sequence is None:
                raise ValueError("durable events require session_sequence")
        elif self.session_sequence is not None:
            raise ValueError("non-durable events must not have session_sequence")
        if self.job_id is not None and isinstance(self.data, JobEventData):
            if self.job_id != self.data.job_id:
                raise ValueError("job_id must match data.job_id")
        if self.interaction_id is not None and isinstance(
            self.data, InteractionEventData
        ):
            if self.interaction_id != self.data.interaction_id:
                raise ValueError("interaction_id must match data.interaction_id")
        return self
