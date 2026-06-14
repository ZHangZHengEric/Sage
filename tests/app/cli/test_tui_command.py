import io
from pathlib import Path
import unittest
from unittest.mock import patch

import app.cli.commands.tui as tui
import app.cli.main as cli_main


class TestCliTuiCommand(unittest.TestCase):
    def test_tui_command_forwards_arguments_in_order(self):
        with patch(
            "app.cli.commands.tui.resolve_terminal_binary",
            return_value=Path("/tmp/sage-terminal"),
        ):
            with patch("app.cli.commands.tui.subprocess.call", return_value=0) as call:
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
            "app.cli.commands.tui.resolve_terminal_binary",
            return_value=Path("/tmp/sage-terminal"),
        ):
            with patch("app.cli.commands.tui.subprocess.call", return_value=0) as call:
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
        with patch("app.cli.commands.tui.resolve_terminal_binary", return_value=None):
            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                exit_code = cli_main.main(["tui"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Sage Terminal TUI binary was not found.", stderr.getvalue())
        self.assertIn("includes the Terminal TUI launcher and binary", stderr.getvalue())

    def test_terminal_resolver_prefers_packaged_launcher_before_source_target(self):
        with patch("app.cli.commands.tui._package_terminal_candidates") as package_candidates:
            with patch("os.access", return_value=True):
                with patch("pathlib.Path.is_file", return_value=True):
                    package_candidates.return_value = [Path("/pkg/bin/run-sage-terminal.sh")]

                    result = tui.resolve_terminal_binary(
                        path_lookup=None,
                        repo_root=Path("/repo"),
                    )

        self.assertEqual(result, Path("/pkg/bin/run-sage-terminal.sh"))

    def test_terminal_resolver_keeps_explicit_env_override_first(self):
        with patch("app.cli.commands.tui._package_terminal_candidates") as package_candidates:
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
