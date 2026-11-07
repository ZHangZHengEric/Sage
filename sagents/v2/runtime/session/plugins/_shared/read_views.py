"""Validate and replay bounded read projections without installing aggregates."""

from .aggregate import _decode_json as _json
from sagents.v2.runtime.session.read_views import project_view_state, apply_view_delta


def replay_view_rows(rows, mutations, **options):
    replay_options = {
        key: options[key] for key in ("include_events", "run_ids") if key in options
    }
    states, heads = {}, {}
    for sid, raw, revision, last_sequence in rows:
        state = project_view_state(_json(raw), **replay_options)
        if len(state["sessions"]) != 1 or state["sessions"][0]["session_id"] != sid:
            raise ValueError("Session read view has an invalid head")
        states[sid] = state
        heads[sid] = (int(revision), int(last_sequence))
    for sid, revision, raw in mutations:
        if sid not in states:
            continue
        state = states[sid]
        if int(revision) != int(state["sessions"][0]["revision"]) + 1:
            raise ValueError("Session read view mutation revision gap")
        apply_view_delta(state, _json(raw), **replay_options)
        if len(state["sessions"]) != 1 or int(state["sessions"][0]["revision"]) != int(
            revision
        ):
            raise ValueError("Session read view mutation head mismatch")
    for sid, state in states.items():
        if (
            int(state["sessions"][0]["revision"]),
            int(state["sessions"][0]["last_sequence"]),
        ) != heads[sid]:
            raise ValueError("Session read view durable head mismatch")
    return states
