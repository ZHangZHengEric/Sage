"""Public sage command: load only the selected application implementation."""
import sys


def main(argv=None):
    args = list(argv) if argv is not None else sys.argv[1:]
    if args and args[0] == "v2":
        from app.v2.cli.main import main as run
    elif args and args[0] == "tui":
        import argparse
        from clients.cli.tui import tui_command
        from clients.cli.errors import CLIError
        try:
            return tui_command(argparse.Namespace(command="tui", terminal_args=args[1:]))
        except CLIError as exc:
            print(str(exc), file=sys.stderr)
            for step in exc.next_steps:
                print(step, file=sys.stderr)
            return exc.exit_code
    elif not args or args[0] in {"-h", "--help"}:
        from clients.cli.parser import build_argument_parser
        build_argument_parser().parse_args(args)
        return 0
    else:
        from app.v1.cli.main import main as run
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
