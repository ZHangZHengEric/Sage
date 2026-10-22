import json

import pytest

from examples.v2.tau_bench_replay import DevelopmentReplay
from sagents.v2.optimization.contracts import OptimizationObservation


def saved(root):
    obs = OptimizationObservation(state='completed', output='kept failure evidence',
        evidence={'tau_trajectory': str(root / 'episodes' / 'e1' / 'simulation.json')})
    events = [
        {'event': 'candidate_created', 'data': {'package': {'manifest': {'metadata': {'version': '1.opt.' + 'a' * 32 + '.1'}}}}},
        {'event': 'target_call_started', 'data': {'call_id': 'c', 'package_hash': 'p', 'input': 'question'}},
        {'event': 'target_call_completed', 'data': {'call_id': 'c', 'observation': obs.model_dump(mode='json')}},
    ]
    (root / 'rsi.jsonl').write_text('\n'.join(map(json.dumps, events)))
    (root / 'episodes.json').write_text(json.dumps([{'phase': 'rsi', 'episode': 'e1'}]))
    (root / 'internal-calls').mkdir()
    (root / 'internal-calls' / '001-tuner.json').write_text(json.dumps({'role': 'tuner', 'request': {'data': {'score': .2}}, 'observation': obs.model_dump(mode='json')}))


def test_exact_replay_consumes_each_observation_once_and_preserves_failure(tmp_path):
    saved(tmp_path)
    replay = DevelopmentReplay(tmp_path)
    assert replay.optimization_id == 'a' * 32
    with pytest.raises(ValueError, match='request differs'):
        replay.agent('tuner', {'data': {'score': .9}})
    with pytest.raises(ValueError, match='target replay differs'):
        replay.target('other-package', 'question')
    assert replay.target('p', 'question').output == 'kept failure evidence'
    replay.agent('tuner', {'data': {'score': .2}})
    assert replay.target('p', 'question') is None
    replay.assert_consumed()
    assert replay.agent('reviewer', {}) is None


def test_replay_rejects_missing_evidence_and_test_contamination(tmp_path):
    saved(tmp_path)
    (tmp_path / 'episodes.json').write_text(json.dumps([{'phase': 'rsi', 'episode': 'missing'}]))
    with pytest.raises(ValueError, match='disagree'):
        DevelopmentReplay(tmp_path)
    (tmp_path / 'episodes.json').write_text(json.dumps([{'phase': 'test-candidate', 'episode': 'e1'}]))
    with pytest.raises(ValueError, match='frozen test'):
        DevelopmentReplay(tmp_path)
