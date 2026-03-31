import copy
import re
from typing import Any, Dict, List, Tuple


ENABLE_PLAN_TAG_RE = re.compile(
    r"^\s*<enable_plan>\s*(true|false)\s*</enable_plan>\s*",
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


def _extract_enable_plan_from_text(text: str) -> Tuple[str, Dict[str, bool]]:
    if not isinstance(text, str):
        return text, {}

    flags: Dict[str, bool] = {}
    remaining = text

    while True:
        match = ENABLE_PLAN_TAG_RE.match(remaining)
        if not match:
            break
        flags["enable_plan"] = match.group(1).lower() == "true"
        remaining = remaining[match.end():]

    return remaining, flags


def _extract_enable_plan_from_content(content: Any) -> Tuple[Any, Dict[str, bool]]:
    if isinstance(content, str):
        return _extract_enable_plan_from_text(content)

    if isinstance(content, list):
        flags: Dict[str, bool] = {}
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
                new_text, new_flags = _extract_enable_plan_from_text(item["text"])
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


def extract_control_flags_from_messages(messages: List[Any]) -> Dict[str, bool]:
    flags: Dict[str, bool] = {}

    for message in messages or []:
        if _get_role(message) != "user":
            continue

        content = _get_content(message)
        new_content, message_flags = _extract_enable_plan_from_content(content)
        if message_flags:
            flags.update(message_flags)
            _set_content(message, new_content)

    return flags
