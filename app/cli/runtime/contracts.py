import json
import uuid
from typing import Any, Dict, List, Optional

from app.cli.runtime.stats import _tool_step_event_key


def _emit_json_tool_events(
    previous_steps: Dict[str, str],
    current_steps: List[Dict[str, Any]],
) -> None:
    for step in current_steps:
        if not isinstance(step, dict):
            continue
        key = _tool_step_event_key(step)
        previous_status = previous_steps.get(key)
        current_status = str(step.get("status") or "")
        if current_status == previous_status:
            continue

        action = None
        if current_status == "running" and previous_status is None:
            action = "started"
        elif previous_status == "running" and current_status in {"completed", "failed"}:
            action = "finished"
        if not action:
            continue

        print(
            json.dumps(
                {
                    "type": "cli_tool",
                    "action": action,
                    "step": step.get("step"),
                    "tool_name": step.get("tool_name"),
                    "tool_call_id": step.get("tool_call_id"),
                    "status": current_status,
                },
                ensure_ascii=False,
            )
        )


def _emit_json_session_event(
    request: Any,
    workspace: Optional[str],
    *,
    command_mode: str,
    session_summary: Optional[Dict[str, Any]] = None,
) -> None:
    prior_message_count = 0
    if isinstance(session_summary, dict):
        raw_message_count = session_summary.get("message_count")
        if isinstance(raw_message_count, int):
            prior_message_count = max(0, raw_message_count)
    session_state = "existing" if session_summary else "new"
    print(
        json.dumps(
            {
                "type": "cli_session",
                "command_mode": command_mode,
                "session_state": session_state,
                "session_id": getattr(request, "session_id", None),
                "user_id": getattr(request, "user_id", None),
                "agent_id": getattr(request, "agent_id", None),
                "agent_mode": getattr(request, "agent_mode", None),
                "workspace": workspace,
                "workspace_source": "explicit" if workspace else "default",
                "requested_skills": list(getattr(request, "available_skills", None) or []),
                "max_loop_count": getattr(request, "max_loop_count", None),
                "has_prior_messages": prior_message_count > 0,
                "prior_message_count": prior_message_count,
                "session_summary": session_summary,
            },
            ensure_ascii=False,
        )
    )


def _ensure_request_session_id(request: Any) -> str:
    session_id = getattr(request, "session_id", None)
    if isinstance(session_id, str) and session_id.strip():
        normalized = session_id.strip()
        if normalized != session_id:
            setattr(request, "session_id", normalized)
        return normalized

    resolved = str(uuid.uuid4())
    setattr(request, "session_id", resolved)
    return resolved

