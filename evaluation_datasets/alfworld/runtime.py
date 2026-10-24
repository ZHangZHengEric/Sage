"""Official ALFWorld TextWorld backend, replayed without planner/oracle tools."""
from __future__ import annotations
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from evaluation_datasets import _interactive, _support

ROOT = Path(__file__).resolve().parent
LIMIT = 200
ABSORBING_TERMINAL = True
tools, validate = _interactive.tools, _interactive.validate


@lru_cache(maxsize=1)
def activate():
    _support.activate(ROOT, 'vendor')
    os.environ.setdefault('ALFWORLD_DATA', str(ROOT / 'data'))
    import textworld
    from alfworld.agents.environment.alfred_tw_env import AlfredDemangler
    return textworld, AlfredDemangler


@lru_cache(maxsize=1)
def tasks():
    return {t['id']: t for t in json.loads((ROOT / 'data/tasks.json').read_text())}


def task(context):
    return tasks()[context['task_id']]


def initial(context):
    task(context)
    return {'actions': []}


def replay(context, actions):
    if len(actions) > LIMIT:
        raise ValueError('ALFWorld action budget exceeded (200)')
    textworld, wrapper = activate()
    t = task(context)
    game = ROOT / 'data' / t['game']
    if hashlib.sha256(game.read_bytes()).hexdigest() != t['sha256']:
        raise ValueError('Official game data hash mismatch')
    env = textworld.start(str(game), request_infos=textworld.EnvInfos(won=True, admissible_commands=True), wrappers=[wrapper])
    try:
        state = env.reset()
        def public(s, done):
            return {'observation': s['feedback'], 'admissible_commands': sorted(s['admissible_commands']), 'done': done}
        snapshots, done = [public(state, False)], False
        for index, action in enumerate(actions, 1):
            if done:
                # Official evaluation ends at done. Sibling calls already sent
                # in the same model batch see the absorbing terminal snapshot.
                snapshots.append(dict(snapshots[-1]))
                continue
            state, reward, done = env.step(action)
            done = bool(done) or index == LIMIT
            snapshots.append(public(state, bool(done)))
        return snapshots, float(bool(state['won']))
    finally:
        env.close()


def call(context, state, name, args):
    import sys
    return _interactive.call(sys.modules[__name__], context, state, name, args)


def preflight():
    activate()
    context = {'task_id': next(iter(tasks()))}
    replay(context, [])
    return {'backend': 'official TextWorld PDDL', 'tasks': len(tasks()), 'ready': True}


if __name__ == '__main__':
    print(json.dumps(preflight()))
