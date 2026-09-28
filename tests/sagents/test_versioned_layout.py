"""Smoke coverage for public imports and relocated standalone entry points."""

from pathlib import Path
import os
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.timeout(30)
def test_public_runtime_imports_remain_lazy_and_keep_class_identity(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", """
import sys
import sagents
assert 'sagents.v1.sagents' not in sys.modules
import sagents.v2
assert 'sagents.v1.sagents' not in sys.modules
from sagents import SAgent
from sagents.v1 import SAgent as V1Agent
from sagents.v1.sagents import SAgent as Implementation
assert SAgent is V1Agent is Implementation
from sagents.v1.llm.model_capabilities import is_openai_reasoning_model
from sagents.v1.utils.sandbox.policy import SandboxPolicyGateway
assert is_openai_reasoning_model('o3')
assert SandboxPolicyGateway
"""],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT), "SAGE_DISABLE_SAGENTS_FILE_LOGGING": "1"},
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.timeout(15)
@pytest.mark.parametrize("name", ["sage_cli.py", "sage_demo.py", "sage_server.py"])
def test_v1_example_help_runs_outside_the_repository(name, tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "v1" / name), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "usage:" in result.stdout.lower()
