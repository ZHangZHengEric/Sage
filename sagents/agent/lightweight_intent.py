import re
from typing import Any, Iterable, Optional

from sagents.context.messages.message import MessageChunk, MessageRole


_LIGHTWEIGHT_PATTERNS = [
    re.compile(
        r"^(?:hi|hello|hey|yo|hola|你好|您好|嗨|哈喽|早上好|晚上好|在吗|在嘛|在麼)"
        r"(?:\s+(?:sage|assistant|助手))?[!！?？。,. ]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:介绍(?:下|一下)?自己|介绍(?:下|一下)?你自己|自我介绍|介绍一下你自己)[!！?？。,. ]*$"
    ),
    re.compile(
        r"^(?:tell me about yourself|introduce yourself|who are you|what can you do)"
        r"(?:\s+please)?[!?. ]*$",
        re.IGNORECASE,
    ),
]

_NON_TRIVIAL_MARKERS = [
    "/",
    "\\",
    "`",
    "```",
    ".py",
    ".js",
    ".ts",
    ".rs",
    "fix",
    "debug",
    "error",
    "bug",
    "implement",
    "inspect",
    "edit",
    "repo",
    "project",
    "代码",
    "文件",
    "实现",
    "修改",
    "调试",
    "测试",
    "仓库",
    "项目",
]


def extract_latest_user_text(messages: Iterable[MessageChunk]) -> str:
    for message in reversed(list(messages)):
        if message.role != MessageRole.USER.value:
            continue
        if isinstance(message.content, str) and message.content.strip():
            return message.content.strip()
    return ""


def extract_latest_user_text_from_any(messages: Iterable[Any]) -> str:
    for message in reversed(list(messages)):
        if isinstance(message, MessageChunk):
            role = message.role
            content: Optional[str] = message.content if isinstance(message.content, str) else None
        elif isinstance(message, dict):
            role = message.get("role")
            raw_content = message.get("content")
            content = raw_content if isinstance(raw_content, str) else None
        else:
            role = getattr(message, "role", None)
            raw_content = getattr(message, "content", None)
            content = raw_content if isinstance(raw_content, str) else None
        if role != MessageRole.USER.value:
            continue
        if content and content.strip():
            return content.strip()
    return ""


def should_skip_preflight_for_lightweight_prompt(text: str) -> bool:
    normalized = " ".join((text or "").strip().lower().split())
    if not normalized or len(normalized) > 64:
        return False
    if any(marker in normalized for marker in _NON_TRIVIAL_MARKERS):
        return False
    return any(pattern.fullmatch(normalized) for pattern in _LIGHTWEIGHT_PATTERNS)
