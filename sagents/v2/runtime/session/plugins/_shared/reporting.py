"""Read a bounded cohort from canonical SQL Run locations, metadata and events."""

from datetime import datetime

from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.session.run_metadata import RunMetadata
from sagents.v2.runtime.session.reporting import (
    REPORT_EVENTS, TOKEN_FIELDS, BusinessReplay, RunBusinessFacts, run_id_range,
)


async def replay_sql(store, *, start, end, agent_id, max_runs, max_events, exclude_sessions):
    usage_fields = ("reported", *TOKEN_FIELDS)
    if store.json_type == "JSONB":
        from ..postgres.metadata import postgres_metadata_cte as metadata_cte

        event_type = "event->>'type'"
        tool_id = "event#>>'{data,tool_call_id}'"
        operation_id = "event#>>'{data,operation_id}'"
        step_id = "event->>'step_id'"
        usage = ", ".join(f"event#>>'{{data,usage,{field}}}'" for field in usage_fields)
    else:
        from ..mysql.run_metadata import mysql_metadata_cte as metadata_cte

        event_type = "JSON_UNQUOTE(JSON_EXTRACT(event,'$.type'))"
        tool_id = "NULLIF(JSON_UNQUOTE(JSON_EXTRACT(event,'$.data.tool_call_id')),'null')"
        operation_id = "NULLIF(JSON_UNQUOTE(JSON_EXTRACT(event,'$.data.operation_id')),'null')"
        step_id = "NULLIF(JSON_UNQUOTE(JSON_EXTRACT(event,'$.step_id')),'null')"
        usage = ", ".join(
            f"JSON_UNQUOTE(JSON_EXTRACT(event,'$.data.usage.{field}'))" for field in usage_fields
        )

    report = BusinessReplay()
    remaining = max_events
    lower, upper = run_id_range(start, end)
    excluded = ""
    if exclude_sessions:
        marks = ",".join(["%s"] * len(exclude_sessions))
        excluded = f" AND session_id NOT IN ({marks})"
    async with store._reader_connection() as connection:
        await store._begin_snapshot(connection)
        async with connection.cursor() as cursor:
            await cursor.execute(
                f"""SELECT session_id, identity FROM {store._table('locations')}
                WHERE kind = 'run_id' AND identity >= %s AND identity < %s{excluded}
                ORDER BY identity DESC LIMIT %s""",
                (lower, upper, *exclude_sessions, max_runs + 1),
            )
            candidates = await cursor.fetchall()
            report.cohort_truncated = len(candidates) > max_runs
            candidates = candidates[:max_runs]
            for offset in range(0, len(candidates), 100):
                batch = candidates[offset : offset + 100]
                sessions = tuple(dict.fromkeys(sid for sid, _ in batch))
                ids = tuple(rid for _, rid in batch)
                marks = ",".join(["%s"] * len(sessions))
                run_marks = ",".join(["%s"] * len(ids))
                await cursor.execute(
                    metadata_cte(store._table, marks) + f"SELECT session_id,run_id,created_at,state,agent_id FROM metadata WHERE run_id IN ({run_marks})",
                    (*(sessions * 4), *ids),
                )
                selected = {}
                for sid, rid, created_at, state, owner_agent in await cursor.fetchall():
                    if agent_id and owner_agent != agent_id:
                        continue
                    metadata = RunMetadata(sid, rid, datetime.fromisoformat(created_at), RunState(state), owner_agent or "")
                    facts = RunBusinessFacts(metadata)
                    selected[rid] = facts
                    report.runs[sid, rid] = facts
                if not selected:
                    continue
                run_marks = ",".join(["%s"] * len(selected))
                type_marks = ",".join(["%s"] * len(REPORT_EVENTS))
                if remaining:
                    await cursor.execute(
                        f"""SELECT run_id,run_sequence,{event_type},{tool_id},{operation_id},{step_id},{usage}
                        FROM {store._table('run_events')}
                        WHERE run_id IN ({run_marks}) AND {event_type} IN ({type_marks})
                        ORDER BY run_id,run_sequence LIMIT %s""",
                        (*selected, *REPORT_EVENTS, remaining + 1),
                    )
                    rows = await cursor.fetchall()
                    if len(rows) <= remaining:
                        remaining -= len(rows)
                        for rid, sequence, kind, call, operation, step, reported, *tokens in rows:
                            usage_values = None
                            if kind == "usage.recorded":
                                usage_values = {"reported": reported == "true", **{
                                    field: int(value or 0) for field, value in zip(TOKEN_FIELDS, tokens)
                                }}
                            selected[rid].record(
                                sequence, kind, call, usage_values, operation_id=operation, step_id=step,
                            )
                        continue
                remaining = 0
                for facts in selected.values():
                    facts.events_complete = False
    return report
