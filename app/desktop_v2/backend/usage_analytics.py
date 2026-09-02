from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.model.usage import canonical_token_usage, has_token_usage


async def build_usage_overview(
    self,
    user_id: str,
    *,
    days: int = 30,
    timezone_offset_minutes: int = 0,
) -> dict[str, Any]:
    """Aggregate local Desktop usage without making diagnostics authoritative."""

    if days < 1 or days > 365:
        raise ValueError("days must be between 1 and 365")
    if timezone_offset_minutes < -840 or timezone_offset_minutes > 840:
        raise ValueError("timezone_offset_minutes must be between -840 and 840")

    await self._initialize_user(user_id)
    local_timezone = timezone(timedelta(minutes=timezone_offset_minutes))
    now = utc_now()
    today = now.astimezone(local_timezone).date()
    first_day = today - timedelta(days=days - 1)
    cutoff = datetime.combine(
        first_day, time.min, tzinfo=local_timezone
    ).astimezone(timezone.utc)
    day_keys = [
        (first_day + timedelta(days=offset)).isoformat() for offset in range(days)
    ]
    daily = {
        key: {
            "date": key,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "turns": 0,
            "tool_calls": 0,
        }
        for key in day_keys
    }
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "model_requests": 0,
        "failed_model_requests": 0,
        "turns": 0,
        "tool_calls": 0,
        "sessions": 0,
    }
    models: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "name": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "requests": 0,
        }
    )
    agents: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "id": "",
            "name": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "requests": 0,
            "turns": 0,
            "tool_calls": 0,
        }
    )
    tools: Counter[str] = Counter()
    active_sessions: set[str] = set()
    first_token_latency_total_ms = 0.0
    first_token_latency_samples = 0
    first_token_latencies_ms: list[float] = []
    output_generation_total_ms = 0.0
    output_token_intervals = 0
    output_token_rates: list[float] = []
    skipped_event_sessions: set[str] = set()
    skipped_diagnostic_sessions: set[str] = set()

    agent_records = await self.catalog.list_agents(user_id)
    agent_names = {value.agent_id: value.name for value in agent_records}
    indexed_sessions = await self._authorized_indexed_sessions(user_id)

    for session in indexed_sessions:
        session_id = session.session_id
        runs = ()
        events = ()
        requests = ()
        # Runtime events and model diagnostics are independent best-effort
        # projections. Failure in one source must not discard valid data
        # already persisted by the other source.
        try:
            runs = await self.session_store.list_session_runs(session_id)
        except (OSError, ValueError, SageV2Error) as error:
            skipped_event_sessions.add(session_id)
            self.logger.warning(
                "usage.runs_skipped",
                "Skipped unreadable Runs while aggregating usage",
                attributes={
                    "session_id": session_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
        try:
            events = await self.session_store.read_session_events(session_id)
        except (OSError, ValueError, SageV2Error) as error:
            skipped_event_sessions.add(session_id)
            self.logger.warning(
                "usage.events_skipped",
                "Skipped unreadable events while aggregating usage",
                attributes={
                    "session_id": session_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
        try:
            requests = await self.diagnostics.list_model_requests(
                session_id=session_id
            )
        except (OSError, ValueError, SageV2Error) as error:
            skipped_diagnostic_sessions.add(session_id)
            self.logger.warning(
                "usage.diagnostics_skipped",
                "Skipped unreadable model diagnostics while aggregating usage",
                attributes={
                    "session_id": session_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )

        run_agents: dict[str, str] = {}
        for run in runs:
            try:
                command = await self.session_store.get_start_command(run.run_id)
                run_agents[run.run_id] = command.agent_id
            except (OSError, ValueError, SageV2Error):
                continue

        for record in requests:
            occurred_at = _usage_record_time(record)
            if occurred_at is None or occurred_at < cutoff:
                continue
            day_key = occurred_at.astimezone(local_timezone).date().isoformat()
            if day_key not in daily:
                continue
            active_sessions.add(session_id)
            totals["model_requests"] += 1
            if record.get("status") == "failed":
                totals["failed_model_requests"] += 1

            response = record.get("response")
            usage = response.get("usage") if isinstance(response, dict) else None
            usage = usage if isinstance(usage, dict) else {}
            (
                input_tokens,
                output_tokens,
                cached_tokens,
                reasoning_tokens,
            ) = _canonical_diagnostic_usage(usage)
            total_tokens = input_tokens + output_tokens
            values = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_input_tokens": cached_tokens,
                "reasoning_tokens": reasoning_tokens,
                "total_tokens": total_tokens,
            }
            for key, value in values.items():
                totals[key] += value
                daily[day_key][key] += value

            first_token_latency_ms, generation_ms, token_intervals = (
                _usage_latency_observation(record, output_tokens=output_tokens)
            )
            if first_token_latency_ms is not None:
                first_token_latency_total_ms += first_token_latency_ms
                first_token_latency_samples += 1
                first_token_latencies_ms.append(first_token_latency_ms)
            if generation_ms is not None and token_intervals > 0:
                output_generation_total_ms += generation_ms
                output_token_intervals += token_intervals
                if generation_ms > 0:
                    output_token_rates.append(
                        token_intervals * 1000 / generation_ms
                    )

            # Diagnostics v2 keeps provider/routing details in one compact
            # metadata object. Retain the v1 provider fallback so existing
            # request files continue to contribute to local usage reports.
            metadata = record.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            provider = record.get("provider")
            provider = provider if isinstance(provider, dict) else {}
            request = record.get("request")
            request = request if isinstance(request, dict) else {}
            raw_models = usage.get("models")
            model_name = (
                str(raw_models[0])
                if isinstance(raw_models, list) and raw_models
                else str(
                    request.get("model")
                    or metadata.get("model")
                    or provider.get("model")
                    or request.get("model_binding")
                    or metadata.get("model_binding")
                    or "Unknown"
                )
            )
            model_value = models[model_name]
            model_value["name"] = model_name
            model_value["requests"] += 1
            for key, value in values.items():
                model_value[key] += value

            run_id = str(record.get("run_id") or "")
            agent_id = str(
                metadata.get("agent_id")
                or provider.get("agent_id")
                or run_agents.get(run_id)
                or "unknown"
            )
            agent_value = agents[agent_id]
            agent_value["id"] = agent_id
            agent_value["name"] = agent_names.get(agent_id, agent_id)
            agent_value["requests"] += 1
            for key, value in values.items():
                agent_value[key] += value

        for event in events:
            if event.occurred_at < cutoff:
                continue
            day_key = (
                event.occurred_at.astimezone(local_timezone).date().isoformat()
            )
            if day_key not in daily:
                continue
            agent_id = run_agents.get(event.run_id, "unknown")
            agent_value = agents[agent_id]
            agent_value["id"] = agent_id
            agent_value["name"] = agent_names.get(agent_id, agent_id)
            if event.type == "turn.started":
                active_sessions.add(session_id)
                totals["turns"] += 1
                daily[day_key]["turns"] += 1
                agent_value["turns"] += 1
            elif event.type == "tool.call.proposed":
                active_sessions.add(session_id)
                totals["tool_calls"] += 1
                daily[day_key]["tool_calls"] += 1
                agent_value["tool_calls"] += 1
                tool_name = str(getattr(event.data, "tool_name", "unknown"))
                tools[tool_name] += 1

    totals["sessions"] = len(active_sessions)
    totals["average_first_token_latency_ms"] = (
        round(first_token_latency_total_ms / first_token_latency_samples, 2)
        if first_token_latency_samples
        else None
    )
    totals["first_token_latency_p50_ms"] = _usage_percentile(
        first_token_latencies_ms, 0.50
    )
    totals["first_token_latency_p95_ms"] = _usage_percentile(
        first_token_latencies_ms, 0.95
    )
    totals["first_token_latency_samples"] = len(first_token_latencies_ms)
    totals["output_tokens_per_second"] = (
        round(output_token_intervals * 1000 / output_generation_total_ms, 2)
        if output_generation_total_ms > 0
        else None
    )
    totals["output_tokens_per_second_p50"] = _usage_percentile(
        output_token_rates, 0.50
    )
    totals["output_tokens_per_second_p95"] = _usage_percentile(
        output_token_rates, 0.95
    )
    totals["output_tokens_per_second_samples"] = len(output_token_rates)
    skipped_sessions = skipped_event_sessions | skipped_diagnostic_sessions
    return {
        "range_days": days,
        "generated_at": now.isoformat(),
        "data_quality": {
            "partial": bool(skipped_sessions),
            "skipped_sessions": len(skipped_sessions),
            "skipped_event_sessions": len(skipped_event_sessions),
            "skipped_diagnostic_sessions": len(skipped_diagnostic_sessions),
        },
        "totals": totals,
        "daily": list(daily.values()),
        "models": sorted(
            models.values(),
            key=lambda value: (-value["total_tokens"], value["name"]),
        ),
        "agents": sorted(
            agents.values(),
            key=lambda value: (-value["total_tokens"], value["name"]),
        ),
        "tools": [
            {"name": name, "count": count}
            for name, count in sorted(
                tools.items(), key=lambda item: (-item[1], item[0])
            )
        ],
    }


def _usage_record_time(record: dict[str, Any]) -> datetime | None:
    return _usage_timestamp(record.get("completed_at") or record.get("started_at"))


def _canonical_diagnostic_usage(
    usage: dict[str, Any],
) -> tuple[int, int, int, int]:
    """Read new canonical records and repair legacy provider-shaped records."""

    provider_usage = usage.get("provider_usage")
    if isinstance(provider_usage, dict) and has_token_usage(provider_usage):
        canonical = canonical_token_usage(provider_usage, input_mode="auto")
        return (
            canonical.input_tokens,
            canonical.output_tokens,
            canonical.cached_input_tokens,
            canonical.reasoning_tokens,
        )
    return (
        _safe_nonnegative_int(usage.get("input_tokens")),
        _safe_nonnegative_int(usage.get("output_tokens")),
        _safe_nonnegative_int(usage.get("cached_input_tokens")),
        _safe_nonnegative_int(usage.get("reasoning_tokens")),
    )


def _usage_percentile(samples: list[float], percentile: float) -> float | None:
    """Return a linearly interpolated percentile for one usage sample series."""

    if not samples:
        return None
    ordered = sorted(samples)
    position = (len(ordered) - 1) * min(1.0, max(0.0, percentile))
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * fraction
    return round(value, 2)


def _usage_latency_observation(
    record: dict[str, Any], *, output_tokens: int
) -> tuple[float | None, float | None, int]:
    started_at = _usage_timestamp(record.get("started_at"))
    first_token_at = _usage_timestamp(record.get("first_token_at"))
    completed_at = _usage_timestamp(record.get("completed_at"))

    first_token_latency_ms: float | None = None
    if isinstance(record.get("ttfb_ms"), (int, float)) and record["ttfb_ms"] >= 0:
        first_token_latency_ms = float(record["ttfb_ms"])
    elif started_at is not None and first_token_at is not None:
        seconds = (first_token_at - started_at).total_seconds()
        if seconds >= 0:
            first_token_latency_ms = seconds * 1000
    elif isinstance(record.get("ttfb_sec"), (int, float)):
        seconds = float(record["ttfb_sec"])
        if seconds >= 0:
            first_token_latency_ms = seconds * 1000

    token_intervals = max(0, output_tokens - 1)
    generation_ms: float | None = None
    if token_intervals > 0:
        if (
            isinstance(record.get("duration_ms"), (int, float))
            and first_token_latency_ms is not None
        ):
            seconds = (float(record["duration_ms"]) - first_token_latency_ms) / 1000
            if seconds >= 0:
                generation_ms = seconds * 1000
        elif first_token_at is not None and completed_at is not None:
            seconds = (completed_at - first_token_at).total_seconds()
            if seconds >= 0:
                generation_ms = seconds * 1000
        elif first_token_latency_ms is not None and isinstance(
            record.get("duration_sec"), (int, float)
        ):
            seconds = float(record["duration_sec"]) - (first_token_latency_ms / 1000)
            if seconds >= 0:
                generation_ms = seconds * 1000
    return first_token_latency_ms, generation_ms, token_intervals


def _usage_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _start_run_user_text(command: StartRun) -> str:
    values: list[str] = []
    for item in command.input:
        if item.role != "user":
            continue
        for block in item.content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text.strip():
                values.append(text.strip())
    return "\n".join(values)


def _safe_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
