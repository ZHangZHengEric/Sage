from typing import Any, Dict, Optional


def _truncate(value: Optional[str], max_len: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _print_session_summary(summary: Dict[str, Any], *, prefix: str = "session") -> None:
    print(f"{prefix}_id: {summary.get('session_id')}")
    print(f"title: {_truncate(summary.get('title') or '(untitled)', 80)}")
    print(f"agent_name: {summary.get('agent_name')}")
    print(f"updated_at: {summary.get('updated_at')}")
    print(f"message_count: {summary.get('message_count')}")
    goal = summary.get("goal") or {}
    if isinstance(goal, dict) and goal.get("objective"):
        print(f"goal: {_truncate(goal.get('objective'), 120)}")
        print(f"goal_status: {goal.get('status')}")
    transition = summary.get("goal_transition") or {}
    if isinstance(transition, dict) and transition.get("type"):
        print(f"goal_transition: {transition.get('type')}")


def _print_message_preview(message: Optional[Dict[str, Any]], *, label: str) -> None:
    if not message:
        print(f"{label}: (none)")
        return
    role = message.get("role") or "unknown"
    message_type = message.get("type")
    content = _truncate(message.get("content") or "", 120)
    suffix = f" [{message_type}]" if message_type else ""
    print(f"{label}: [{role}]{suffix} {content}")


def _print_provider_summary(provider: Optional[Dict[str, Any]], *, prefix: str = "provider") -> None:
    if not provider:
        print(f"{prefix}: (none)")
        return
    print(f"{prefix}_id: {provider.get('id') or '(pending)'}")
    print(f"name: {provider.get('name') or '(unnamed)'}")
    print(f"model: {provider.get('model')}")
    print(f"base_url: {provider.get('base_url')}")
    print(f"api_key: {provider.get('api_key_preview') or '(hidden)'}")
    print(f"is_default: {provider.get('is_default')}")
    if provider.get("user_id") is not None:
        print(f"user_id: {provider.get('user_id')}")
    if provider.get("created_at"):
        print(f"created_at: {provider.get('created_at')}")
    if provider.get("updated_at"):
        print(f"updated_at: {provider.get('updated_at')}")
