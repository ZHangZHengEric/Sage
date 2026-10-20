"""审批记忆：把 ``approve_and_remember`` 落到会话级派生状态。

记忆只记录精确匹配器（见 :class:`ApprovalMatcher`），只能把"需要审批"收敛为
"已批准"，不能把 deny 记成 allow；作用域 ``session`` 由 Kernel 提供，
``workspace`` 等更宽的作用域由宿主自己的 :class:`ApprovalMemory` 实现叠加。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol


from sagents.v2.agent.policy.tool_policy import ApprovalMatcher
from sagents.v2.contracts.common import StrictModel

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


__all__ = [
    "REMEMBER_DECISION",
    "ApprovalMemory",
    "ApprovalScope",
    "RememberedApproval",
]
