"""Pinned official JVM simulator; gold trajectories never enter tool responses."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import types
from functools import lru_cache
from pathlib import Path
from evaluation_datasets import _interactive, _support

ROOT = Path(__file__).resolve().parent
LIMIT = 200
tools, validate = _interactive.tools, _interactive.validate


@lru_cache(maxsize=1)
def activate():
    _support.activate(ROOT, 'vendor')
    config = ROOT / '.runtime/java.json'
    if config.exists():
        os.environ['JAVA_HOME'] = json.loads(config.read_text())['java_home']
    java = str(Path(os.environ['JAVA_HOME']) / 'bin/java') if os.environ.get('JAVA_HOME') else 'java'
    try:
        subprocess.run([java, '-version'], check=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError('ScienceWorld needs Java 17. Install a JRE and configure JAVA_HOME in both the Desktop backend and MCP.') from e
    # Upstream's version.py is generated at package-build time and absent in Git.
    # Use its unmodified simulator submodule through a namespace package.
    if 'scienceworld' not in sys.modules:
        package = types.ModuleType('scienceworld')
        package.__path__ = [str(ROOT / 'vendor/scienceworld')]
        sys.modules['scienceworld'] = package
    from scienceworld.scienceworld import ScienceWorldEnv
    return ScienceWorldEnv


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
        raise ValueError('ScienceWorld action budget exceeded (200)')
    cls = activate()
    t = task(context)
    env = cls(envStepLimit=LIMIT + 1)  # Upstream reset() consumes one look-around step.
    try:
        env.load(t['task'], t['variation'], simplificationStr='', generateGoldPath=False)
        obs, info = env.reset()
        if env.get_task_description().strip() != t['input'].strip():
            raise ValueError('Task description differs from the pinned runtime; regenerate and verify data')
        def public(o, i, done):
            return {'observation': o, 'look': i['look'], 'inventory': i['inv'], 'done': done}
        snapshots, done = [public(obs, info, False)], False
        for action in actions:
            if done:
                raise ValueError('Cannot act after the episode ended')
            obs, reward, done, info = env.step(action)
            snapshots.append(public(obs, info, bool(done)))
        return snapshots, max(0, min(100, info['score'])) / 100
    finally:
        env.close()
        try:
            env._gateway.java_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            env._gateway.java_process.kill()
            env._gateway.java_process.wait(timeout=5)


def call(context, state, name, args):
    return _interactive.call(sys.modules[__name__], context, state, name, args)


def preflight():
    activate()
    replay({'task_id': next(iter(tasks()))}, [])
    return {'backend': 'official ScienceWorld JVM', 'tasks': len(tasks()), 'ready': True}


if __name__ == '__main__':
    print(json.dumps(preflight()))
