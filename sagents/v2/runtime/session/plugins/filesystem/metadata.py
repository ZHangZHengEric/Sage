"""Backend metadata loading over the canonical Session projection."""

from sagents.v2.runtime.session.metadata_replay import (
    project_metadata_state,
    apply_metadata_delta,
)


def read_filesystem_metadata(
    store, snapshot, *, project=project_metadata_state, apply=apply_metadata_delta
):
    import json

    payload = store._read_snapshot_payload(snapshot)
    if payload.get("format") not in {
        "sage.filesystem-session-store/v2",
        "sage.filesystem-session-store/v3",
        "sage.filesystem-session-store/v4",
    }:
        raise ValueError("unsupported metadata snapshot format")
    revision = int(payload["current_session_revision"])
    state = project(payload["state"])
    journal = snapshot.parent / "journal.jsonl"
    if journal.exists():
        with journal.open("rb") as stream:
            for line in stream:
                if not line.endswith(b"\n"):
                    break
                entry = json.loads(line)
                unsigned = {
                    key: value for key, value in entry.items() if key != "checksum"
                }
                if entry.get("checksum") != store._checksum(unsigned):
                    raise store._corrupt(
                        "session_store.hash_mismatch",
                        "metadata journal checksum mismatch",
                    )
                if int(entry["current_session_revision"]) <= revision:
                    continue
                if int(entry["previous_session_revision"]) != revision:
                    raise store._corrupt(
                        "session_store.revision_gap", "metadata journal revision gap"
                    )
                state = apply(state, entry.get("mutation", entry.get("delta", {})))
                revision = int(entry["current_session_revision"])
                if int(state["sessions"][0]["revision"]) != revision:
                    raise store._corrupt(
                        "session_store.revision_mismatch",
                        "metadata journal revision mismatch",
                    )
    if len(state["sessions"]) != 1 or int(state["sessions"][0]["revision"]) != revision:
        raise store._corrupt(
            "session_store.revision_mismatch", "metadata snapshot revision mismatch"
        )
    return state
