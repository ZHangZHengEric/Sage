# ruff: noqa: E402
"""Sage Agents v2 public API.

The v2 package is intentionally independent from the legacy runtime.  Importing
it must not initialize global managers, model clients, MCP connections, or app
services. See `sagents/v2/README.md` for the lifecycle model, embedding example,
built-in inventory, and implementation-status boundaries.

Requires Python 3.12 or newer. The legacy Sage runtime remains 3.10+.
"""

from sagents.v2.compat import require_python

require_python()

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
from sagents.v2.application import (
    InterfaceRunStream,
    MaterializedAgentPorts,
    ResolvedApplicationPlan,
    ResolvedProviderBinding,
    SAgentApplication,
)
from sagents.v2.builder import SAgentBuilder
from sagents.v2.runtime.execution import (
    ExecutionBindingProvider,
    ExecutionBindingRequest,
    RunExecutionBinding,
)

__all__ = [
    "ActorRef",
    "EventCursor",
    "ExecutionBindingProvider",
    "ExecutionBindingRequest",
    "RequestContext",
    "ResolvedApplicationPlan",
    "ResolvedProviderBinding",
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
    "SAgentApplication",
    "SAgentBuilder",
    "SAgentRunStream",
    "InterfaceRunStream",
    "MaterializedAgentPorts",
]
