import asyncio
import json
import time
from contextlib import suppress
from typing import Any, Dict, Optional

from app.cli.runtime.contracts import (
    _emit_json_session_event,
    _emit_json_tool_events,
    _ensure_request_session_id,
)
from app.cli.runtime.rendering import (
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


async def _stream_request(
    request,
    json_output: bool,
    stats_output: bool,
    workspace: Optional[str] = None,
    *,
    command_mode: str = "run",
    session_summary: Optional[Dict[str, Any]] = None,
) -> int:
    from app.cli.service import run_request_stream

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
    stats = _empty_stats(request=request, workspace=workspace)
    render_state = _empty_render_state()
    last_event_time = time.monotonic()
    last_notice_time: Optional[float] = None
    producer_task = asyncio.create_task(_pump_stream_events())
    if json_output:
        _emit_json_session_event(
            request,
            workspace,
            command_mode=command_mode,
            session_summary=session_summary,
        )

    try:
        while True:
            try:
                item_type, payload = await asyncio.wait_for(event_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if not json_output:
                    now = time.monotonic()
                    idle_seconds = now - last_event_time
                    if idle_seconds >= STREAM_IDLE_NOTICE_SECONDS and (
                        last_notice_time is None or (now - last_notice_time) >= STREAM_IDLE_REPEAT_SECONDS
                    ):
                        _emit_stream_idle_notice_for_state(render_state, idle_seconds)
                        last_notice_time = now
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
                print(json.dumps(event, ensure_ascii=False))
            else:
                _print_plain_event(event, render_state)
    finally:
        if not producer_task.done():
            producer_task.cancel()
        with suppress(asyncio.CancelledError):
            await producer_task
    stats["elapsed_seconds"] = round(time.monotonic() - start_time, 3)
    _finalize_stats(stats)
    if stats_output:
        _print_stats(stats, json_output=json_output)
    return 0

