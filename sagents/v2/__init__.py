"""Sage Agents v2 public API.

The v2 package is intentionally independent from the legacy runtime.  Importing
it must not initialize global managers, model clients, MCP connections, or app
services. See `sagents/v2/README.md` for the lifecycle model, embedding example,
built-in inventory, and implementation-status boundaries.
"""

from sagents.v2.contracts import (
    ActorRef,
    EventCursor,
    RequestContext,
    RunHandle,
    RuntimeEvent,
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionCommitProposal,
    SessionMergeStrategy,
    StartRun,
)
from sagents.v2.sagent import SAgent, SAgentRunStream
from sagents.v2.builder import SAgentBuilder
from sagents.v2.runtime.execution import (
    ExecutionBindingProvider,
    ExecutionBindingRequest,
    RunExecutionBinding,
)
from sagents.v2.host import (
    AgentHost,
    AgentPackageSource,
    AgentRef,
    AgentRuntimeFactory,
)

__all__ = [
    "ActorRef",
    "AgentHost",
    "AgentPackageSource",
    "AgentRef",
    "AgentRuntimeFactory",
    "EventCursor",
    "ExecutionBindingProvider",
    "ExecutionBindingRequest",
    "RequestContext",
    "RunHandle",
    "RunExecutionBinding",
    "RuntimeEvent",
    "ProposeSessionCommit",
    "PublishSessionCommit",
    "RejectSessionCommit",
    "SessionCommitProposal",
    "SessionMergeStrategy",
    "StartRun",
    "SAgent",
    "SAgentBuilder",
    "SAgentRunStream",
]
