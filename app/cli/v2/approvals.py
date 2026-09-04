"""``--approval-mode`` 到审批策略的映射，以及 CLI 的"记住审批"匹配器。

策略即数据：这里只是把命令行选项翻译成 ``DefaultToolPolicy`` 的参数，
判定与记忆的执行都在 ``sagents.v2`` 内部完成。
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from sagents.v2.agent.policy import (
    ApprovalMatcher,
    ApprovalStrategy,
    DefaultToolPolicy,
    RememberedApproval,
    exact_arguments_matcher,
)
from sagents.v2.agent.policy.tool_policy import ToolPolicyContext

CLI_APPROVAL_MATCHER_ID = "sage.cli.approval-matcher/v1"
# ask：写类工具需审批（可记住）；always：每次工具调用都问（不可记住）；
# approve-all：策略层直接放行，不再产生审批交互；deny-all：策略照常，由固定应答拒绝。
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
    digest = hashlib.sha256(f"{tool_name}:{kind}:{value}".encode("utf-8")).hexdigest()
    summary = f"{tool_name}: {value}"
    if len(summary) > _SUMMARY_LIMIT:
        summary = summary[: _SUMMARY_LIMIT - 1] + "…"
    return ApprovalMatcher(
        tool_name=tool_name, fingerprint=f"{kind}:sha256:{digest}", summary=summary
    )


def cli_approval_matcher(context: ToolPolicyContext) -> ApprovalMatcher | None:
    """CLI 的记忆粒度：shell 按规范化后的整条命令，文件写入按路径，其余按完整参数。

    返回 None 表示本次调用不提供"记住"（只能 approve_once）。
    """

    name = context.definition.name
    arguments = context.call.arguments
    if name == _SHELL_TOOL:
        command = " ".join(str(arguments.get("command") or "").split())
        return _matcher(name, "command", command) if command else None
    if name in _PATH_TOOLS:
        path = str(arguments.get("file_path") or "").strip()
        return _matcher(name, "path", path) if path else None
    return exact_arguments_matcher(context)


def build_tool_policy(approval_mode: str | None) -> DefaultToolPolicy:
    """把 ``--approval-mode`` 翻译成宿主注入的审批策略。"""

    strategy = APPROVAL_STRATEGIES.get(approval_mode or "ask", ApprovalStrategy.CONFIGURED)
    return DefaultToolPolicy(
        approval_strategy=strategy,
        allow_persistent_approval=strategy == ApprovalStrategy.CONFIGURED,
        approval_matcher=cli_approval_matcher,
        approval_matcher_id=CLI_APPROVAL_MATCHER_ID,
    )


def format_remembered_approvals(remembered: Sequence[RememberedApproval]) -> str:
    if not remembered:
        return "no remembered approvals in this session"
    lines = ["remembered approvals in this session (/forget <n> | /forget all):"]
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
    "build_tool_policy",
    "cli_approval_matcher",
    "format_remembered_approvals",
]
