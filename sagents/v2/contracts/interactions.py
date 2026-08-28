"""SAgents V2 module for contracts/interactions.py."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.principals import ActorRef


class InteractionType(str, Enum):
    APPROVAL = "approval"
    PERMISSION = "permission"
    USER_INPUT = "user_input"
    CREDENTIAL = "credential"
    ELICITATION = "elicitation"


class InteractionStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class BlockingScope(str, Enum):
    NODE = "node"
    BRANCH = "branch"
    RUN = "run"


class InteractionRequest(StrictModel):
    """Persisted question that blocks some runtime scope until it is answered.

    Approval, permission, credentials, and user input share this lifecycle but
    remain distinguishable through `interaction_type`.
    """

    interaction_id: Identifier
    run_id: Identifier
    turn_id: Identifier | None = None
    step_id: Identifier | None = None
    item_id: Identifier | None = None
    interaction_type: InteractionType
    status: InteractionStatus = InteractionStatus.PENDING
    blocking_scope: BlockingScope = BlockingScope.RUN
    allowed_decisions: tuple[str, ...]
    eligible_principal_ids: tuple[Identifier, ...] = ()
    payload: dict[str, Any]
    expected_revision: int = Field(default=0, ge=0)
    requested_at: datetime
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_decisions(self) -> "InteractionRequest":
        if not self.allowed_decisions:
            raise ValueError("allowed_decisions must not be empty")
        if len(set(self.allowed_decisions)) != len(self.allowed_decisions):
            raise ValueError("allowed_decisions must be unique")
        return self


class InteractionResolution(StrictModel):
    """Single durable answer to an InteractionRequest."""

    interaction_id: Identifier
    decision: str
    resolver: ActorRef
    expected_revision: int = Field(ge=0)
    idempotency_key: Identifier
    payload: dict[str, Any] = Field(default_factory=dict)
    resolved_at: datetime
