import json
import sys
import time
from typing import Any, Dict, List, Optional

from app.cli.runtime.rendering import (
    _buffer_has_skill_io_markup,
    _collect_event_tool_names,
)


def _empty_stats(*, request, workspace: Optional[str]) -> Dict[str, Any]:
    return {
        "session_id": getattr(request, "session_id", None),
        "user_id": getattr(request, "user_id", None),
        "agent_id": getattr(request, "agent_id", None),
        "agent_mode": getattr(request, "agent_mode", None),
        "workspace": workspace,
        "requested_skills": list(getattr(request, "available_skills", None) or []),
        "max_loop_count": getattr(request, "max_loop_count", None),
        "elapsed_seconds": 0.0,
        "first_output_seconds": None,
        "tools": [],
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "per_step_info": [],
        "tool_steps": [],
        "phase_timings": [],
        "_active_tool_steps": {},
        "_next_tool_step": 1,
        "_tool_tag_buffer": "",
        "_phase_totals": {},
        "_phase_order": [],
        "_active_phase": None,
        "_active_phase_started_at": None,
        "_last_event_timestamp": None,
    }


def _record_stats_event(stats: Dict[str, Any], event: Dict[str, Any], start_time: float) -> None:
    def _event_timestamp() -> float:
        timestamp = event.get("timestamp")
        if isinstance(timestamp, (int, float)):
            return float(timestamp)
        return round(time.time(), 3)

    def _finalize_active_phase(until_timestamp: float) -> None:
        phase = stats.get("_active_phase")
        started_at = stats.get("_active_phase_started_at")
        if not phase or not isinstance(started_at, (int, float)):
            return

        totals = stats["_phase_totals"].setdefault(
            phase,
            {
                "phase": phase,
                "started_at": float(started_at),
                "finished_at": float(until_timestamp),
                "duration_ms": 0.0,
                "segment_count": 0,
            },
        )
        totals["started_at"] = min(float(totals.get("started_at") or started_at), float(started_at))
        totals["finished_at"] = max(
            float(totals.get("finished_at") or until_timestamp),
            float(until_timestamp),
        )
        totals["duration_ms"] = float(totals.get("duration_ms") or 0.0) + max(
            0.0,
            (float(until_timestamp) - float(started_at)) * 1000.0,
        )
        totals["segment_count"] = int(totals.get("segment_count") or 0) + 1
        stats["_active_phase"] = None
        stats["_active_phase_started_at"] = None

    def _start_phase(phase: str, timestamp: float) -> None:
        if stats.get("_active_phase") == phase:
            return
        _finalize_active_phase(timestamp)
        stats["_active_phase"] = phase
        stats["_active_phase_started_at"] = timestamp
        if phase not in stats["_phase_totals"]:
            stats["_phase_totals"][phase] = {
                "phase": phase,
                "started_at": timestamp,
                "finished_at": timestamp,
                "duration_ms": 0.0,
                "segment_count": 0,
            }
            stats["_phase_order"].append(phase)

    def _start_tool_step(tool_name: str, tool_call_id: Optional[str]) -> None:
        key = tool_call_id or f"synthetic:{tool_name}:{stats['_next_tool_step']}"
        if key in stats["_active_tool_steps"]:
            return
        step = {
            "step": stats["_next_tool_step"],
            "tool_name": tool_name or "unknown",
            "tool_call_id": tool_call_id,
            "status": "running",
            "started_at": _event_timestamp(),
            "finished_at": None,
            "duration_ms": None,
        }
        stats["_next_tool_step"] += 1
        stats["_active_tool_steps"][key] = step
        stats["tool_steps"].append(step)

    def _finish_tool_step(tool_call_id: Optional[str], tool_name: Optional[str]) -> None:
        key = tool_call_id or ""
        step = stats["_active_tool_steps"].get(key) if key else None
        if step is None and tool_name:
            for candidate in reversed(stats["tool_steps"]):
                if candidate.get("tool_name") == tool_name and candidate.get("status") == "running":
                    step = candidate
                    break
        if step is None:
            _start_tool_step(tool_name or "unknown", tool_call_id)
            step = stats["tool_steps"][-1]
        finished_at = _event_timestamp()
        step["status"] = "completed"
        step["finished_at"] = finished_at
        started_at = step.get("started_at")
        if isinstance(started_at, (int, float)):
            step["duration_ms"] = max(0.0, (finished_at - float(started_at)) * 1000.0)
        if key:
            stats["_active_tool_steps"].pop(key, None)

    def _event_phase(tool_names: List[str]) -> Optional[str]:
        event_type = str(event.get("type") or "").strip()
        role = str(event.get("role") or "").strip()
        content = event.get("content")

        if event_type in {"token_usage", "stream_end", "start", "done", "cli_stats"}:
            return None
        if event_type in {
            "thinking",
            "reasoning_content",
            "task_analysis",
            "analysis",
            "plan",
            "observation",
        }:
            return "planning"
        if event_type in {"tool_call", "tool_result"} or role == "tool" or tool_names:
            return "tool"
        if (
            content
            and isinstance(content, str)
            and (
                event_type in {"text", "assistant", "message", "do_subtask_result"}
                or role in {"assistant", "agent"}
            )
        ):
            return "assistant_text"
        if event_type in {"error", "cli_error"}:
            return "error"
        return None

    event_timestamp = _event_timestamp()
    stats["_last_event_timestamp"] = event_timestamp

    session_id = event.get("session_id")
    if session_id and not stats["session_id"]:
        stats["session_id"] = session_id

    has_visible_output = False
    content = event.get("content")
    if isinstance(content, str) and content:
        has_visible_output = True
        buffer = (stats.get("_tool_tag_buffer") or "") + content
        stats["_tool_tag_buffer"] = buffer[-2048:]

    tool_names = _collect_event_tool_names(event, content_buffer=stats.get("_tool_tag_buffer") or "")
    if tool_names:
        has_visible_output = True
        existing_tool_names = set(stats["tools"])
        existing_tool_names.update(tool_names)
        stats["tools"] = sorted(existing_tool_names)
    elif stats.get("_tool_tag_buffer"):
        if _buffer_has_skill_io_markup(stats["_tool_tag_buffer"]):
            has_visible_output = True

    if event.get("type") == "error":
        has_visible_output = True

    if has_visible_output and stats["first_output_seconds"] is None:
        stats["first_output_seconds"] = round(time.monotonic() - start_time, 3)

    phase = _event_phase(tool_names)
    if phase:
        _start_phase(phase, event_timestamp)

    if event.get("type") == "tool_call":
        for tool_call in event.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function") or {}
            tool_name = function.get("name")
            tool_call_id = tool_call.get("id")
            if isinstance(tool_name, str) and tool_name.strip():
                _start_tool_step(tool_name.strip(), str(tool_call_id).strip() or None)

    event_type = event.get("type")
    role = event.get("role")
    if event_type == "tool_result" or role == "tool":
        tool_call_id = event.get("tool_call_id")
        tool_name = None
        metadata = event.get("metadata") or {}
        if isinstance(metadata.get("tool_name"), str):
            tool_name = metadata.get("tool_name")
        if not tool_name and isinstance(event.get("tool_name"), str):
            tool_name = event.get("tool_name")
        _finish_tool_step(
            str(tool_call_id).strip() or None if tool_call_id else None,
            str(tool_name).strip() if isinstance(tool_name, str) and tool_name.strip() else None,
        )

    if event.get("type") == "token_usage":
        metadata = event.get("metadata") or {}
        token_usage = metadata.get("token_usage") or {}
        total_info = token_usage.get("total_info") or {}
        stats["prompt_tokens"] = total_info.get("prompt_tokens")
        stats["completion_tokens"] = total_info.get("completion_tokens")
        stats["total_tokens"] = total_info.get("total_tokens")
        stats["per_step_info"] = token_usage.get("per_step_info") or []
        tool_steps = metadata.get("tool_steps") or []
        if isinstance(tool_steps, list) and tool_steps:
            stats["tool_steps"] = tool_steps
        phase_timings = metadata.get("phase_timings") or []
        if isinstance(phase_timings, list) and phase_timings:
            stats["phase_timings"] = phase_timings


def _finalize_stats(stats: Dict[str, Any], finished_at: Optional[float] = None) -> None:
    active_phase = stats.get("_active_phase")
    active_started_at = stats.get("_active_phase_started_at")
    if active_phase and isinstance(active_started_at, (int, float)):
        last_event_timestamp = stats.get("_last_event_timestamp")
        end_timestamp = finished_at
        if not isinstance(end_timestamp, (int, float)):
            end_timestamp = last_event_timestamp
        if isinstance(end_timestamp, (int, float)):
            totals = stats["_phase_totals"].setdefault(
                active_phase,
                {
                    "phase": active_phase,
                    "started_at": float(active_started_at),
                    "finished_at": float(end_timestamp),
                    "duration_ms": 0.0,
                    "segment_count": 0,
                },
            )
            totals["started_at"] = min(
                float(totals.get("started_at") or active_started_at),
                float(active_started_at),
            )
            totals["finished_at"] = max(
                float(totals.get("finished_at") or end_timestamp),
                float(end_timestamp),
            )
            totals["duration_ms"] = float(totals.get("duration_ms") or 0.0) + max(
                0.0,
                (float(end_timestamp) - float(active_started_at)) * 1000.0,
            )
            totals["segment_count"] = int(totals.get("segment_count") or 0) + 1
            stats["_active_phase"] = None
            stats["_active_phase_started_at"] = None

    if not stats.get("phase_timings"):
        stats["phase_timings"] = [
            stats["_phase_totals"][phase]
            for phase in stats.get("_phase_order") or []
            if phase in stats["_phase_totals"]
        ]


def _print_stats(stats: Dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(
            json.dumps(
                {
                    "type": "cli_stats",
                    "session_id": stats.get("session_id"),
                    "user_id": stats.get("user_id"),
                    "agent_id": stats.get("agent_id"),
                    "agent_mode": stats.get("agent_mode"),
                    "workspace": stats.get("workspace"),
                    "requested_skills": stats.get("requested_skills") or [],
                    "max_loop_count": stats.get("max_loop_count"),
                    "elapsed_seconds": stats.get("elapsed_seconds"),
                    "first_output_seconds": stats.get("first_output_seconds"),
                    "tools": stats.get("tools") or [],
                    "prompt_tokens": stats.get("prompt_tokens"),
                    "completion_tokens": stats.get("completion_tokens"),
                    "total_tokens": stats.get("total_tokens"),
                    "per_step_info": stats.get("per_step_info") or [],
                    "tool_steps": stats.get("tool_steps") or [],
                    "phase_timings": stats.get("phase_timings") or [],
                },
                ensure_ascii=False,
            )
        )
        return

    output_lines = [
        "",
        "[stats]",
        f"session_id: {stats.get('session_id') or '(unknown)'}",
        f"user_id: {stats.get('user_id') or '(unknown)'}",
        f"agent_mode: {stats.get('agent_mode') or '(unknown)'}",
        f"elapsed_seconds: {stats.get('elapsed_seconds'):.3f}",
    ]
    if stats.get("agent_id"):
        output_lines.append(f"agent_id: {stats.get('agent_id')}")
    if stats.get("workspace"):
        output_lines.append(f"workspace: {stats.get('workspace')}")
    first_output = stats.get("first_output_seconds")
    if first_output is not None:
        output_lines.append(f"first_output_seconds: {first_output:.3f}")
    requested_skills = stats.get("requested_skills") or []
    output_lines.append(
        f"requested_skills: {', '.join(requested_skills) if requested_skills else '(none)'}"
    )
    if stats.get("max_loop_count") is not None:
        output_lines.append(f"max_loop_count: {stats.get('max_loop_count')}")

    tools = stats.get("tools") or []
    output_lines.append(f"tools: {', '.join(tools) if tools else '(none)'}")

    if stats.get("total_tokens") is not None:
        output_lines.append(
            "tokens: "
            f"prompt={stats.get('prompt_tokens')}, "
            f"completion={stats.get('completion_tokens')}, "
            f"total={stats.get('total_tokens')}"
        )

    per_step_info = stats.get("per_step_info") or []
    if per_step_info:
        output_lines.append("per_step_usage:")
        for step in per_step_info:
            step_name = step.get("step_name", "unknown")
            usage = step.get("usage") or {}
            output_lines.append(
                "  - "
                f"{step_name}: prompt={usage.get('prompt_tokens')}, "
                f"completion={usage.get('completion_tokens')}, "
                f"total={usage.get('total_tokens')}"
            )

    tool_steps = stats.get("tool_steps") or []
    if tool_steps:
        output_lines.append("tool_steps:")
        for step in tool_steps:
            duration_ms = step.get("duration_ms")
            duration_text = (
                f"{duration_ms:.0f}ms"
                if isinstance(duration_ms, (int, float))
                else str(step.get("status") or "unknown")
            )
            output_lines.append(
                "  - "
                f"#{step.get('step')} {step.get('tool_name')} ({duration_text})"
            )

    phase_timings = stats.get("phase_timings") or []
    if phase_timings:
        output_lines.append("phase_timings:")
        for phase in phase_timings:
            duration_ms = phase.get("duration_ms")
            duration_text = (
                f"{duration_ms:.0f}ms"
                if isinstance(duration_ms, (int, float))
                else "unknown"
            )
            output_lines.append(
                "  - "
                f"{phase.get('phase')} ({duration_text}, segments={phase.get('segment_count', 0)})"
            )

    sys.stdout.write("\n".join(output_lines) + "\n")
    sys.stdout.flush()


def _tool_step_event_key(step: Dict[str, Any]) -> str:
    tool_call_id = step.get("tool_call_id")
    if isinstance(tool_call_id, str) and tool_call_id.strip():
        return tool_call_id.strip()
    return f"step:{step.get('step')}"


def _snapshot_tool_steps(stats: Dict[str, Any]) -> Dict[str, str]:
    snapshot: Dict[str, str] = {}
    for step in stats.get("tool_steps") or []:
        if not isinstance(step, dict):
            continue
        snapshot[_tool_step_event_key(step)] = str(step.get("status") or "")
    return snapshot

