from pathlib import Path
import unittest
from unittest.mock import patch

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
                        "--workspace",
                        "/tmp/demo",
                        "--display",
                        "compact",
                        "chat",
                        "hello",
                    ]
                )

        self.assertEqual(exit_code, 0)
        call.assert_called_once_with(
            [
                "/tmp/sage-terminal",
                "--workspace",
                "/tmp/demo",
                "--display",
                "compact",
                "chat",
                "hello",
            ]
        )


if __name__ == "__main__":
    unittest.main()
