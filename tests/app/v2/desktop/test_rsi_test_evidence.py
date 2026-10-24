import json

import pytest

from app.v2.desktop.backend.rsi_test_recovery import persist_human_evidence


def test_resuming_keeps_prior_private_evidence_when_observer_has_no_new_rows(tmp_path):
    path = tmp_path / 'evidence.json'
    baseline = {'round': 0, 'package_hash': 'base', 'case_id': 'test', 'trial': 1,
                'conversation': [{'user': 'task', 'target': {'state': 'completed'}}]}
    persist_human_evidence(path, [baseline])
    persist_human_evidence(path, [])
    assert json.loads(path.read_text()) == [baseline]
    new = {**baseline, 'round': 1, 'package_hash': 'candidate'}
    persist_human_evidence(path, [new])
    assert json.loads(path.read_text()) == [baseline, new]


def test_completed_private_execution_cannot_be_silently_replaced(tmp_path):
    path = tmp_path / 'evidence.json'
    row = {'round': 0, 'package_hash': 'base', 'case_id': 'test', 'trial': 1, 'conversation': []}
    persist_human_evidence(path, [row])
    with pytest.raises(ValueError, match='evidence differs'):
        persist_human_evidence(path, [{**row, 'conversation': [{'user': 'different'}]}])
    assert json.loads(path.read_text()) == [row]


def test_failed_atomic_replacement_preserves_previous_evidence(tmp_path, monkeypatch):
    import os
    path = tmp_path / 'evidence.json'
    row = {'round': 0, 'package_hash': 'base', 'case_id': 'test', 'trial': 1, 'conversation': []}
    persist_human_evidence(path, [row])
    before = path.read_bytes()

    def failed_replace(source, destination):
        assert destination == path
        assert json.loads(source.read_text()) == [row, {**row, 'round': 1}]
        assert source.stat().st_mode & 0o777 == 0o600
        raise OSError('Simulated replacement failure')

    monkeypatch.setattr(os, 'replace', failed_replace)
    with pytest.raises(OSError, match='replacement failure'):
        persist_human_evidence(path, [{**row, 'round': 1}])
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
