"""Public command discovery: v2 by default, explicit v1 compatibility."""
import argparse


def build_argument_parser():
    from app.v2.cli.config import get_default_cli_user_id
    from app.v2.cli.parser import _add_v2_parser, add_v2_parser

    parser = argparse.ArgumentParser(prog="sage", description="Sage CLI (default runtime: v2)")
    subparsers = parser.add_subparsers(dest="command")
    _add_v2_parser(subparsers, default_user_id=get_default_cli_user_id())
    # Default command namespaces match the explicit v2 command group.
    for name, command_parser in subparsers.choices.items():
        command_parser.set_defaults(command="v2", v2_command=name)
    add_v2_parser(subparsers)
    v1_parser = subparsers.add_parser("v1", help="Use the legacy v1 CLI", add_help=False)
    v1_parser.add_argument("legacy_args", nargs=argparse.REMAINDER)
    tui_parser = subparsers.add_parser("tui", help="Start the terminal UI (default runtime: v2)")
    tui_parser.add_argument("terminal_args", nargs=argparse.REMAINDER)
    return parser
