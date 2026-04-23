from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from loguru import logger

from common.models.base import get_local_now
from common.models.token_usage import TokenUsage, TokenUsageDao


def _to_local_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone().replace(tzinfo=None)
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value)).astimezone().replace(tzinfo=None)
    return None


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


async def record_session_execution(
    *,
    session_context: Any,
    request_source: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    started_at: Any = None,
    finished_at: Any = None,
) -> bool:
    if not session_context:
        return False

    token_usage = session_context.get_tokens_usage_info()
    if not isinstance(token_usage, dict):
        return False

    total_info = token_usage.get("total_info") or {}
    if not isinstance(total_info, dict):
        return False

    total_tokens = total_info.get("total_tokens")
    if not isinstance(total_tokens, (int, float)):
        logger.bind(session_id=session_id or getattr(session_context, "session_id", "")).warning(
            "跳过 token_usage 落库：缺少 total_tokens"
        )
        return False

    per_step_info = token_usage.get("per_step_info") or []
    step_count = sum(
        1
        for step in per_step_info
        if isinstance(step, dict) and str(step.get("step_name") or "").strip()
    )

    resolved_started_at = (
        _to_local_datetime(started_at)
        or _to_local_datetime(getattr(session_context, "start_time", None))
        or get_local_now()
    )
    resolved_finished_at = (
        _to_local_datetime(finished_at)
        or _to_local_datetime(getattr(session_context, "end_time", None))
        or get_local_now()
    )
    if resolved_finished_at < resolved_started_at:
        resolved_finished_at = resolved_started_at

    record = TokenUsage(
        id=str(uuid.uuid4()),
        session_id=str(session_id or getattr(session_context, "session_id", "") or ""),
        user_id=str(user_id if user_id is not None else getattr(session_context, "user_id", "") or ""),
        agent_id=str(agent_id if agent_id is not None else getattr(session_context, "agent_id", "") or ""),
        request_source=str(request_source or ""),
        input_tokens=_to_int(total_info.get("prompt_tokens")),
        output_tokens=_to_int(total_info.get("completion_tokens")),
        total_tokens=_to_int(total_tokens),
        cached_tokens=_to_int(total_info.get("cached_tokens")),
        reasoning_tokens=_to_int(total_info.get("reasoning_tokens")),
        prompt_audio_tokens=_to_int(total_info.get("prompt_audio_tokens")),
        completion_audio_tokens=_to_int(total_info.get("completion_audio_tokens")),
        step_count=step_count,
        usage_payload=token_usage,
        started_at=resolved_started_at,
        finished_at=resolved_finished_at,
    )
    await TokenUsageDao().save_usage(record)
    logger.bind(
        session_id=record.session_id,
        agent_id=record.agent_id,
        request_source=record.request_source,
    ).info(
        f"token_usage 已落库: total_tokens={record.total_tokens}, steps={record.step_count}"
    )
    return True


async def get_token_usage_stats(
    *,
    group_by: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    return await TokenUsageDao().get_stats(
        group_by=group_by,
        user_id=user_id,
        agent_id=agent_id,
        session_id=session_id,
        start_time=_to_local_datetime(start_time),
        end_time=_to_local_datetime(end_time),
    )
