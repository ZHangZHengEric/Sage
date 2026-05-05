import asyncio
import json
import os
import sys
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from app.cli.runtime.contracts import (
    _emit_json_notice_event,
    _emit_json_goal_event,
    _emit_json_session_event,
    _emit_json_tool_events,
    _ensure_request_session_id,
)
from app.cli.runtime.rendering import (
    _build_stream_idle_notice_for_state,
    _emit_stream_idle_notice_for_state,
    _empty_render_state,
    _print_plain_event,
)
from app.cli.runtime.stats import (
    _empty_stats,
    _finalize_stats,
    _print_stats,
    _record_stats_event,
    _snapshot_tool_steps,
)


STREAM_IDLE_NOTICE_SECONDS = 3.0
STREAM_IDLE_REPEAT_SECONDS = 5.0
SESSION_LOG_SCAN_BYTES = 64 * 1024


def _resolve_session_log_path(session_id: Optional[str]) -> Optional[Path]:
    if not session_id:
        return None
    session_dir = (
        os.environ.get("SAGE_SESSION_DIR")
        or os.environ.get("SAGE_SESSION_DIR_PATH")
        or None
    )
    if not session_dir:
        from common.core.config import get_local_storage_defaults

        session_dir = get_local_storage_defaults()["session_dir"]
    return Path(session_dir) / session_id / f"session_{session_id}.log"


def _extract_recent_session_issue_notice(
    session_id: Optional[str],
    *,
    request_started_at_epoch: float,
) -> Optional[str]:
    log_path = _resolve_session_log_path(session_id)
    if not log_path or not log_path.is_file():
        return None

    try:
        with log_path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - SESSION_LOG_SCAN_BYTES))
            tail = handle.read().decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return None

    for line in reversed(tail.splitlines()):
        if " - WARNING - " not in line and " - ERROR - " not in line:
            continue
        try:
            timestamp_str, _, _, message = line.split(" - ", 3)
            log_time = datetime.strptime(timestamp_str.strip(), "%Y-%m-%d %H:%M:%S,%f").timestamp()
            if log_time + 1 < request_started_at_epoch:
                continue
            return f"[working] {message.strip()}"
        except Exception:  # noqa: BLE001
            continue

    return None


async def _stream_request(
    request,
    json_output: bool,
    stats_output: bool,
    workspace: Optional[str] = None,
    *,
    command_mode: str = "run",
    session_summary: Optional[Dict[str, Any]] = None,
) -> int:
    from app.cli.service import get_session_summary, run_request_stream

    _ensure_request_session_id(request)
    event_queue: asyncio.Queue = asyncio.Queue()

    async def _pump_stream_events() -> None:
        try:
            async for event in run_request_stream(request, workspace=workspace):
                await event_queue.put(("event", event))
        except Exception as exc:  # noqa: BLE001
            await event_queue.put(("error", exc))
        finally:
            await event_queue.put(("end", None))

    start_time = time.monotonic()
    request_started_at_epoch = time.time()
    stats = _empty_stats(request=request, workspace=workspace)
    render_state = _empty_render_state()
    last_event_time = time.monotonic()
    last_notice_time: Optional[float] = None
    last_issue_notice: Optional[str] = None
    producer_task = asyncio.create_task(_pump_stream_events())
    if json_output:
        _emit_json_session_event(
            request,
            workspace,
            command_mode=command_mode,
            session_summary=session_summary,
        )
        _emit_json_goal_event(
            request,
            command_mode=command_mode,
            source="session_start",
            session_summary=session_summary,
        )

    try:
        while True:
            try:
                item_type, payload = await asyncio.wait_for(event_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                now = time.monotonic()
                idle_seconds = now - last_event_time
                if idle_seconds >= STREAM_IDLE_NOTICE_SECONDS and (
                    last_notice_time is None or (now - last_notice_time) >= STREAM_IDLE_REPEAT_SECONDS
                ):
                    issue_notice = _extract_recent_session_issue_notice(
                        getattr(request, "session_id", None),
                        request_started_at_epoch=request_started_at_epoch,
                    )
                    notice = None
                    if issue_notice and issue_notice != last_issue_notice:
                        notice = issue_notice
                    elif not issue_notice:
                        notice = _build_stream_idle_notice_for_state(render_state, idle_seconds)

                    if json_output:
                        if notice:
                            _emit_json_notice_event(
                                session_id=getattr(request, "session_id", None),
                                command_mode=command_mode,
                                level="info",
                                content=notice,
                                source="idle_poll",
                            )
                    elif issue_notice and issue_notice != last_issue_notice:
                        sys.stderr.write(f"\n{issue_notice}\n")
                        sys.stderr.flush()
                    elif not issue_notice:
                        _emit_stream_idle_notice_for_state(render_state, idle_seconds)
                    last_notice_time = now
                    if issue_notice:
                        last_issue_notice = issue_notice
                continue

            if item_type == "end":
                break
            if item_type == "error":
                raise payload

            event = payload

            last_event_time = time.monotonic()
            last_notice_time = None
            previous_phase = stats.get("_active_phase")
            previous_tool_steps = _snapshot_tool_steps(stats)
            _record_stats_event(stats, event, start_time)
            if json_output:
                next_phase = stats.get("_active_phase")
                if isinstance(next_phase, str) and next_phase and next_phase != previous_phase:
                    print(
                        json.dumps(
                            {
                                "type": "cli_phase",
                                "phase": next_phase,
                            },
                            ensure_ascii=False,
                        )
                    )
                _emit_json_tool_events(previous_tool_steps, stats.get("tool_steps") or [])
                _emit_json_goal_event(
                    request,
                    command_mode=command_mode,
                    source=str(event.get("type") or "runtime"),
                    goal=event.get("goal") if isinstance(event.get("goal"), dict) else None,
                    goal_transition=(
                        event.get("goal_transition")
                        if isinstance(event.get("goal_transition"), dict)
                        else None
                    ),
                    goal_outcome=(
                        event.get("goal_outcome")
                        if isinstance(event.get("goal_outcome"), dict)
                        else None
                    ),
                    include_request_goal_overlay=False,
                )
                print(json.dumps(event, ensure_ascii=False))
            else:
                _print_plain_event(event, render_state)
    finally:
        if not producer_task.done():
            producer_task.cancel()
        with suppress(asyncio.CancelledError):
            await producer_task
    if json_output:
        refreshed_summary = None
        try:
            refreshed_summary = await get_session_summary(
                session_id=request.session_id,
                user_id=getattr(request, "user_id", None),
            )
        except Exception:  # noqa: BLE001
            refreshed_summary = None
        if refreshed_summary:
            _emit_json_session_event(
                request,
                workspace,
                command_mode=command_mode,
                session_summary=refreshed_summary,
                include_request_goal_overlay=False,
            )
            _emit_json_goal_event(
                request,
                command_mode=command_mode,
                source="session_refresh",
                session_summary=refreshed_summary,
                include_request_goal_overlay=False,
            )
    stats["elapsed_seconds"] = round(time.monotonic() - start_time, 3)
    _finalize_stats(stats)
    if stats_output:
        _print_stats(stats, json_output=json_output)
    return 0
