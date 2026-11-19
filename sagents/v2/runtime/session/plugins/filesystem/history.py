"""Rebuildable, revision-stamped reads over committed filesystem Sessions."""

from __future__ import annotations

import json
import posixpath
import sqlite3
import tempfile
from pathlib import Path
from contextlib import closing, contextmanager

from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.principals import ActorRef
from sagents.v2.contracts.run_state import RunSnapshot, SessionSnapshot
from sagents.v2.runtime.session.plugins.filesystem.metadata import (
    read_filesystem_metadata,
)
from sagents.v2.runtime.session.metadata_replay import project_metadata_state
from sagents.v2.runtime.session.run_metadata import metadata_from_payload
from sagents.v2.runtime.session.contracts import (
    SessionEventPage,
    SessionHistoryMetadata,
    SessionToolActivity,
)

HISTORY_FILENAME = "history-v2.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS head (id INTEGER PRIMARY KEY CHECK (id = 1),
    fingerprint TEXT NOT NULL, session TEXT NOT NULL, owner TEXT, runs TEXT NOT NULL,
    run_metadata TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calls (
    run_id TEXT NOT NULL, call_id TEXT NOT NULL, tool_name TEXT NOT NULL,
    state TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (run_id, call_id));
CREATE TABLE IF NOT EXISTS paths (
    run_id TEXT NOT NULL, call_id TEXT NOT NULL, path TEXT NOT NULL,
    PRIMARY KEY (run_id, call_id, path));
CREATE INDEX IF NOT EXISTS calls_by_tool ON calls (tool_name, sequence DESC);
CREATE INDEX IF NOT EXISTS paths_by_path ON paths (path, run_id, call_id);
"""
_PATH_KEYS = (
    "path",
    "file_path",
    "source_path",
    "target_path",
    "destination_path",
    "old_path",
    "new_path",
    "timeline_path",
    "timeline_config_path",
)


def _encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _paths(arguments):
    for key in _PATH_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            yield posixpath.normpath(value.replace("\\", "/"))
    operations = arguments.get("operations")
    if isinstance(operations, (list, tuple)):
        for edit in operations:
            if isinstance(edit, dict):
                yield from _paths(edit)


def _event_rows(groups):
    for events in groups.values():
        for event in events:
            if event.get("session_sequence") is not None:
                yield event


def _write_activity(db, event):
    data = event["data"]
    if data.get("kind") != "tool" or not event["type"].startswith("tool.call."):
        return
    run_id, call_id = event["run_id"], data["tool_call_id"]
    db.execute(
        """INSERT INTO calls VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (run_id, call_id) DO UPDATE SET state=excluded.state,
        sequence=excluded.sequence, tool_name=excluded.tool_name
        WHERE excluded.sequence > calls.sequence""",
        (
            run_id,
            call_id,
            data["tool_name"],
            event["type"].removeprefix("tool.call."),
            event["session_sequence"],
        ),
    )
    arguments = data.get("arguments")
    if isinstance(arguments, dict):
        db.executemany(
            "INSERT OR IGNORE INTO paths VALUES (?, ?, ?)",
            ((run_id, call_id, path) for path in _paths(arguments)),
        )


def _path(directory):
    return directory / HISTORY_FILENAME


def publish(directory, state, fingerprint, *, appends=None, previous_fingerprint=None):
    _publish(_path(directory), state, fingerprint, appends, previous_fingerprint)


def _publish(path, state, fingerprint, appends, previous_fingerprint):
    with closing(sqlite3.connect(path)) as db:
        db.executescript(_SCHEMA)
        with db:
            head = db.execute("SELECT fingerprint FROM head WHERE id=1").fetchone()
            rebuilding = appends is None or head != (_encode(previous_fingerprint),)
            if rebuilding:
                appends = state.get("run_events", {})
                for table in ("events", "calls", "paths"):
                    db.execute(f"DELETE FROM {table}")
            previous_sequence = db.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM events"
            ).fetchone()[0]
            appended = 0
            row = state["sessions"][0]
            run_ids = {run["run_id"] for run in state["runs"]}
            for event in _event_rows(appends):
                if (
                    event["session_id"] != row["session_id"]
                    or event["run_id"] not in run_ids
                ):
                    raise ValueError(
                        "Session history contains an event for another aggregate"
                    )
                if not rebuilding and event["session_sequence"] <= previous_sequence:
                    raise ValueError(
                        "Session history append overlaps the committed head"
                    )
                db.execute(
                    "INSERT INTO events VALUES (?, ?)",
                    (event["session_sequence"], _encode(event)),
                )
                _write_activity(db, event)
                appended += 1
            head_sequence = row["last_sequence"]
            maximum = db.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM events"
            ).fetchone()[0]
            if (
                maximum != head_sequence
                or appended != head_sequence - previous_sequence
            ):
                raise ValueError("Session history contains a sequence gap")
            session = {
                key: row[key] for key in SessionSnapshot.model_fields if key in row
            }
            runs = [
                {key: run[key] for key in RunSnapshot.model_fields if key in run}
                for run in state["runs"]
            ]
            owner = _owner(state)
            metadata = project_metadata_state(
                {"sessions": [{**row, "owner": owner}], "runs": state["runs"]}
            )
            db.execute(
                "INSERT OR REPLACE INTO head VALUES (1, ?, ?, ?, ?, ?)",
                (
                    _encode(fingerprint),
                    _encode(session),
                    _encode(owner),
                    _encode(runs),
                    _encode(metadata),
                ),
            )


def _head(db):
    try:
        return db.execute("SELECT * FROM head WHERE id=1").fetchone()
    except sqlite3.DatabaseError:
        return None


def _owner(state):
    row = state["sessions"][0]
    if row.get("owner") is not None:
        return row["owner"]
    _, owners = metadata_from_payload(state)
    return owners[row["session_id"]]


def _authorize(store, owner, context):
    if context is not None:
        store._authorize_session_owner(
            ActorRef.model_validate(owner) if owner else None, context
        )


def _storage(store, session_id):
    directory = store._session_dir(session_id)
    fingerprint = store._storage_fingerprint(directory)
    if fingerprint is None:
        raise OSError(f"Cannot stat Session storage at {directory}")
    if fingerprint[0] is None:
        raise store._not_found("session.not_found", session_id)
    return directory, fingerprint


def _current(path, fingerprint):
    if path.is_file():
        with closing(sqlite3.connect(path)) as db:
            head = _head(db)
            return head is not None and head[1] == _encode(fingerprint)
    return False


def _project_state(state):
    return {
        "sessions": state["sessions"],
        "runs": state.get("runs", []),
        "run_events": state.get("run_events", {}),
    }


def _history_source(store, snapshot):
    def apply(state, delta):
        projected = {
            operation: {
                collection: values
                for collection, values in rows.items()
                if collection in state
            }
            for operation, rows in delta.items()
            if operation
            in {
                "patches",
                "upserts",
                "deletes",
                "appends",
                "replacements",
                "map_deletes",
            }
        }
        store._apply_state_delta(state, projected)
        return state

    return read_filesystem_metadata(
        store,
        snapshot,
        project=_project_state,
        apply=apply,
        read_only=True,
    )


def _rebuild(store, session_id, context):
    # Only one legacy decode at a time. It does not hold the filesystem writer
    # lock while validating a large snapshot or creating the replacement.
    with store._history_build_lock:
        with store._filesystem_lock:
            directory, fingerprint = _storage(store, session_id)
            if _current(_path(directory), fingerprint):
                return
        snapshot = directory / "state.json"
        try:
            state = _history_source(store, snapshot)
        except Exception:
            with store._filesystem_lock:
                if _storage(store, session_id) != (directory, fingerprint):
                    return
            raise
        row = state["sessions"][0]
        if row["session_id"] != session_id:
            raise store._corrupt(
                "session_store.path_mismatch",
                "Historical Session identity does not match",
            )
        _authorize(store, _owner(state), context)
        with tempfile.TemporaryDirectory(dir=store.control_root) as temporary:
            replacement = Path(temporary) / "history.sqlite3"
            _publish(replacement, state, fingerprint, None, None)
            with store._filesystem_lock:
                if _storage(store, session_id) == (directory, fingerprint):
                    replacement.replace(_path(directory))


@contextmanager
def open_history(store, session_id, context=None):
    while True:
        with store._filesystem_lock:
            directory, fingerprint = _storage(store, session_id)
            path = _path(directory)
            if path.is_file():
                with closing(sqlite3.connect(path)) as db:
                    head = _head(db)
                    if head is not None and head[1] == _encode(fingerprint):
                        _, _, session, owner, runs, _ = head
                        session = SessionSnapshot.model_validate_json(session)
                        if session.session_id != session_id:
                            raise store._corrupt(
                                "session_store.path_mismatch",
                                "Historical Session identity does not match",
                            )
                        _authorize(store, json.loads(owner), context)
                        yield db, session, runs
                        return
        _rebuild(store, session_id, context)


def read_page(db, total, *, after_sequence=None, before_sequence=None, limit=None):
    if after_sequence is None:
        end = min(
            total + 1, before_sequence if before_sequence is not None else total + 1
        )
        rows = db.execute(
            "SELECT payload FROM events WHERE sequence < ? ORDER BY sequence DESC LIMIT ?",
            (end, limit),
        ).fetchall()
        events = tuple(
            RuntimeEvent.model_validate_json(payload) for (payload,) in reversed(rows)
        )
        start = (events[0].session_sequence or 1) - 1 if events else max(0, end - 1)
    else:
        start = after_sequence
        rows = db.execute(
            "SELECT payload FROM events WHERE sequence > ? ORDER BY sequence LIMIT ?",
            (min(start, total), -1 if limit is None else limit),
        )
        events = tuple(RuntimeEvent.model_validate_json(payload) for (payload,) in rows)
    return SessionEventPage(events, total, start)


def run_metadata(db):
    (payload,) = db.execute("SELECT run_metadata FROM head WHERE id=1").fetchone()
    return metadata_from_payload(json.loads(payload))


def metadata(store, session_id, context):
    with open_history(store, session_id, context) as (_, session, runs):
        values = (RunSnapshot.model_validate(row) for row in json.loads(runs))
        latest = max(values, key=lambda run: (run.created_at, run.run_id), default=None)
    with store._index_lock:
        candidates = [
            sid
            for sid, row in store._session_index.items()
            if row["parent_session_id"] == session_id
        ]
    from sagents.v2.contracts.errors import ErrorCategory, SageV2Error

    children = []
    for child_id in sorted(candidates):
        try:
            with open_history(store, child_id, context):
                children.append(child_id)
        except SageV2Error as exc:
            if (
                exc.info.category != ErrorCategory.AUTHORIZATION
                and exc.info.code != "session.not_found"
            ):
                raise
    return SessionHistoryMetadata(session, latest, tuple(children))


def tool_activity(db, session_id, *, tool_name, path, state, limit):
    clauses, parameters = [], []
    if tool_name is not None:
        clauses.append("c.tool_name = ?")
        parameters.append(tool_name)
    if path is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM paths WHERE run_id=c.run_id AND call_id=c.call_id AND path=?)"
        )
        parameters.append(posixpath.normpath(path.replace("\\", "/")))
    if state is not None:
        clauses.append("c.state = ?")
        parameters.append(state)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.execute(
        "SELECT c.run_id, c.call_id, c.tool_name, c.state, c.sequence FROM calls c"
        + where
        + " ORDER BY c.sequence DESC LIMIT ?",
        (*parameters, limit),
    )
    return tuple(
        SessionToolActivity(
            session_id,
            run_id,
            call_id,
            name,
            status,
            sequence,
            tuple(
                value
                for (value,) in db.execute(
                    "SELECT path FROM paths WHERE run_id=? AND call_id=? ORDER BY path",
                    (run_id, call_id),
                )
            ),
        )
        for run_id, call_id, name, status, sequence in rows
    )
