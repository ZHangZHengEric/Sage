"""In-process sandbox approval broker.

The broker is intentionally process-local. App surfaces submit decisions through
their existing runtime channel; sagents does not start a service or poll state.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from sagents.utils.logger import logger


ApprovalDecision = Literal["approve", "deny"]
ApprovalStatus = Literal[
    "resolved",
    "not_found",
    "expired",
    "session_mismatch",
    "command_mismatch",
    "already_resolved",
    "invalid_decision",
]


@dataclass
class PendingSandboxApproval:
    session_id: str
    approval_id: str
    command: str
    command_hash: str
    category: str
    reason: str
    approval_mode: str
    hint: Optional[str]
    created_at: float
    expires_at_epoch: float
    future: asyncio.Future[ApprovalDecision]

    @property
    def expires_at(self) -> str:
        return (
            datetime.fromtimestamp(self.expires_at_epoch, timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def event_payload(self) -> Dict[str, Any]:
        return {
            "type": "sandbox_approval_requested",
            "role": "system",
            "content": self.reason
            or "Sandbox policy requires confirmation before running this command.",
            "session_id": self.session_id,
            "approval_id": self.approval_id,
            "command": self.command,
            "command_hash": self.command_hash,
            "category": self.category,
            "reason": self.reason,
            "approval_mode": self.approval_mode,
            "expires_at": self.expires_at,
            "hint": self.hint,
            "tool_name": "execute_shell_command",
        }


class SandboxApprovalBroker:
    def __init__(self) -> None:
        self._pending: Dict[str, PendingSandboxApproval] = {}

    def create(
        self,
        *,
        session_id: str,
        command: str,
        category: str,
        reason: str,
        approval_mode: str,
        hint: Optional[str] = None,
        ttl_s: int = 30 * 60,
    ) -> PendingSandboxApproval:
        self.gc_stale()
        now = time.time()
        approval_id = "shapproval_" + uuid.uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        pending = PendingSandboxApproval(
            session_id=session_id,
            approval_id=approval_id,
            command=command.strip(),
            command_hash=command_hash(command),
            category=category,
            reason=reason,
            approval_mode=approval_mode,
            hint=hint,
            created_at=now,
            expires_at_epoch=now + ttl_s,
            future=loop.create_future(),
        )
        self._pending[approval_id] = pending
        return pending

    def resolve(
        self,
        *,
        session_id: str,
        approval_id: str,
        decision: str,
        command_hash_value: Optional[str] = None,
    ) -> ApprovalStatus:
        self.gc_stale()
        normalized_decision = decision.strip().lower()
        if normalized_decision not in {"approve", "deny"}:
            return "invalid_decision"

        pending = self._pending.get(approval_id)
        if pending is None:
            return "not_found"
        if pending.future.done():
            self._pending.pop(approval_id, None)
            return "already_resolved"
        if pending.session_id != session_id:
            return "session_mismatch"
        if command_hash_value and command_hash_value != pending.command_hash:
            return "command_mismatch"
        if time.time() > pending.expires_at_epoch:
            self._pending.pop(approval_id, None)
            pending.future.set_result("deny")
            return "expired"

        self._pending.pop(approval_id, None)
        pending.future.set_result(normalized_decision)  # pyright: ignore[reportArgumentType]
        return "resolved"

    def discard(self, approval_id: str) -> None:
        pending = self._pending.pop(approval_id, None)
        if pending is not None and not pending.future.done():
            pending.future.set_result("deny")

    def gc_stale(self) -> None:
        now = time.time()
        for approval_id, pending in list(self._pending.items()):
            if now <= pending.expires_at_epoch:
                continue
            self._pending.pop(approval_id, None)
            if not pending.future.done():
                pending.future.set_result("deny")


_BROKER = SandboxApprovalBroker()


def command_hash(command: str) -> str:
    normalized = command.strip().encode("utf-8", errors="replace")
    return hashlib.sha256(normalized).hexdigest()


def get_sandbox_approval_broker() -> SandboxApprovalBroker:
    return _BROKER


def resolve_sandbox_approval(
    *,
    session_id: str,
    approval_id: str,
    decision: str,
    command_hash_value: Optional[str] = None,
) -> ApprovalStatus:
    status = _BROKER.resolve(
        session_id=session_id,
        approval_id=approval_id,
        decision=decision,
        command_hash_value=command_hash_value,
    )
    logger.debug(
        "sandbox approval resolve: "
        f"session_id={session_id} approval_id={approval_id} status={status}"
    )
    return status


__all__ = [
    "ApprovalDecision",
    "ApprovalStatus",
    "PendingSandboxApproval",
    "SandboxApprovalBroker",
    "command_hash",
    "get_sandbox_approval_broker",
    "resolve_sandbox_approval",
]
