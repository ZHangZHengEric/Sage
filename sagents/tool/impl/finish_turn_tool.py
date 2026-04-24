#!/usr/bin/env python3
"""finish_turn 工具

agent 在「任务完成 / 需要用户输入 / 被阻塞」时调用，显式结束本轮。

调用契约（由 SimpleAgent 在调用前校验）：
- 在调用 ``finish_turn`` 之前，本轮 assistant 必须已经输出过一段非空自然语言总结；
  否则该次调用会被拒绝（返回 INVALID_ARGUMENT），并要求模型先补总结再调用。

工具本身不做副作用，仅落一条结构化结果，供上层判断终止。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..tool_base import tool
from ..error_codes import ToolErrorCode, make_tool_error
from sagents.utils.logger import logger


_VALID_REASONS = {"task_done", "need_user_input", "blocked"}


class FinishTurnTool:
    """显式结束本轮的标记工具。"""

    @tool(
        description_i18n={
            "zh": (
                "结束本轮：当你认为本轮可以结束时调用。"
                "调用前必须先用一段自然语言总结当前进展和结果（不能只调用工具不写总结）。"
                "reason 只能取以下三个枚举值：task_done（任务完成）/need_user_input（需要用户补充信息）/blocked（受阻无法继续）。"
            ),
            "en": (
                "End the current turn explicitly. Before calling, you MUST have already produced a natural-language "
                "summary of progress and result in this turn (do not call this tool without writing a summary). "
                "reason must be one of: task_done | need_user_input | blocked."
            ),
        },
        param_description_i18n={
            "reason": {
                "zh": "结束本轮的原因，只能是 task_done / need_user_input / blocked",
                "en": "Reason for ending the turn: task_done | need_user_input | blocked",
            },
            "note": {
                "zh": "可选简短备注，用作前端状态标签（不替代正文总结）",
                "en": "Optional short note for UI status (does not replace the summary)",
            },
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "reason": {
                "type": "string",
                "enum": sorted(_VALID_REASONS),
                "description": "task_done | need_user_input | blocked",
            },
            "note": {"type": "string", "description": "Optional short status note"},
            "session_id": {"type": "string", "description": "Session ID"},
        },
    )
    async def finish_turn(
        self,
        reason: str,
        note: Optional[str] = None,
        session_id: str = None,
    ) -> Dict[str, Any]:
        if reason not in _VALID_REASONS:
            return make_tool_error(
                ToolErrorCode.INVALID_ARGUMENT,
                f"reason 必须是 {sorted(_VALID_REASONS)} 之一，收到: {reason!r}",
                hint="改为 task_done / need_user_input / blocked 之一后重试",
            )
        logger.info(f"FinishTurnTool: finish_turn called reason={reason} note={note!r} session={session_id}")
        return {
            "success": True,
            "status": "success",
            "reason": reason,
            "note": note or "",
            "message": f"finish_turn acknowledged: {reason}",
        }
