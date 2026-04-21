#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli.main import _build_cli_error_payload
from app.cli.service import CLIError, validate_cli_request_options


class TestCliErrorHandling(unittest.TestCase):
    def test_build_payload_from_cli_error_keeps_next_steps(self):
        exc = CLIError(
            "Workspace path is not writable",
            next_steps=["Choose a writable `--workspace` path."],
            debug_detail="debug-info",
        )
        payload = _build_cli_error_payload(exc, verbose=True)

        self.assertEqual(payload["message"], "Workspace path is not writable")
        self.assertEqual(payload["next_steps"], ["Choose a writable `--workspace` path."])
        self.assertEqual(payload["debug_detail"], "debug-info")

    def test_build_payload_from_module_not_found_adds_install_hint(self):
        exc = ModuleNotFoundError("No module named 'loguru'")
        exc.name = "loguru"
        payload = _build_cli_error_payload(exc, verbose=False)

        self.assertEqual(payload["message"], "Missing dependency: loguru")
        self.assertTrue(payload["next_steps"])

    def test_validate_request_options_rejects_file_workspace(self):
        with tempfile.NamedTemporaryFile() as handle:
            with self.assertRaises(CLIError) as ctx:
                validate_cli_request_options(workspace=handle.name, max_loop_count=50)
        self.assertIn("not a directory", str(ctx.exception))

    def test_validate_request_options_requires_positive_loop_count(self):
        with self.assertRaises(CLIError) as ctx:
            validate_cli_request_options(workspace=None, max_loop_count=0)
        self.assertIn("Invalid max loop count", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
