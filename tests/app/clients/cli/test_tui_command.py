import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import pytest

import app.clients.cli.tui as tui
import app.clients.cli.main as cli_main


class TestCliTuiCommand(unittest.TestCase):
    @pytest.mark.timeout(10)
    @unittest.skipIf(os.name == "nt", "POSIX source launcher")
    def test_source_launcher_finds_compiled_terminal_and_runtime_root(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder).resolve()
            terminal = repo / "app/clients/terminal"
            (terminal / "scripts").mkdir(parents=True)
            launcher = terminal / "scripts/run-sage-terminal.sh"
            source = Path(tui.__file__).resolve().parents[1] / "terminal/scripts/run-sage-terminal.sh"
            shutil.copyfile(source, launcher)
            binary = terminal / "target/debug/sage-terminal"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nprintf 'source-terminal-ran\\n'\n")
            binary.chmod(0o755)
            main = repo / "app/clients/cli/main.py"
            main.parent.mkdir(parents=True)
            main.write_text("# runtime entry\n")
            env = {key: value for key, value in os.environ.items() if not key.startswith("SAGE_")}
            result = subprocess.run(
                ["sh", str(launcher), "--help"], env={**env, "SAGE_TERMINAL_DEBUG_LAUNCH": "1"},
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"SAGE_TERMINAL_RUNTIME_ROOT={repo}", result.stdout)
            self.assertIn("source-terminal-ran", result.stdout)

    def test_tui_command_forwards_arguments_in_order(self):
        with patch(
            "app.clients.cli.tui.resolve_terminal_binary",
            return_value=Path("/tmp/sage-terminal"),
        ):
            with patch("app.clients.cli.tui.subprocess.call", return_value=0) as call:
                exit_code = cli_main.main(
                    [
                        "tui",
                        "--agent-config",
                        "coding",
                        "--workspace",
                        "/tmp/demo",
                        "--display",
                        "compact",
                        "chat",
                        "hello",
                    ]
                )

        self.assertEqual(exit_code, 0)
        call.assert_called_once()
        argv = call.call_args.args[0]
        self.assertEqual(
            argv,
            [
                "/tmp/sage-terminal",
                "--agent-config",
                "coding",
                "--workspace",
                "/tmp/demo",
                "--display",
                "compact",
                "chat",
                "hello",
            ],
        )
        self.assertIn("SAGE_PYTHON", call.call_args.kwargs["env"])

    def test_tui_command_does_not_parse_terminal_arguments_in_python(self):
        with patch(
            "app.clients.cli.tui.resolve_terminal_binary",
            return_value=Path("/tmp/sage-terminal"),
        ):
            with patch("app.clients.cli.tui.subprocess.call", return_value=0) as call:
                exit_code = cli_main.main(
                    [
                        "tui",
                        "--future-rust-only-flag",
                        "value",
                        "--help",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            call.call_args.args[0],
            [
                "/tmp/sage-terminal",
                "--future-rust-only-flag",
                "value",
                "--help",
            ],
        )

    def test_tui_command_requires_terminal_binary(self):
        with patch("app.clients.cli.tui.resolve_terminal_binary", return_value=None):
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                exit_code = cli_main.main(["tui"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Sage Terminal TUI binary was not found.", stderr.getvalue())
        self.assertIn(
            "includes the Terminal TUI launcher and binary", stderr.getvalue()
        )

    def test_terminal_resolver_prefers_packaged_launcher_before_source_target(self):
        with patch(
            "app.clients.cli.tui._package_terminal_candidates"
        ) as package_candidates:
            with patch("os.access", return_value=True):
                with patch("pathlib.Path.is_file", return_value=True):
                    package_candidates.return_value = [
                        Path("/pkg/bin/run-sage-terminal.sh")
                    ]

                    result = tui.resolve_terminal_binary(
                        path_lookup=None,
                        repo_root=Path("/repo"),
                    )

        self.assertEqual(result, Path("/pkg/bin/run-sage-terminal.sh"))

    def test_terminal_resolver_keeps_explicit_env_override_first(self):
        with patch(
            "app.clients.cli.tui._package_terminal_candidates"
        ) as package_candidates:
            with patch("os.access", return_value=True):
                with patch("pathlib.Path.is_file", return_value=True):
                    package_candidates.return_value = [Path("/pkg/bin/sage-terminal")]

                    result = tui.resolve_terminal_binary(
                        env_value="/custom/sage-terminal",
                        path_lookup="/usr/local/bin/sage-terminal",
                        repo_root=Path("/repo"),
                    )

        self.assertEqual(result, Path("/custom/sage-terminal"))


if __name__ == "__main__":
    unittest.main()
