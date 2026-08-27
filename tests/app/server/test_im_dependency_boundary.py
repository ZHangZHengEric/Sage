import subprocess
import sys
from pathlib import Path


def test_server_chat_service_does_not_import_desktop_im_storage_model():
    repo_root = Path(__file__).resolve().parents[3]
    script = """
import os
import sys

os.environ["SAGE_INTERNAL_SERVER_PROCESS"] = "1"
import common.services.chat_service  # noqa: F401

assert "common.models.im_channel" not in sys.modules
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
