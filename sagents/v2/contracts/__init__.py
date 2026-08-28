"""SAgents V2 module for contracts/__init__.py."""

from sagents.v2.contracts.checkpoint import Checkpoint, Suspension
from sagents.v2.contracts.commands import (
    CancelRun,
    CommandReceipt,
    InputItem,
    PauseRun,
    ReplyInteraction,
    ResumeRun,
    RunConfig,
    StartRun,
    SteerRun,
)
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.events import (
    EVENT_CATALOG,
    EventDurability,
    EventSource,
    RuntimeEvent,
)
from sagents.v2.contracts.interactions import (
    InteractionRequest,
    InteractionResolution,
)
from sagents.v2.contracts.items import (
    ArtifactRef,
    ContentBlock,
    ItemSnapshot,
    TextBlock,
    UsageSummary,
)
from sagents.v2.contracts.jobs import JobHandle, JobSnapshot
from sagents.v2.contracts.principals import ActorRef, RequestContext
from sagents.v2.contracts.run_state import (
    EventCursor,
    RunHandle,
    RunResult,
    RunSnapshot,
    RunState,
    RunStream,
    SessionSnapshot,
    SessionConcurrencyMode,
)
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionCommitProposal,
    SessionCommitProposalStatus,
    SessionMergeStrategy,
)

__all__ = [
    "ActorRef",
    "ArtifactRef",
    "CancelRun",
    "Checkpoint",
    "CommandReceipt",
    "ContentBlock",
    "EVENT_CATALOG",
    "ErrorCategory",
    "EventCursor",
    "EventDurability",
    "EventSource",
    "InputItem",
    "InteractionRequest",
    "InteractionResolution",
    "ItemSnapshot",
    "JobHandle",
    "JobSnapshot",
    "PauseRun",
    "ProposeSessionCommit",
    "PublishSessionCommit",
    "ReplyInteraction",
    "RejectSessionCommit",
    "RequestContext",
    "ResumeRun",
    "RunConfig",
    "RunHandle",
    "RunResult",
    "RunSnapshot",
    "RunState",
    "RunStream",
    "RuntimeErrorInfo",
    "RuntimeEvent",
    "SageV2Error",
    "SessionConcurrencyMode",
    "SessionCommitProposal",
    "SessionCommitProposalStatus",
    "SessionMergeStrategy",
    "SessionSnapshot",
    "StartRun",
    "SteerRun",
    "Suspension",
    "TextBlock",
    "UsageSummary",
]
