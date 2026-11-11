"""SQLite timing indexes, projection, query and explicit backfill."""

from __future__ import annotations

from collections import defaultdict
from contextlib import closing
import sqlite3

from ...performance.aggregation import EVENTS, build_run, timestamp, timing_report
from ...performance.projection import log_timings, model_timing

SCHEMA = """
CREATE TABLE IF NOT EXISTS performance_events (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT NOT NULL,
 event TEXT NOT NULL, at REAL NOT NULL, agent_id TEXT, identity TEXT, purpose TEXT,
 started_at REAL, turn_id TEXT, state TEXT);
CREATE INDEX IF NOT EXISTS performance_events_time ON performance_events(event,at);
CREATE INDEX IF NOT EXISTS performance_events_entry ON performance_events(event,started_at);
CREATE INDEX IF NOT EXISTS performance_events_run ON performance_events(run_id,at);
CREATE TABLE IF NOT EXISTS performance_models (
 run_id TEXT NOT NULL, request_id TEXT NOT NULL, session_id TEXT NOT NULL,
 started_at REAL, ended_at REAL, first_token_at REAL, purpose TEXT, turn_id TEXT,
 PRIMARY KEY(run_id,request_id));
CREATE INDEX IF NOT EXISTS performance_models_run ON performance_models(run_id,started_at);
"""


def project_log(db, row):
    for timing in log_timings(row):
        db.execute(
            """INSERT OR IGNORE INTO performance_events
            VALUES(:id,:session_id,:run_id,:event,:at,:agent_id,:identity,:purpose,:started_at,:turn_id,:state)""",
            timing,
        )


def project_model(db, row):
    db.execute(
        """INSERT OR REPLACE INTO performance_models
        VALUES(:run_id,:request_id,:session_id,:started_at,:ended_at,:first_token_at,:purpose,:turn_id)""",
        model_timing(row),
    )


def backfill(path):
    """Explicit maintenance operation; reads only allowlisted timing fields."""
    with closing(sqlite3.connect(path, timeout=15)) as db, db:
        db.executescript(SCHEMA)
        names = ",".join("?" for _ in EVENTS)
        rows = db.execute(
            f"""SELECT session_id,run_id,json_extract(payload,'$.timestamp'),
          json_extract(payload,'$.event'),json_extract(payload,'$.tool_call_id'),json_extract(payload,'$.request_id'),
          json_extract(payload,'$.turn_id'),json_extract(payload,'$.attributes.agent_id'),
          json_extract(payload,'$.attributes.purpose'),json_extract(payload,'$.attributes.started_at'),
          json_extract(payload,'$.attributes.first_text_ms'),json_extract(payload,'$.attributes.first_text_at'),
          json_extract(payload,'$.attributes.duration_ms'),
          json_extract(payload,'$.attributes.run_state')
          FROM logs WHERE json_extract(payload,'$.event') IN ({names})""",
            tuple(EVENTS),
        )
        count = 0
        for (
            sid,
            rid,
            at,
            event,
            call,
            request,
            turn,
            agent,
            purpose,
            start,
            first,
            first_at,
            duration,
            state,
        ) in rows:
            project_log(
                db,
                dict(
                    session_id=sid,
                    run_id=rid,
                    timestamp=at,
                    event=event,
                    tool_call_id=call,
                    request_id=request,
                    turn_id=turn,
                    attributes=dict(
                        agent_id=agent,
                        purpose=purpose,
                        started_at=start,
                        first_text_ms=first,
                        first_text_at=first_at,
                        duration_ms=duration,
                        run_state=state,
                    ),
                ),
            )
            count += 1
        rows = db.execute("""SELECT session_id,run_id,request_id,json_extract(payload,'$.started_at'),
          json_extract(payload,'$.completed_at'),json_extract(payload,'$.first_token_at'),
          json_extract(payload,'$.purpose'),json_extract(payload,'$.turn_id') FROM models""")
        models = 0
        for row in rows:
            project_model(
                db,
                dict(
                    zip(
                        (
                            "session_id",
                            "run_id",
                            "request_id",
                            "started_at",
                            "completed_at",
                            "first_token_at",
                            "purpose",
                            "turn_id",
                        ),
                        row,
                    )
                ),
            )
            models += 1
        return {"events": count, "models": models}


def run_timing(path, *, session_id, run_id):
    scope = (run_id, session_id)
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        events = [dict(row) for row in db.execute(
            "SELECT * FROM performance_events WHERE run_id=? AND session_id=? LIMIT 10001",
            scope,
        )]
        if not events or len(events) > 10000:
            return None
        models = [dict(row) for row in db.execute(
            "SELECT * FROM performance_models WHERE run_id=? AND session_id=? LIMIT 10001",
            scope,
        )]
    return build_run(events, models, include_timeline=True) if len(models) <= 10000 else None


def report(
    path,
    *,
    start,
    end,
    agent_id="",
    bucket="hour",
    timezone_name="Asia/Shanghai",
    max_runs=10000,
    max_timing_rows=100000,
):
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        candidates = list(
            db.execute(
                """SELECT run_id, MIN(CASE WHEN event='server.run.performance.accepted' THEN started_at ELSE at END) AS cohort FROM performance_events
            WHERE ((event='agent.run.started' AND at>=? AND at<?)
            OR (event='server.run.performance.accepted' AND started_at>=? AND started_at<?))
            AND (?='' OR agent_id=?)
            GROUP BY run_id ORDER BY cohort DESC LIMIT ?""",
                (start, end, start, end, agent_id, agent_id, max_runs + 1),
            )
        )
        truncated = len(candidates) > max_runs
        ids = [r["run_id"] for r in candidates[:max_runs]]
        events = defaultdict(list)
        models = defaultdict(list)
        timing_rows = 0
        for offset in range(0, len(ids), 400):
            batch = ids[offset : offset + 400]
            placeholders = ",".join("?" for _ in batch)
            batch_size = sum(
                db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE run_id IN ({placeholders})",
                    batch,
                ).fetchone()[0]
                for table in ("performance_events", "performance_models")
            )
            if timing_rows + batch_size > max_timing_rows:
                truncated = True
                break
            timing_rows += batch_size
            for r in db.execute(
                f"SELECT * FROM performance_events WHERE run_id IN ({placeholders})",
                batch,
            ):
                events[r["run_id"]].append(dict(r))
            for r in db.execute(
                f"SELECT * FROM performance_models WHERE run_id IN ({placeholders})",
                batch,
            ):
                models[r["run_id"]].append(dict(r))
    return timing_report(
        events,
        models,
        start=start,
        end=end,
        agent_id=agent_id,
        bucket=bucket,
        timezone_name=timezone_name,
        truncated=truncated,
    )


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Backfill content-free timing metadata from existing diagnostic records"
    )
    parser.add_argument(
        "--backfill", required=True, help="Existing evidence.sqlite3 path"
    )
    options = parser.parse_args()
    print(json.dumps(backfill(options.backfill)))
