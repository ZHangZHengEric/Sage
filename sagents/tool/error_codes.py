"""统一的内置工具错误码与构造助手。

所有内置工具的失败返回应使用 ``make_tool_error`` 构造，确保模型可以根据
``error_code`` 做出确定性的纠错动作，而不是依赖中文消息字符串匹配。

返回形如::

    {
        "success": False,
        "status": "error",            # 兼容旧字段
        "error_code": "MULTIPLE_MATCHES",
        "error": "search_pattern matched 3 times ...",
        "hint": "Tighten the search pattern or set replace_all=true",
        # 可选附加字段（matches/match_count/file_path 等）由调用方扩展
    }
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class ToolErrorCode:
    """工具错误码常量集合（保持纯字符串便于跨进程序列化）。"""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_FOUND = "NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"
    MULTIPLE_MATCHES = "MULTIPLE_MATCHES"
    NO_MATCH = "NO_MATCH"
    TIMEOUT = "TIMEOUT"
    SANDBOX_ERROR = "SANDBOX_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def make_tool_error(
    code: str,
    message: str,
    hint: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """构造统一的工具错误返回。

    Args:
        code: ``ToolErrorCode`` 中的常量字符串。
        message: 面向模型 / 用户的人类可读错误信息。
        hint: 可选的下一步建议；缺省则不写入。
        **extra: 调用方可以追加任意上下文字段（如 ``file_path``、``matches``）。

    Returns:
        统一格式的错误字典。
    """
    payload: Dict[str, Any] = {
        "success": False,
        "status": "error",
        "error_code": code or ToolErrorCode.INTERNAL_ERROR,
        "error": message,
        "message": message,  # 兼容旧消费方
    }
    if hint:
        payload["hint"] = hint
    for key, value in extra.items():
        if value is None:
            continue
        payload[key] = value
    return payload


__all__ = ["ToolErrorCode", "make_tool_error"]
