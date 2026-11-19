"""Backend metadata loading over the canonical Session projection."""

from sagents.v2.runtime.session.metadata_replay import (
    project_metadata_state,
    apply_metadata_delta,
)


def read_filesystem_metadata(
    store, snapshot, *, project=project_metadata_state, apply=apply_metadata_delta,
    read_only=False,
):
    import json

    payload = (
        store._read_snapshot_payload(snapshot, read_only=True)
        if read_only else store._read_snapshot_payload(snapshot)
    )
    snapshot_format = payload.get("format")
    if snapshot_format not in {
        "sage.filesystem-session-store/v2",
        "sage.filesystem-session-store/v3",
        "sage.filesystem-session-store/v4",
    }:
        raise ValueError("unsupported metadata snapshot format")
    revision = int(payload["current_session_revision"])
    state = project(payload["state"])
    del payload
    journal = snapshot.parent / "journal.jsonl"
    if journal.exists():
        with journal.open("rb") as stream:
            for line in stream:
                if snapshot_format == "sage.filesystem-session-store/v2":
                    if line.strip():
                        raise store._corrupt(
                            "session_store.journal_corrupt", "v2 snapshot unexpectedly has a journal"
                        )
                    continue
                if not line.endswith(b"\n"):
                    break
                entry = json.loads(line)
                version = snapshot_format[-2:]
                if entry.get("format") != f"sage.filesystem-session-journal/{version}":
                    raise store._corrupt(
                        "session_store.journal_corrupt", "metadata journal has an invalid format"
                    )
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
