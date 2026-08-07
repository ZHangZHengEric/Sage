import copy
import re
from typing import Any, Dict, List, Tuple


ENABLE_PLAN_TAG_RE = re.compile(
    r"^\s*<enable_plan>\s*(true|false)\s*</enable_plan>\s*",
    re.IGNORECASE,
)
ENABLE_DEEP_THINKING_TAG_RE = re.compile(
    r"^\s*<enable_deep_thinking>\s*(true|false)\s*</enable_deep_thinking>\s*",
    re.IGNORECASE,
)
THINKING_LEVEL_TAG_RE = re.compile(
    r"^\s*<(?:thinking_level|deep_thinking_level)>\s*"
    r"(minimal|low|medium|high|xhigh|max)\s*"
    r"</(?:thinking_level|deep_thinking_level)>\s*",
    re.IGNORECASE,
)


def _get_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role", ""))
    return str(getattr(message, "role", ""))


def _get_content(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content")
    return getattr(message, "content", None)


def _set_content(message: Any, content: Any) -> None:
    if isinstance(message, dict):
        message["content"] = content
    else:
        message.content = content


def _extract_control_flags_from_text(text: str) -> Tuple[str, Dict[str, Any]]:
    if not isinstance(text, str):
        return text, {}

    flags: Dict[str, Any] = {}
    remaining = text

    while True:
        matched = False

        plan_match = ENABLE_PLAN_TAG_RE.match(remaining)
        if plan_match:
            flags["enable_plan"] = plan_match.group(1).lower() == "true"
            remaining = remaining[plan_match.end() :]
            matched = True

        deep_thinking_match = ENABLE_DEEP_THINKING_TAG_RE.match(remaining)
        if deep_thinking_match:
            flags["enable_deep_thinking"] = (
                deep_thinking_match.group(1).lower() == "true"
            )
            remaining = remaining[deep_thinking_match.end() :]
            matched = True

        thinking_level_match = THINKING_LEVEL_TAG_RE.match(remaining)
        if thinking_level_match:
            flags["thinking_level"] = thinking_level_match.group(1).lower()
            remaining = remaining[thinking_level_match.end() :]
            matched = True

        if not matched:
            break

    return remaining, flags


def _extract_control_flags_from_content(content: Any) -> Tuple[Any, Dict[str, Any]]:
    if isinstance(content, str):
        return _extract_control_flags_from_text(content)

    if isinstance(content, list):
        flags: Dict[str, Any] = {}
        new_content: List[Dict[str, Any]] = []
        parsed_first_text = False

        for item in content:
            if (
                not parsed_first_text
                and isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                parsed_first_text = True
                new_text, new_flags = _extract_control_flags_from_text(item["text"])
                if new_flags:
                    flags.update(new_flags)
                if new_text:
                    new_item = copy.deepcopy(item)
                    new_item["text"] = new_text
                    new_content.append(new_item)
                continue

            new_content.append(copy.deepcopy(item) if isinstance(item, dict) else item)

        if not new_content:
            return "", flags
        return new_content, flags

    return content, {}


def extract_control_flags_from_messages(messages: List[Any]) -> Dict[str, Any]:
    flags: Dict[str, Any] = {}

    for message in messages or []:
        if _get_role(message) != "user":
            continue

        content = _get_content(message)
        new_content, message_flags = _extract_control_flags_from_content(content)
        if message_flags:
            flags.update(message_flags)
            _set_content(message, new_content)

    return flags
