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
AuditStatus = Literal["pending", "resolved", "expired", "discarded"]


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


@dataclass
class SandboxApprovalAuditRecord:
    session_id: str
    approval_id: str
    command: str
    command_hash: str
    category: str
    reason: str
    approval_mode: str
    created_at: float
    expires_at_epoch: float
    status: AuditStatus = "pending"
    decision: Optional[ApprovalDecision] = None
    resolved_at: Optional[float] = None

    @property
    def created_at_iso(self) -> str:
        return _format_epoch(self.created_at)

    @property
    def expires_at_iso(self) -> str:
        return _format_epoch(self.expires_at_epoch)

    @property
    def resolved_at_iso(self) -> Optional[str]:
        if self.resolved_at is None:
            return None
        return _format_epoch(self.resolved_at)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "approval_id": self.approval_id,
            "command": self.command,
            "command_hash": self.command_hash,
            "category": self.category,
            "reason": self.reason,
            "approval_mode": self.approval_mode,
            "status": self.status,
            "decision": self.decision,
            "created_at": self.created_at_iso,
            "expires_at": self.expires_at_iso,
            "resolved_at": self.resolved_at_iso,
        }


class SandboxApprovalBroker:
    def __init__(self, max_audit_records: int = 200) -> None:
        self._pending: Dict[str, PendingSandboxApproval] = {}
        self._audit: list[SandboxApprovalAuditRecord] = []
        self._max_audit_records = max(1, max_audit_records)

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
        self._append_audit(pending)
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
            self._finish_audit(
                approval_id,
                status="expired",
                decision="deny",
            )
            return "expired"

        self._pending.pop(approval_id, None)
        pending.future.set_result(normalized_decision)  # pyright: ignore[reportArgumentType]
        self._finish_audit(
            approval_id,
            status="resolved",
            decision=normalized_decision,  # pyright: ignore[reportArgumentType]
        )
        return "resolved"

    def discard(self, approval_id: str) -> None:
        pending = self._pending.pop(approval_id, None)
        if pending is not None and not pending.future.done():
            pending.future.set_result("deny")
        if pending is not None:
            self._finish_audit(
                approval_id,
                status="discarded",
                decision="deny",
            )

    def gc_stale(self) -> None:
        now = time.time()
        for approval_id, pending in list(self._pending.items()):
            if now <= pending.expires_at_epoch:
                continue
            self._pending.pop(approval_id, None)
            if not pending.future.done():
                pending.future.set_result("deny")
            self._finish_audit(
                approval_id,
                status="expired",
                decision="deny",
                resolved_at=now,
            )

    def list_audit(
        self, *, session_id: Optional[str] = None, limit: int = 50
    ) -> list[Dict[str, Any]]:
        self.gc_stale()
        normalized_limit = max(1, min(limit, self._max_audit_records))
        records = self._audit
        if session_id:
            records = [record for record in records if record.session_id == session_id]
        return [record.as_dict() for record in records[-normalized_limit:]]

    def _append_audit(self, pending: PendingSandboxApproval) -> None:
        self._audit.append(
            SandboxApprovalAuditRecord(
                session_id=pending.session_id,
                approval_id=pending.approval_id,
                command=pending.command,
                command_hash=pending.command_hash,
                category=pending.category,
                reason=pending.reason,
                approval_mode=pending.approval_mode,
                created_at=pending.created_at,
                expires_at_epoch=pending.expires_at_epoch,
            )
        )
        overflow = len(self._audit) - self._max_audit_records
        if overflow > 0:
            del self._audit[:overflow]

    def _finish_audit(
        self,
        approval_id: str,
        *,
        status: AuditStatus,
        decision: ApprovalDecision,
        resolved_at: Optional[float] = None,
    ) -> None:
        for record in reversed(self._audit):
            if record.approval_id != approval_id:
                continue
            record.status = status
            record.decision = decision
            record.resolved_at = resolved_at or time.time()
            return


_BROKER = SandboxApprovalBroker()


def command_hash(command: str) -> str:
    normalized = command.strip().encode("utf-8", errors="replace")
    return hashlib.sha256(normalized).hexdigest()


def _format_epoch(value: float) -> str:
    return (
        datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
    )


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


def list_sandbox_approval_audit(
    *, session_id: Optional[str] = None, limit: int = 50
) -> list[Dict[str, Any]]:
    return _BROKER.list_audit(session_id=session_id, limit=limit)


__all__ = [
    "ApprovalDecision",
    "ApprovalStatus",
    "AuditStatus",
    "PendingSandboxApproval",
    "SandboxApprovalAuditRecord",
    "SandboxApprovalBroker",
    "command_hash",
    "get_sandbox_approval_broker",
    "list_sandbox_approval_audit",
    "resolve_sandbox_approval",
]
