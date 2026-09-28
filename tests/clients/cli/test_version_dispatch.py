"""Installed public dispatch must not initialize the other generation."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('version,args', [
    ('v2', ['v2', 'sessions', '--json']),
    ('v1', ['run', '--help']),
])
def test_dispatch_with_other_generation_blocked(tmp_path, version, args):
    other = 'v1' if version == 'v2' else 'v2'
    if version == 'v2':
        args += ['--session-root', str(tmp_path / 'sessions')]
    script = f'''
import importlib.abc, sys
class BlockOther(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        for prefix in ('app.{other}', 'sagents.{other}'):
            if fullname == prefix or fullname.startswith(prefix + '.'):
                raise AssertionError('Cross-generation import: ' + fullname)
sys.meta_path.insert(0, BlockOther())
from clients.cli.main import main
try:
    result = main({args!r})
except SystemExit as exc:
    result = exc.code
assert result == 0, result
assert not any(name == 'app.{other}' or name.startswith('app.{other}.') for name in sys.modules)
'''
    result = subprocess.run(
        [sys.executable, '-c', script], cwd=tmp_path,
        env={**os.environ, 'PYTHONPATH': str(ROOT), 'SAGE_LOCAL_DATA_ROOT': str(tmp_path)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_v2_configuration_uses_env_without_legacy_initialization(tmp_path, monkeypatch):
    from app.v2.cli.config import configure_cli_logging, sage_home
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('SAGE_LOCAL_DATA_ROOT', str(tmp_path))
    (tmp_path / '.env').write_text('SAGE_DEFAULT_LLM_MODEL_NAME=local-test\nSAGE_DEFAULT_LLM_API_BASE_URL=http://localhost:4321/v1\n')
    # load_dotenv intentionally writes the process environment; restore it after this test.
    monkeypatch.setenv('SAGE_DEFAULT_LLM_MODEL_NAME', '')
    monkeypatch.setenv('SAGE_DEFAULT_LLM_API_BASE_URL', '')
    config = configure_cli_logging(verbose=False)
    assert config.default_llm_model_name == 'local-test'
    assert config.default_llm_api_base_url == 'http://localhost:4321/v1'
    assert sage_home() == tmp_path
    assert not (tmp_path / 'sage.db').exists()
