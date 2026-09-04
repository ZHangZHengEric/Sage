"""``--approval-mode`` 到审批策略的映射，以及 CLI 的"记住审批"匹配器。

策略即数据：这里只是把命令行选项翻译成 ``DefaultToolPolicy`` 的参数，
判定与记忆的执行都在 ``sagents.v2`` 内部完成。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sagents.v2.agent.policy import (
    ApprovalMatcher,
    ApprovalMemory,
    ApprovalStrategy,
    DefaultToolPolicy,
    RememberedApproval,
    exact_arguments_matcher,
)
from sagents.v2.agent.policy.tool_policy import ToolPolicyAction, ToolPolicyContext

CLI_APPROVAL_MATCHER_ID = "sage.cli.approval-matcher/v2"
# ask：写类工具需审批（可记住）；always：每次工具调用都问（不可记住）；
# approve-all：策略层直接放行；deny-all：策略层拒绝所有原本需要审批的调用。
APPROVAL_STRATEGIES: dict[str, ApprovalStrategy] = {
    "ask": ApprovalStrategy.CONFIGURED,
    "always": ApprovalStrategy.ALWAYS_ASK,
    "approve-all": ApprovalStrategy.AUTO_APPROVE,
    "deny-all": ApprovalStrategy.CONFIGURED,
}
_SHELL_TOOL = "execute_shell_command"
_PATH_TOOLS = frozenset({"file_write", "file_update"})
_SUMMARY_LIMIT = 160


def _matcher(tool_name: str, kind: str, value: str) -> ApprovalMatcher:
    # 指纹自带工具名：file_write 与 file_update 同一路径也不共用记忆。
    digest = hashlib.sha256(
        f"{CLI_APPROVAL_MATCHER_ID}:{tool_name}:{kind}:{value}".encode("utf-8")
    ).hexdigest()
    summary = f"{tool_name}: {value}"
    if len(summary) > _SUMMARY_LIMIT:
        summary = summary[: _SUMMARY_LIMIT - 1] + "…"
    return ApprovalMatcher(
        tool_name=tool_name, fingerprint=f"{kind}:sha256:{digest}", summary=summary
    )


def cli_approval_matcher(context: ToolPolicyContext) -> ApprovalMatcher | None:
    """Shell 按完整参数精确匹配（保留换行、引号、工作目录和环境），文件写入按原始路径。

    返回 None 表示本次调用不提供"记住"（只能 approve_once）。
    """

    name = context.definition.name
    arguments = context.call.arguments
    if name == _SHELL_TOOL:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return None
        # 不解析/重写 shell 文本：空白可改变注释、引号、heredoc 等的语义。
        # exact-arguments 的指纹格式也不会命中旧的 command:sha256 记忆。
        return exact_arguments_matcher(context)
    if name in _PATH_TOOLS:
        path = str(arguments.get("file_path") or "")
        return _matcher(name, "path", path) if path else None
    return exact_arguments_matcher(context)


class _DenyApprovalPolicy(DefaultToolPolicy):
    async def decide(self, context: ToolPolicyContext):
        decision = await super().decide(context)
        if decision.action != ToolPolicyAction.REQUIRE_INTERACTION:
            return decision
        return decision.model_copy(
            update={
                "action": ToolPolicyAction.DENY,
                "reason": "tool approval is disabled by --approval-mode deny-all",
                "allowed_decisions": (),
                "interaction_payload": {},
                "persistent_approval_allowed": False,
                "approval_matcher": None,
            }
        )


def build_tool_policy(approval_mode: str | None) -> DefaultToolPolicy:
    """把 ``--approval-mode`` 翻译成宿主注入的审批策略。"""

    mode = approval_mode or "ask"
    strategy = APPROVAL_STRATEGIES.get(mode, ApprovalStrategy.CONFIGURED)
    policy_type = _DenyApprovalPolicy if mode == "deny-all" else DefaultToolPolicy
    return policy_type(
        policy_version="sage.cli.deny-all/v1" if mode == "deny-all" else "1",
        approval_strategy=strategy,
        allow_persistent_approval=mode == "ask",
        approval_matcher=cli_approval_matcher,
        approval_matcher_id=CLI_APPROVAL_MATCHER_ID,
    )


def workspace_approval_store_path(store_root: str | Path, workspace: str | Path) -> Path:
    """workspace 作用域记忆的文件位置：宿主目录下按工作区路径散列分文件。

    刻意不放进工作区本身：仓库里带一份"预先批准"的文件会变成供应链入口。
    """

    resolved = Path(workspace).expanduser().resolve()
    digest = hashlib.sha256(resolved.as_posix().encode("utf-8")).hexdigest()[:24]
    return Path(store_root).expanduser() / f"{digest}.json"


class WorkspaceApprovalMemory:
    """在 Kernel 的 session 记忆之上叠加 ``workspace`` 作用域。

    ``session`` 作用域原样交给被包装的记忆（会话派生状态，随 Session 删除清理）；
    ``workspace`` 作用域记在 ``session_root/approvals/<workspace-hash>.json``，同一
    工作区的后续进程/会话都能命中。文件损坏、版本不认识或工作区不匹配一律当作没有
    记忆：只会多问一次，不会放宽。
    """

    VERSION = 1
    supported_scopes: frozenset[str] = frozenset({"session", "workspace"})

    def __init__(
        self,
        session_memory: ApprovalMemory,
        *,
        store_root: str | Path,
        workspace: str | Path,
    ) -> None:
        self.session_memory = session_memory
        self.workspace = Path(workspace).expanduser().resolve()
        self.path = workspace_approval_store_path(store_root, self.workspace)
        self._lock = asyncio.Lock()

    async def lookup(
        self, *, session_id: str, matcher: ApprovalMatcher
    ) -> RememberedApproval | None:
        remembered = await self.session_memory.lookup(
            session_id=session_id, matcher=matcher
        )
        if remembered is not None:
            return remembered
        raw = (await self._entries()).get(matcher.key)
        if raw is None:
            return None
        try:
            remembered = RememberedApproval.model_validate(raw)
        except ValueError:
            return None
        return remembered if remembered.matcher == matcher else None

    async def remember(
        self, *, session_id: str, approval: RememberedApproval
    ) -> None:
        if approval.scope == "session":
            await self.session_memory.remember(session_id=session_id, approval=approval)
            return
        if approval.scope not in self.supported_scopes:
            raise ValueError(
                f"approval scope {approval.scope!r} is not supported by "
                "WorkspaceApprovalMemory"
            )
        async with self._lock:
            entries = await self._entries()
            entries[approval.matcher.key] = approval.model_dump(mode="json")
            await self._store(entries)

    async def forget(
        self, *, session_id: str, matcher: ApprovalMatcher | None = None
    ) -> int:
        removed = await self.session_memory.forget(
            session_id=session_id, matcher=matcher
        )
        async with self._lock:
            entries = await self._entries()
            if matcher is None:
                removed += len(entries)
                if entries:
                    await self._store({})
                return removed
            if entries.pop(matcher.key, None) is not None:
                removed += 1
                await self._store(entries)
        return removed

    async def list_remembered(
        self, *, session_id: str
    ) -> tuple[RememberedApproval, ...]:
        session_entries = await self.session_memory.list_remembered(
            session_id=session_id
        )
        workspace_entries = []
        for _key, raw in sorted((await self._entries()).items()):
            try:
                workspace_entries.append(RememberedApproval.model_validate(raw))
            except ValueError:
                continue
        return (*session_entries, *workspace_entries)

    def composition_identity(self) -> dict[str, Any]:
        identity = getattr(self.session_memory, "composition_identity", None)
        return {
            "provider": "sage.cli.workspace-approval-memory",
            "scopes": sorted(self.supported_scopes),
            "version": self.VERSION,
            "session": identity() if callable(identity) else None,
        }

    async def _entries(self) -> dict[str, Any]:
        def read() -> dict[str, Any]:
            try:
                raw = json.loads(self.path.read_text("utf-8"))
            except (OSError, ValueError):
                return {}
            if (
                not isinstance(raw, dict)
                or raw.get("version") != self.VERSION
                or raw.get("workspace") != self.workspace.as_posix()
            ):
                return {}
            entries = raw.get("entries")
            return dict(entries) if isinstance(entries, dict) else {}

        return await asyncio.to_thread(read)

    async def _store(self, entries: dict[str, Any]) -> None:
        payload = {
            "version": self.VERSION,
            "workspace": self.workspace.as_posix(),
            "entries": entries,
        }

        def write() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                "utf-8",
            )
            os.replace(temporary, self.path)

        await asyncio.to_thread(write)


def format_remembered_approvals(remembered: Sequence[RememberedApproval]) -> str:
    if not remembered:
        return "no remembered approvals in this session or workspace"
    lines = [
        "remembered approvals in this session and workspace "
        "(/forget <n> | /forget all):"
    ]
    for index, value in enumerate(remembered, 1):
        lines.append(
            f"  {index}. {value.matcher.summary}  "
            f"[{value.scope}, by {value.remembered_by}, "
            f"{value.remembered_at:%Y-%m-%d %H:%M} UTC]"
        )
    return "\n".join(lines)


__all__ = [
    "APPROVAL_STRATEGIES",
    "CLI_APPROVAL_MATCHER_ID",
    "WorkspaceApprovalMemory",
    "build_tool_policy",
    "cli_approval_matcher",
    "format_remembered_approvals",
    "workspace_approval_store_path",
]
