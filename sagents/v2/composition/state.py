"""SDK-internal assembly state derived exclusively from registered capabilities."""
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sagents.v2.composition.revision_store import RecoveryIdentity


@dataclass
class AssemblyState:
    session_root: Path | None = None
    execution_binding_provider: Any = None
    tool_policy: Any = None
    agent_management: Any = None
    check_readiness: bool = False
    dispatcher: Any = None
    defer_dispatcher_start: bool = False
    manual_dispatcher_start: bool = False
    revision_identity: bool = True
    recovery_identity: "RecoveryIdentity | None" = None
