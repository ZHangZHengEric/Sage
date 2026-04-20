"""
Agent 与全局 session 注册表交互的统一入口，避免在每个 Agent 中重复编写。

- ``get_live_session(session_id)``：从全局 session manager 拿到 live session；
- ``get_live_session_context(session_id)``：直接拿对应的 SessionContext；
- ``should_abort_due_to_session(session_context, ...)``：聚合"会话中断/出错/已完成"以及
  父会话状态的判断，命中即返回 True，调用方应直接 return。
"""

from __future__ import annotations

from typing import Any, Optional

from sagents.context.session_context import SessionContext, SessionStatus
from sagents.utils.logger import logger


def get_live_session(session_id: Optional[str], log_prefix: str = "AgentBase") -> Optional[Any]:
    """根据 session_id 获取 live session；任何异常都吞掉返回 None。"""
    if not session_id:
        return None
    try:
        # 延迟 import 避免循环依赖
        from sagents.session_runtime import get_global_session_manager

        session_manager = get_global_session_manager()
        if not session_manager:
            return None
        return session_manager.get_live_session(session_id)
    except Exception as exc:
        logger.debug(f"{log_prefix}: 获取 live session 失败, session_id={session_id}: {exc}")
        return None


def get_live_session_context(
    session_id: Optional[str], log_prefix: str = "AgentBase"
) -> Optional[SessionContext]:
    session = get_live_session(session_id, log_prefix=log_prefix)
    return session.session_context if session else None


def get_session_sandbox(
    session_id: str,
    *,
    log_prefix: str = "Tool",
    error_cls: type = ValueError,
) -> Any:
    """从指定 session 取出 sandbox，缺失或无效时按 ``error_cls`` 抛错。

    被多个 tool 共用，避免每个工具都重写一遍
    "拿 session manager → 拿 session → 校验 session_context → 校验 sandbox" 的样板代码。

    Args:
        session_id: 会话 ID。
        log_prefix: 错误信息前缀（一般传工具名，如 ``"FileSystemTool"``）。
        error_cls: 抛出的异常类型，默认 ``ValueError``；调用方有自定义异常的可传入。
    """
    session = get_live_session(session_id, log_prefix=log_prefix)
    if not session or not getattr(session, 'session_context', None):
        raise error_cls(f"{log_prefix}: Invalid session_id={session_id}")

    sandbox = session.session_context.sandbox
    if not sandbox:
        raise error_cls(f"{log_prefix}: No sandbox available for session_id={session_id}")
    return sandbox


def should_abort_due_to_session(
    session_context: SessionContext,
    log_prefix: str = "Agent",
) -> bool:
    """检查会话与父会话状态，命中则应停止执行。

    - session_context.session_id 已被中断/出错/已完成 → True；
    - 父会话状态非运行中 → 同时把当前会话标为 INTERRUPTED 并返回 True。
    """
    session_id = session_context.session_id
    session = get_live_session(session_id, log_prefix=log_prefix)
    if session_id and session is None:
        logger.info(f"{log_prefix}: 跳过执行，session上下文不存在或已中断")
        return True

    if session and session.get_status() in [
        SessionStatus.INTERRUPTED,
        SessionStatus.ERROR,
        SessionStatus.COMPLETED,
    ]:
        logger.info(f"{log_prefix}: 跳过执行，session状态为{session.get_status().value}")
        return True

    parent_session_id = getattr(session_context, 'parent_session_id', None)
    if parent_session_id:
        parent_session = get_live_session(parent_session_id, log_prefix=log_prefix)
        if parent_session and parent_session.get_status() in [
            SessionStatus.INTERRUPTED,
            SessionStatus.ERROR,
            SessionStatus.COMPLETED,
        ]:
            logger.info(
                f"{log_prefix}: 跳过执行，父会话 {parent_session_id} 状态为{parent_session.get_status().value}"
            )
            if session is None:
                return True
            session.set_status(SessionStatus.INTERRUPTED, cascade=False)
            return True
    return False
