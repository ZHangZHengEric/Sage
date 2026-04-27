#!/usr/bin/env python3
"""turn_status 协议工具

agent 在「任务完成 / 需要用户输入或确认 / 被阻塞 / 需要继续执行」时调用，
显式报告本轮状态。

调用契约（由 SimpleAgent 在调用前校验）：
- 在调用 ``turn_status`` 之前，本轮 assistant 必须已经输出过一段非空自然语言总结、
  提问、确认请求或阻塞说明；否则该次调用会被拒绝，并要求模型先补说明再调用。
- 当 assistant 向用户提问、请求确认、让用户选择，或等待用户上传/补充信息时，
  必须调用 ``turn_status(status="need_user_input")``。
- 当 assistant 刚输出的文字只是阶段说明、进度说明或中间内容，后面还需要继续执行时，
  必须调用 ``turn_status(status="continue_work")``，此时上层不会结束本轮。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..tool_base import tool
from ..error_codes import ToolErrorCode, make_tool_error
from sagents.utils.logger import logger


_VALID_STATUSES = {"task_done", "need_user_input", "blocked", "continue_work"}


class TurnStatusTool:
    """显式报告本轮是否结束或继续的标记工具。"""

    @tool(
        description_i18n={
            "zh": (
                "报告本轮状态。调用前必须先用自然语言告诉用户当前结果、需要用户回答的问题、确认项或阻塞原因；"
                "不能只调用工具不写说明。如果你向用户提问、请求确认、让用户选择，或等待用户上传/补充信息，"
                "必须设置 status=need_user_input。如果刚才输出的文字只是阶段说明、进度说明或中间内容，"
                "后面还需要继续执行，必须设置 status=continue_work。"
                "status 只能取：task_done / need_user_input / blocked / continue_work。"
            ),
            "en": (
                "Report the current turn status. Before calling, you MUST have already produced user-facing text. "
                "Use status=need_user_input when asking the user, requesting confirmation, offering choices, "
                "or waiting for user input/upload. Use status=continue_work when the previous text was only "
                "intermediate progress and more work is needed. status must be one of: "
                "task_done | need_user_input | blocked | continue_work."
            ),
        },
        param_description_i18n={
            "status": {
                "zh": "本轮状态：task_done / need_user_input / blocked / continue_work",
                "en": "Turn status: task_done | need_user_input | blocked | continue_work",
            },
            "note": {
                "zh": "可选简短备注，用作前端状态标签（不替代正文说明）",
                "en": "Optional short note for UI status (does not replace user-facing text)",
            },
            "session_id": {"zh": "会话ID（必填，自动注入）", "en": "Session ID (Required, Auto-injected)"},
        },
        param_schema={
            "status": {
                "type": "string",
                "enum": sorted(_VALID_STATUSES),
                "description": "task_done | need_user_input | blocked | continue_work",
            },
            "note": {"type": "string", "description": "Optional short status note"},
            "session_id": {"type": "string", "description": "Session ID"},
        },
    )
    async def turn_status(
        self,
        status: str,
        note: Optional[str] = None,
        session_id: str = None,
    ) -> Dict[str, Any]:
        if status not in _VALID_STATUSES:
            return make_tool_error(
                ToolErrorCode.INVALID_ARGUMENT,
                f"status 必须是 {sorted(_VALID_STATUSES)} 之一，收到: {status!r}",
                hint="改为 task_done / need_user_input / blocked / continue_work 之一后重试",
            )
        should_end = status != "continue_work"
        logger.info(f"TurnStatusTool: turn_status called status={status} should_end={should_end} note={note!r} session={session_id}")
        # 成功路径：保留标准 success/status，业务字段仅 should_end；入参 status/note 见日志
        return {
            "success": True,
            "status": "success",
            "should_end": should_end,
        }
