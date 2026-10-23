"""Activate repository-owned official source/data without temporary paths."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def activate(*, verify=True):
    manifest = json.loads((ROOT / 'upstream.json').read_text())
    if verify:
        for name, digest in manifest['files'].items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f'official source changed: {name}')
    os.environ['TAU2_DATA_DIR'] = str(ROOT / 'data')
    os.environ.setdefault('LITELLM_LOCAL_MODEL_COST_MAP', 'True')
    sys.path.insert(0, str(ROOT / 'vendor/src'))
    return manifest


def preflight():
    """Check text runtime resources and official domain loading without model calls."""
    manifest = activate()
    from tau2.domains.retail.environment import get_environment, get_tasks
    from tau2.user.user_simulator import get_global_user_sim_guidelines
    if not get_global_user_sim_guidelines(use_tools=False).strip():
        raise ValueError('official user simulation guidelines are empty')
    if not get_global_user_sim_guidelines(use_tools=True).strip():
        raise ValueError('official tool-using user simulation guidelines are empty')
    environment = get_environment()
    tasks = get_tasks()
    splits = json.loads((ROOT / 'data/tau2/domains/retail/split_tasks.json').read_text())
    return {'commit': manifest['commit'], 'verified_files': len(manifest['files']),
            'tools': len(environment.get_tools()), 'tasks': len(tasks),
            'splits': {name: len(ids) for name, ids in splits.items()}}
