import json
import os
from typing import Any, Dict, List, Optional

from app.cli.services.base import CLIError
from app.cli.services.runtime import get_default_cli_user_id, init_cli_config


async def list_sessions(
    *,
    user_id: Optional[str] = None,
    limit: int = 20,
    search: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    from common.models.conversation import ConversationDao
    from common.schemas.conversation import ConversationInfo

    def _normalize_messages(raw_messages: Any) -> List[Dict[str, Any]]:
        if isinstance(raw_messages, str):
            try:
                raw_messages = json.loads(raw_messages)
            except Exception:
                return []
        return raw_messages if isinstance(raw_messages, list) else []

    def _build_last_message_preview(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        for message in reversed(messages):
            role = (message or {}).get("role")
            content = ((message or {}).get("content") or "").strip()
            if role and content:
                return {
                    "role": role,
                    "content": content,
                    "type": (message or {}).get("type"),
                }
        return {}

    resolved_user_id = user_id or get_default_cli_user_id()
    dao = ConversationDao()
    conversations, total_count = await dao.get_conversations_paginated(
        page=1,
        page_size=limit,
        user_id=resolved_user_id,
        search=search,
        agent_id=agent_id,
        sort_by="date",
    )

    items: List[Dict[str, Any]] = []
    for conv in conversations:
        message_count = conv.get_message_count()
        messages = _normalize_messages(conv.messages)
        last_message = _build_last_message_preview(messages)
        items.append(
            {
                **ConversationInfo(
                    session_id=conv.session_id,
                    user_id=conv.user_id,
                    agent_id=conv.agent_id,
                    agent_name=conv.agent_name,
                    title=conv.title,
                    message_count=message_count.get("user_count", 0) + message_count.get("agent_count", 0),
                    user_count=message_count.get("user_count", 0),
                    agent_count=message_count.get("agent_count", 0),
                    created_at=conv.created_at.isoformat() if conv.created_at else "",
                    updated_at=conv.updated_at.isoformat() if conv.updated_at else "",
                ).model_dump(),
                "last_message": last_message or None,
            }
        )

    return {
        "user_id": resolved_user_id,
        "limit": limit,
        "total": total_count,
        "list": items,
    }


def _resolve_agent_mode_from_config(agent_config: Dict[str, Any]) -> str:
    raw_value = str(
        agent_config.get("agentMode")
        or agent_config.get("agent_mode")
        or ""
    ).strip().lower()
    if raw_value in {"simple", "multi", "fibre"}:
        return raw_value
    return "simple"


async def list_cli_agents(
    *,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    from common.services.agent_service import list_agents

    resolved_user_id = user_id or get_default_cli_user_id()
    agents = await list_agents(user_id=resolved_user_id)
    items: List[Dict[str, Any]] = []
    for agent in agents:
        agent_config = agent.config if isinstance(agent.config, dict) else {}
        items.append(
            {
                "agent_id": agent.agent_id,
                "name": agent.name,
                "agent_mode": _resolve_agent_mode_from_config(agent_config),
                "is_default": bool(agent.is_default),
                "updated_at": agent.updated_at.isoformat() if agent.updated_at else "",
            }
        )

    items.sort(
        key=lambda item: (
            not bool(item.get("is_default")),
            item.get("name") or "",
            item.get("agent_id") or "",
        )
    )
    return {
        "user_id": resolved_user_id,
        "total": len(items),
        "list": items,
    }


async def list_available_skills(
    *,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    workspace: Optional[str] = None,
) -> Dict[str, Any]:
    from sagents.skill.skill_manager import SkillManager

    cfg = init_cli_config(init_logging=False)
    resolved_user_id = user_id or get_default_cli_user_id()
    if agent_id:
        from common.services import skill_service

        agent_skills = await skill_service.get_agent_available_skills(
            agent_id=agent_id,
            current_user_id=resolved_user_id,
            role="admin" if resolved_user_id == "admin" else "user",
        )
        skills = []
        source_counts: Dict[str, int] = {}
        for item in agent_skills:
            source_name = item.get("source_dimension") or item.get("dimension") or "unknown"
            source_counts[source_name] = source_counts.get(source_name, 0) + 1
            skills.append(
                {
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "source": source_name,
                    "path": item.get("path"),
                    "need_update": bool(item.get("need_update")),
                    "agent_id": agent_id,
                }
            )
        skills.sort(key=lambda item: item["name"] or "")
        return {
            "user_id": resolved_user_id,
            "agent_id": agent_id,
            "workspace": None,
            "sources": [],
            "total": len(skills),
            "source_counts": source_counts,
            "list": skills,
            "errors": [],
        }

    skill_sources: List[Dict[str, Any]] = []
    skills_map: Dict[str, Dict[str, Any]] = {}

    source_defs: List[tuple[str, Optional[str]]] = [
        ("system", cfg.skill_dir if os.path.isdir(cfg.skill_dir) else None),
        (
            "user",
            os.path.join(cfg.user_dir, resolved_user_id, "skills")
            if os.path.isdir(os.path.join(cfg.user_dir, resolved_user_id, "skills"))
            else None,
        ),
        (
            "workspace",
            os.path.join(os.path.abspath(workspace), "skills")
            if workspace and os.path.isdir(os.path.join(os.path.abspath(workspace), "skills"))
            else None,
        ),
    ]

    for source_name, source_path in source_defs:
        if not source_path:
            continue
        skill_sources.append({"source": source_name, "path": source_path})
        try:
            tm = SkillManager(skill_dirs=[source_path], isolated=True)
            for skill in tm.list_skill_info():
                skills_map[skill.name] = {
                    "name": skill.name,
                    "description": skill.description,
                    "source": source_name,
                    "path": skill.path,
                }
        except Exception as exc:
            skills_map[f"__error__:{source_name}"] = {
                "name": f"[error:{source_name}]",
                "description": str(exc),
                "source": source_name,
                "path": source_path,
            }

    skills = [value for key, value in skills_map.items() if not key.startswith("__error__:")]
    skills.sort(key=lambda item: item["name"])

    errors = [value for key, value in skills_map.items() if key.startswith("__error__:")]
    source_counts: Dict[str, int] = {}
    for item in skills:
        source_name = item["source"]
        source_counts[source_name] = source_counts.get(source_name, 0) + 1

    return {
        "user_id": resolved_user_id,
        "agent_id": None,
        "workspace": os.path.abspath(workspace) if workspace else None,
        "sources": skill_sources,
        "total": len(skills),
        "source_counts": source_counts,
        "list": skills,
        "errors": errors,
    }


async def validate_requested_skills(
    *,
    requested_skills: Optional[List[str]],
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    workspace: Optional[str] = None,
) -> List[str]:
    normalized = [skill.strip() for skill in (requested_skills or []) if skill and skill.strip()]
    if not normalized:
        return []

    result = await list_available_skills(user_id=user_id, agent_id=agent_id, workspace=workspace)
    available_names = {item["name"] for item in result.get("list", [])}
    missing = [skill for skill in normalized if skill not in available_names]
    if missing:
        available_display = ", ".join(sorted(available_names)) if available_names else "(none)"
        next_steps = ["Run `sage skills` to inspect currently visible skills."]
        if agent_id:
            next_steps[0] = f"Run `sage skills --agent-id {agent_id}` to inspect the skills currently available to that agent."
        if workspace:
            next_steps.append(
                f"Run `sage skills --workspace {os.path.abspath(workspace)}` to inspect workspace skills."
            )
        raise CLIError(
            "Unknown CLI skill(s): "
            f"{', '.join(missing)}\n"
            f"Available skills: {available_display}",
            next_steps=next_steps,
        )
    return normalized


async def get_session_summary(
    *,
    session_id: str,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    from common.models.conversation import ConversationDao
    from common.services.conversation_service import (
        _load_session_goal,
        _load_session_goal_transition,
    )

    dao = ConversationDao()
    conversation = await dao.get_by_session_id(session_id)
    if not conversation:
        return None

    if user_id and conversation.user_id and conversation.user_id != user_id:
        return None

    counts = conversation.get_message_count()
    goal = _load_session_goal(session_id)
    goal_transition = _load_session_goal_transition(session_id)
    return {
        "session_id": conversation.session_id,
        "user_id": conversation.user_id,
        "agent_id": conversation.agent_id,
        "agent_name": conversation.agent_name,
        "title": conversation.title,
        "message_count": counts.get("user_count", 0) + counts.get("agent_count", 0),
        "user_count": counts.get("user_count", 0),
        "agent_count": counts.get("agent_count", 0),
        "created_at": conversation.created_at.isoformat() if conversation.created_at else "",
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else "",
        "goal": goal.model_dump(mode="json") if goal else None,
        "goal_transition": goal_transition.model_dump(mode="json") if goal_transition else None,
    }


async def inspect_session(
    *,
    session_id: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    message_limit: int = 5,
) -> Dict[str, Any]:
    from common.models.conversation import ConversationDao

    def _normalize_messages(raw_messages: Any) -> List[Dict[str, Any]]:
        if isinstance(raw_messages, str):
            try:
                raw_messages = json.loads(raw_messages)
            except Exception:
                return []
        return raw_messages if isinstance(raw_messages, list) else []

    def _find_last_message(messages: List[Dict[str, Any]], *, role: Optional[str] = None) -> Optional[Dict[str, Any]]:
        for message in reversed(messages):
            message_role = (message or {}).get("role")
            content = ((message or {}).get("content") or "").strip()
            if role and message_role != role:
                continue
            if content:
                return {
                    "role": message_role,
                    "type": (message or {}).get("type"),
                    "content": content,
                    "message_id": (message or {}).get("message_id"),
                }
        return None

    dao = ConversationDao()
    resolved_user_id = user_id or get_default_cli_user_id()

    if session_id == "latest":
        recent = await dao.get_recent_conversations(
            user_id=resolved_user_id,
            agent_id=agent_id,
        )
        conversation = recent[0] if recent else None
    else:
        conversation = await dao.get_by_session_id(session_id)

    if not conversation:
        if session_id == "latest":
            scope_suffix = f" for user {resolved_user_id}"
            if agent_id:
                scope_suffix += f" and agent {agent_id}"
            raise CLIError(
                f"No recent session found{scope_suffix}",
                next_steps=["Run `sage sessions` to inspect visible sessions."],
            )
        raise CLIError(
            f"Session not found: {session_id}",
            next_steps=["Run `sage sessions` to inspect visible sessions."],
        )

    if resolved_user_id and conversation.user_id and conversation.user_id != resolved_user_id:
        raise CLIError(
            f"Session {conversation.session_id} is not visible to user {resolved_user_id}",
            next_steps=["Check `--user-id`, or run `sage sessions --user-id <user>` to inspect visible sessions."],
        )
    if agent_id and conversation.agent_id and conversation.agent_id != agent_id:
        raise CLIError(
            f"Session {conversation.session_id} is not visible to agent {agent_id}",
            next_steps=[f"Run `sage sessions --agent-id {agent_id}` to inspect sessions for that agent."],
        )

    counts = conversation.get_message_count()
    messages = _normalize_messages(conversation.messages or [])

    normalized_limit = max(0, int(message_limit))
    preview_messages = []
    start_index = max(0, len(messages) - normalized_limit)
    for index, message in enumerate(messages[start_index:], start=start_index):
        preview_messages.append(
            {
                "index": index,
                "role": (message or {}).get("role"),
                "type": (message or {}).get("type"),
                "content": (message or {}).get("content"),
                "message_id": (message or {}).get("message_id"),
            }
        )

    return {
        "session_id": conversation.session_id,
        "user_id": conversation.user_id,
        "agent_id": conversation.agent_id,
        "agent_name": conversation.agent_name,
        "title": conversation.title,
        "message_count": counts.get("user_count", 0) + counts.get("agent_count", 0),
        "user_count": counts.get("user_count", 0),
        "agent_count": counts.get("agent_count", 0),
        "created_at": conversation.created_at.isoformat() if conversation.created_at else "",
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else "",
        "last_user_message": _find_last_message(messages, role="user"),
        "last_assistant_message": _find_last_message(messages, role="assistant")
        or _find_last_message(messages, role="agent"),
        "recent_messages": preview_messages,
        "message_preview_limit": normalized_limit,
    }

