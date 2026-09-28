"""Desktop v2 composition must not load the v1 runtime to build requests."""

from pathlib import Path
import os
import subprocess
import sys

import pytest

from app.v2.desktop.backend.model_request_defaults import build_llm_extra_body


@pytest.mark.timeout(30)
def test_composition_loads_with_v1_imports_blocked(tmp_path):
    root = Path(__file__).resolve().parents[4]
    result = subprocess.run(
        [sys.executable, "-c", """
import importlib.abc
import sys

class BlockV1(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.v1' or fullname.startswith('app.v1.') or fullname == 'common' or fullname.startswith('common.') or fullname == 'sagents.v1' or fullname.startswith('sagents.v1.'):
            raise AssertionError('Desktop v2 imported ' + fullname)

sys.meta_path.insert(0, BlockV1())
from app.v2.desktop.backend import run_composition, shell_policy, anytool
from app.v2.desktop.backend.command_policy import ShellCommandPolicyGateway
from sagents.v2.tool.official.media import compress_image_to_jpeg_bytes_for_llm
assert run_composition.compress_image_to_jpeg_bytes_for_llm is compress_image_to_jpeg_bytes_for_llm
gateway = ShellCommandPolicyGateway(approval_mode='on-request')
assert gateway.evaluate_shell_command('git push --force origin main').action == 'deny'
assert gateway.evaluate_shell_command('git reset --hard').action == 'ask'
assert gateway.evaluate_shell_command('cat README.md').action == 'allow'
assert not any(name == 'sagents.v1' or name.startswith('sagents.v1.') for name in sys.modules)
"""],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("model", "base_url", "enabled", "level", "expected"),
    [
        ("o3", "https://api.openai.com/v1", True, "high", {"reasoning_effort": "high"}),
        (
            "deepseek-chat", "https://api.deepseek.com", False, None,
            {"thinking": {"type": "disabled"}},
        ),
        (
            "qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1", False, None,
            {"enable_thinking": False},
        ),
        (
            "glm-5.2", "https://open.bigmodel.cn/api/paas/v4", False, None,
            {"thinking": {"type": "disabled"}},
        ),
        (
            "local-model", "http://localhost:8000/v1", False, None,
            {
                "enable_thinking": False,
                "thinking": {"type": "disabled"},
                "chat_template_kwargs": {"enable_thinking": False},
            },
        ),
    ],
)
def test_unverified_model_request_defaults_preserve_wire_fields(
    model, base_url, enabled, level, expected
):
    assert build_llm_extra_body(
        model, base_url=base_url, enable_thinking=enabled, thinking_level=level
    ) == expected
