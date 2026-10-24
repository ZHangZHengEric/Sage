"""Authoritative official environment replay from canonical tool evidence."""
import json
from evaluation_datasets import _interactive
from evaluation_datasets.scienceworld import runtime
from sagents.v2.optimization.scoring import ScorerDescriptor

SCORER_CONTRACT = """Replay completed native MCP actions in the pinned official ScienceWorld environment.
Only committed task IDs are supported. No external trajectories, rewards or files are trusted.
A rejected action or mismatched native observation is an invalid measurement, not zero credit.
Budget is 200 actions. Official cumulative score clamped to [0,100] / 100; pass only at 100.
Single-turn native loop guards close an episode only with complete bound successful receipts;
the Run remains suspended and the official world alone determines reward for its action prefix.
This fixed subset is an RSI experiment, not the full official leaderboard."""
DESCRIPTOR = ScorerDescriptor(id='scienceworld.official-replay', name='ScienceWorld official replay',
    version='native-v2-e8216d6044e8e39be9fcb185e3b2dfb602584b52', contract=SCORER_CONTRACT)


def score(request):
    return _interactive.evaluate(runtime, 'ScienceWorld', json.loads(request['case']['reference_answer']), request)


SCORER_TEST_CASES = json.loads((runtime.ROOT / 'fixtures.json').read_text())
