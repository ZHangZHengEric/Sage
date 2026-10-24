"""Authoritative official environment replay from canonical tool evidence."""
import json
from evaluation_datasets import _interactive
from evaluation_datasets.alfworld import runtime
from sagents.v2.optimization.scoring import ScorerDescriptor

SCORER_CONTRACT = """Replay completed native MCP actions in the pinned official ALFWorld environment.
Only committed task IDs are supported. No external trajectories, rewards or files are trusted.
A rejected action or mismatched native observation is an invalid measurement, not zero credit.
Budget is 200 actions. Binary official won flag.
Verified successful native load_skill receipts may load enabled instructions;
they are auxiliary reads, never environment actions or sources of reward.
Already-dispatched postterminal siblings must match the absorbing terminal snapshot;
they do not consume another environment action or extend the 200-action budget.
Single-turn native loop guards close an episode only with complete bound successful receipts;
the Run remains suspended and the official world alone determines reward for its action prefix.
This fixed subset is an RSI experiment, not the full official leaderboard."""
DESCRIPTOR = ScorerDescriptor(id='alfworld.official-replay', name='ALFWorld official replay',
    version='native-v3-aaba6870f86c5be6a08a491f32a50b906227bc3e', contract=SCORER_CONTRACT)


def score(request):
    return _interactive.evaluate(runtime, 'ALFWorld', json.loads(request['case']['reference_answer']), request)


SCORER_TEST_CASES = json.loads((runtime.ROOT / 'fixtures.json').read_text())
