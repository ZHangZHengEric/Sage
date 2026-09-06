"""审批记忆：把 ``approve_and_remember`` 落到会话级派生状态。

记忆只记录精确匹配器（见 :class:`ApprovalMatcher`），只能把"需要审批"收敛为
"已批准"，不能把 deny 记成 allow；作用域 ``session`` 由 Kernel 提供，
``workspace`` 等更宽的作用域由宿主自己的 :class:`ApprovalMemory` 实现叠加。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from sagents.v2.agent.policy.tool_policy import ApprovalMatcher
from sagents.v2.contracts.common import StrictModel
from sagents.v2.runtime.session.contracts import DerivedStateStore

ApprovalScope = Literal["session", "workspace"]

REMEMBER_DECISION = "approve_and_remember"


class RememberedApproval(StrictModel):
    matcher: ApprovalMatcher
    scope: ApprovalScope
    remembered_at: datetime
    remembered_by: str


class ApprovalMemory(Protocol):
    """Loop 持有的审批记忆端口；实现必须至少支持 ``session`` 作用域。"""

    supported_scopes: frozenset[str]

    async def lookup(
        self, *, session_id: str, matcher: ApprovalMatcher
    ) -> RememberedApproval | None: ...

    async def remember(
        self, *, session_id: str, approval: RememberedApproval
    ) -> None: ...

    async def forget(
        self, *, session_id: str, matcher: ApprovalMatcher | None = None
    ) -> int:
        """撤销一条（或全部）记忆，返回删除条数。"""

        ...

    async def list_remembered(
        self, *, session_id: str
    ) -> tuple[RememberedApproval, ...]: ...


class SessionApprovalMemory:
    """基于 :class:`DerivedStateStore` 的会话作用域记忆。

    派生状态非权威、可重建：丢失只会让用户多确认一次，不会放宽任何权限。
    会话删除时随 ``forget_session`` 一起清理。
    """

    NAMESPACE = "approval-memory"
    KEY = "remembered"
    VERSION = 1
    supported_scopes: frozenset[str] = frozenset({"session"})

    def __init__(self, derived_state: DerivedStateStore) -> None:
        self._derived_state = derived_state
        self._lock = asyncio.Lock()

    async def lookup(
        self, *, session_id: str, matcher: ApprovalMatcher
    ) -> RememberedApproval | None:
        entries = await self._entries(session_id)
        raw = entries.get(matcher.key)
        if raw is None:
            return None
        remembered = RememberedApproval.model_validate(raw)
        # 指纹相同但工具名不同（几乎不可能）也不放行：匹配器必须完全一致。
        return remembered if remembered.matcher == matcher else None

    async def remember(self, *, session_id: str, approval: RememberedApproval) -> None:
        if approval.scope not in self.supported_scopes:
            raise ValueError(
                f"approval scope {approval.scope!r} is not supported by "
                "SessionApprovalMemory"
            )
        async with self._lock:
            entries = await self._entries(session_id)
            entries[approval.matcher.key] = approval.model_dump(mode="json")
            await self._store(session_id, entries)

    async def forget(
        self, *, session_id: str, matcher: ApprovalMatcher | None = None
    ) -> int:
        async with self._lock:
            entries = await self._entries(session_id)
            if matcher is None:
                removed = len(entries)
                await self._derived_state.delete_derived_state(
                    session_id, self.NAMESPACE, self.KEY
                )
                return removed
            if entries.pop(matcher.key, None) is None:
                return 0
            await self._store(session_id, entries)
            return 1

    async def list_remembered(
        self, *, session_id: str
    ) -> tuple[RememberedApproval, ...]:
        entries = await self._entries(session_id)
        return tuple(
            RememberedApproval.model_validate(raw)
            for _key, raw in sorted(entries.items())
        )

    def composition_identity(self) -> dict[str, Any]:
        return {
            "provider": "session-approval-memory",
            "scopes": sorted(self.supported_scopes),
            "version": self.VERSION,
        }

    async def _entries(self, session_id: str) -> dict[str, Any]:
        raw = await self._derived_state.get_derived_state(
            session_id, self.NAMESPACE, self.KEY
        )
        if not isinstance(raw, dict) or raw.get("version") != self.VERSION:
            # 版本不认识就当作没有记忆：只会多问一次，不会放宽。
            return {}
        entries = raw.get("entries")
        if not isinstance(entries, dict):
            return {}
        valid = {}
        for key, value in entries.items():
            try:
                approval = RememberedApproval.model_validate(value)
            except ValidationError:
                continue
            if (
                approval.scope not in self.supported_scopes
                or key != approval.matcher.key
            ):
                continue
            valid[key] = approval.model_dump(mode="json")
        return valid

    async def _store(self, session_id: str, entries: dict[str, Any]) -> None:
        await self._derived_state.put_derived_state(
            session_id,
            self.NAMESPACE,
            self.KEY,
            {"version": self.VERSION, "entries": entries},
        )


__all__ = [
    "REMEMBER_DECISION",
    "ApprovalMemory",
    "ApprovalScope",
    "RememberedApproval",
    "SessionApprovalMemory",
]
