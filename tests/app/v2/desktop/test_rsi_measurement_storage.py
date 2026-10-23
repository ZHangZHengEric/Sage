import copy
import json

import pytest

from app.v2.desktop.backend.rsi import RsiStore


def record():
    return {
        "id": "run",
        "status": "running",
        "stage": "evaluation",
        "test_observations": [
            {
                "round": 0,
                "cases": [
                    {"id": "hidden", "score": 0, "conversation": ["evidence" * 1000]},
                ],
            }
        ],
        "human_test_suite": {"cases": [{"input": "hidden question"}]},
    }


def test_progress_preserves_measurements_without_serializing_them(tmp_path):
    store = RsiStore(tmp_path / "rsi.sqlite3", recover_interrupted=False)
    value = record()
    original = copy.deepcopy(value)
    store.put(value, "alice", "agent", "run")

    class NoSerialization(list):
        def __iter__(self):
            raise AssertionError("Unchanged human evidence must not be serialized")

    value["test_observations"] = NoSerialization([object()])
    value["stage"] = "tuning"
    store.put(value, "alice", "agent", "run", preserve_test_observations=True)
    restored = store.get("run", "alice", "agent", "run")
    assert restored == {**original, "stage": "tuning"}
    assert store.list("alice", "agent", "run") == [restored]
    with store.connect() as db:
        body, summary = db.execute("SELECT body, summary FROM records").fetchone()
        assert "evidence" not in body and "evidence" not in summary
        assert "hidden question" not in summary
    with pytest.raises(ValueError, match="not found"):
        store.get("run", "bob", "agent", "run")


def test_measurement_update_and_status_commit_atomically(tmp_path):
    store = RsiStore(tmp_path / "rsi.sqlite3", recover_interrupted=False)
    original = record()
    store.put(original, "alice", "agent", "run")
    changed = copy.deepcopy(original)
    changed["test_observations"][0]["cases"][0]["score"] = 1
    changed["invalid"] = object()
    with pytest.raises(TypeError):
        store.put(changed, "alice", "agent", "run")
    assert store.get("run", "alice", "agent", "run") == original
    changed.pop("invalid")
    store.put(changed, "alice", "agent", "run")
    assert store.get("run", "alice", "agent", "run") == changed


def test_legacy_inline_record_migrates_on_progress_and_survives_reopen(tmp_path):
    path = tmp_path / "rsi.sqlite3"
    store = RsiStore(path, recover_interrupted=False)
    value = record()
    with store.connect() as db:
        db.execute(
            "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)",
            ("run", "alice", "agent", "run", json.dumps(value), json.dumps(value)),
        )
    assert store.get("run", "alice", "agent", "run") == value
    store.put(value, "alice", "agent", "run", preserve_test_observations=True)
    reopened = RsiStore(path)
    restored = reopened.get("run", "alice", "agent", "run")
    assert restored["status"] == "interrupted"
    assert restored["test_observations"] == value["test_observations"]
    summary = reopened.summaries("alice", "agent", "run")[0]
    assert "test_observations" not in summary
    assert "human_test_suite" not in summary
    assert "_test_observations_external" not in restored


def test_missing_or_wrong_owner_payload_is_not_treated_as_empty_test(tmp_path):
    store = RsiStore(tmp_path / "rsi.sqlite3", recover_interrupted=False)
    store.put(record(), "alice", "agent", "run")
    with store.connect() as db:
        db.execute("UPDATE run_test_observations SET user='bob'")
    with pytest.raises(ValueError, match="unavailable"):
        store.get("run", "alice", "agent", "run")


def test_explicit_removal_does_not_resurrect_old_measurements(tmp_path):
    store = RsiStore(tmp_path / "rsi.sqlite3", recover_interrupted=False)
    value = record()
    store.put(value, "alice", "agent", "run")
    value.pop("test_observations")
    store.put(value, "alice", "agent", "run")
    assert store.get("run", "alice", "agent", "run") == value
    with store.connect() as db:
        assert (
            db.execute("SELECT count(*) FROM run_test_observations").fetchone()[0] == 0
        )
