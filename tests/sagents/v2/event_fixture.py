"""Minimal catalog payloads shared by wire-contract and projection tests."""

from sagents.v2.contracts.events import (
    ArtifactEventData,
    CheckpointEventData,
    ContinuationEventData,
    FlowEventData,
    InteractionEventData,
    ItemEventData,
    JobEventData,
    PolicyEventData,
    ProtocolEventData,
    RunEventData,
    SandboxEventData,
    SessionCommitEventData,
    SkillStateEventData,
    SteeringEventData,
    StepEventData,
    ToolEventData,
    TurnEventData,
    UsageEventData,
)
from sagents.v2.contracts.items import ArtifactRef, UsageSummary


def event_data(kind: str):
    if kind == "skill_state":
        return SkillStateEventData(state={})
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
