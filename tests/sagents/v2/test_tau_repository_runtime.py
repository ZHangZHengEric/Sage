"""Repository-owned benchmark assets must be complete before paid model work."""
import hashlib
import json

import pytest


from evaluation_datasets.tau_bench import runtime


def test_pinned_source_manifest_covers_every_required_shared_guideline():
    manifest = json.loads((runtime.ROOT / 'upstream.json').read_text())
    assert manifest['commit'] == 'fc0055dc4e0a316c3f83133267fbd6faaa770992'
    for name in ('simulation_guidelines.md', 'simulation_guidelines_tools.md'):
        path = 'data/tau2/user_simulator/' + name
        assert path in manifest['files']
        assert hashlib.sha256((runtime.ROOT / path).read_bytes()).hexdigest() == manifest['files'][path]


def test_preflight_loads_official_environment_and_user_prompts_without_model_calls():
    pytest.importorskip("litellm")  # Optional extra; do not skip missing vendored tau2.
    status = runtime.preflight()
    assert status['tools'] == 16 and status['tasks'] == 114
    assert status['splits']['train'] == 74 and status['splits']['test'] == 40
