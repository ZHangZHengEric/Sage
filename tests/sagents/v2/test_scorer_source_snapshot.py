import hashlib
from pathlib import Path
import shutil

import pytest

from sagents.v2.optimization.scorer_snapshot import freeze_worker_sources
from sagents.v2.optimization.python_scorer import PythonExecutionScorer, ScorerExecutionError
from tests.sagents.v2.test_python_scorer import request


@pytest.mark.asyncio
async def test_worker_uses_snapshot_after_checkout_changes(tmp_path):
    root = tmp_path / 'checkout'
    actual = Path(__file__).resolve().parents[3]
    shutil.copytree(actual / 'sagents', root / 'sagents', ignore=shutil.ignore_patterns('__pycache__', 'node_modules'))
    package = root / 'fixture_package'
    package.mkdir()
    (package / '__init__.py').write_text('from sibling_support import VALUE\n')
    sibling = root / 'sibling_support.py'
    sibling.write_text('VALUE = 0.8\n')
    frozen = freeze_worker_sources(tmp_path / 'snapshots', source_root=root,
        dependency_manifest={'trees': {str(package): []}, 'files': {str(sibling): 'captured'}})
    plugin = tmp_path / 'scorer.py'
    plugin.write_text("from fixture_package import VALUE\ndef score(request):\n return {'score': VALUE, 'passed': True, 'rationale': 'fixture'}\n")
    scorer = PythonExecutionScorer(path=plugin, source_hash=hashlib.sha256(plugin.read_bytes()).hexdigest(),
        descriptor={'id': 'fixture', 'name': 'Fixture', 'version': '1'}, worker_source_root=frozen)
    first = await scorer.score(request())
    (package / '__init__.py').write_text('raise RuntimeError("mutable checkout must not be imported")\n')
    sibling.write_text('raise RuntimeError("mutable sibling must not be imported")\n')
    (root / 'sagents/v2/optimization/runner.py').write_text('raise RuntimeError("checkout changed")\n')
    second = await scorer.score(request())
    assert first.grade.score == second.grade.score == .8
    # Snapshot tampering still fails; never relax the integrity guard.
    captured = frozen / 'fixture_package/__init__.py'
    captured.chmod(0o644)
    captured.write_text('VALUE = 0.0\n')
    with pytest.raises(ScorerExecutionError) as error:
        await scorer.score(request())
    assert error.value.code == 'scorer.dependencies_changed'
