"""Combined command discovery; runtime dispatch uses version-owned parsers."""
import argparse


def build_argument_parser():
    from app.v1.cli.parser import build_argument_parser as build_v1
    from app.v2.cli.parser import add_v2_parser
    parser = build_v1()
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    tui_parser = subparsers.add_parser("tui", help="Start the Sage Terminal TUI")
    tui_parser.add_argument(
        "terminal_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the terminal TUI, e.g. --workspace /path/to/repo",
    )

    add_v2_parser(subparsers)
    return parser
