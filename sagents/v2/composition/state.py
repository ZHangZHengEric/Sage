"""SDK-internal assembly state derived exclusively from registered capabilities."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sagents.v2.contracts.runtime_skills import RuntimeSkillAuthority

if TYPE_CHECKING:
    from sagents.v2.composition.revision_store import RecoveryIdentity


@dataclass
class AssemblyState:
    runtime_skill_authority: RuntimeSkillAuthority = field(default_factory=RuntimeSkillAuthority)
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
