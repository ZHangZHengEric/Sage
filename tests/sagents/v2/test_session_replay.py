from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from sagents.v2.runtime.session.aggregate import SessionAggregate
from sagents.v2.runtime.session.journal import (
    SessionAggregateSnapshotV2,
    SessionRowSnapshot,
    SessionStateDeltaMutation,
)
from sagents.v2.runtime.session.mysql_state import (
    SessionStoreCorruptionError,
    _MysqlSessionState,
)


def replay_history():
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    base = SessionAggregateSnapshotV2(sessions=(SessionRowSnapshot(
        session_id="session_1", revision=1, last_sequence=0,
        created_at=now, updated_at=now, revision_sequences={"0": 0, "1": 0},
    ),), coordinator_command_results=(
        {"idempotency_key": "keep", "request_digest": "first", "result_revision": 1},
        {"idempotency_key": "remove", "request_digest": "second", "result_revision": 1},
    ))

    def head(revision):
        return {**base.sessions[0].model_dump(mode="json"), "revision": revision,
                "revision_sequences": {str(revision): 0}}

    def steer(identity, sequence):
        return {"steer_id": identity, "run_id": "run_1", "expected_turn_id": "turn_1",
                "inbox_sequence": sequence, "input": [], "mode": "steer",
                "created_at": now.isoformat()}

    deltas = [
        SessionStateDeltaMutation(
            upserts={"sessions": [head(2)]},
            patches={"coordinator_command_results": [{"idempotency_key": "keep", "result_revision": 2}]},
            deletes={"coordinator_command_results": [["remove"]]},
            appends={"steer_inbox": {"run_1": [steer("first", 1)], "old_run": [steer("old", 1)]}},
        ),
        SessionStateDeltaMutation(
            upserts={"sessions": [head(3)], "coordinator_command_results": [
                {"idempotency_key": "new", "request_digest": "third", "result_revision": 3}]},
            appends={"steer_inbox": {"run_1": [steer("second", 2)]}},
        ),
        SessionStateDeltaMutation(
            upserts={"sessions": [head(4)]},
            patches={"coordinator_command_results": [{"idempotency_key": "new", "result_revision": 4}]},
            appends={"steer_inbox": {"run_1": [steer("discarded", 3)]}},
            replacements={"steer_inbox": {"run_1": [steer("replacement", 4)]}},
            map_deletes={"steer_inbox": ["old_run"]},
        ),
    ]
    return base, deltas


def test_multi_delta_replay_matches_sequential_aggregate_semantics():
    base, deltas = replay_history()
    original = base.model_dump(mode="json")
    expected = SessionAggregate(base)
    rows = []
    for revision, delta in enumerate(deltas, 2):
        rows.append((revision, json.dumps(delta.model_dump(mode="json", exclude={"kind"}))))
        head = delta.upserts["sessions"][0]
        full_head = {**head, "revision_sequences": {
            **expected.snapshot.sessions[0].revision_sequences, **head["revision_sequences"]}}
        expected = expected.apply(delta.model_copy(update={"upserts": {**delta.upserts, "sessions": [full_head]}}))

    restored = _MysqlSessionState._replay_mutations(original, rows, 4, 0)

    assert restored == expected.snapshot.model_dump(mode="json")
    assert restored["sessions"][0]["revision_sequences"] == {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0}
    assert [row["steer_id"] for row in restored["steer_inbox"]["run_1"]] == ["replacement"]
    assert original == base.model_dump(mode="json")


@pytest.mark.parametrize("damage", ["gap", "invalid_head", "missing_patch", "unknown_patch", "head_revision", "head_sequence"])
def test_replay_rejects_corrupt_delta_history(damage):
    base, deltas = replay_history()
    rows = [(revision, deepcopy(delta.model_dump(mode="json", exclude={"kind"})))
            for revision, delta in enumerate(deltas, 2)]
    revision, sequence = 4, 0
    if damage == "gap":
        rows.pop(1)
    elif damage == "invalid_head":
        rows[0][1]["upserts"]["sessions"][0]["revision"] = 9
    elif damage == "missing_patch":
        # A later upsert must not conceal an earlier patch of a nonexistent row.
        rows[0][1]["patches"]["coordinator_command_results"] = [{"idempotency_key": "new", "result_revision": 2}]
    elif damage == "unknown_patch":
        rows[0][1]["patches"]["unknown_collection"] = [{"id": "missing"}]
    elif damage == "head_revision":
        revision = 5
    else:
        sequence = 1

    with pytest.raises(SessionStoreCorruptionError):
        _MysqlSessionState._replay_mutations(base.model_dump(mode="json"),
            [(number, json.dumps(delta)) for number, delta in rows], revision, sequence)
