import argparse
from app.v2.cli.config import get_default_cli_user_id

def add_v2_parser(subparsers):
    default_user_id = get_default_cli_user_id()
    v2_parser = subparsers.add_parser("v2", help="Manage SAgents v2 runtime data")
    v2_subparsers = v2_parser.add_subparsers(dest="v2_command", required=True)
    v2_migrate = v2_subparsers.add_parser(
        "migrate", help="Explicitly migrate a v3 SessionStore to v4"
    )
    v2_migrate.add_argument("--runtime-root", required=True)
    v2_migrate.add_argument("--dry-run", action="store_true")
    v2_migrate.add_argument(
        "--manifest",
        default=None,
        help="Also generate sage.v2.yaml from this sage/v1 manifest",
    )
    v2_migrate.add_argument("--verbose", action="store_true")

    _add_v2_parser(v2_subparsers, default_user_id=default_user_id)

def build_argument_parser():
    parser = argparse.ArgumentParser(prog="sage")
    add_v2_parser(parser.add_subparsers(dest="command", required=True))
    return parser

def _add_v2_common_args(parser: argparse.ArgumentParser, *, default_user_id: str) -> None:
    from app.v2.cli.package import DEFAULT_PRESET, available_presets

    parser.add_argument(
        "--preset",
        dest="preset",
        choices=list(available_presets()),
        default=DEFAULT_PRESET,
        help=f"Built-in agent preset used when no --package is given (default: {DEFAULT_PRESET})",
    )
    parser.add_argument(
        "--package",
        dest="package",
        help="Path to a sage.yaml agent package (overrides --preset and model env config)",
    )
    parser.add_argument(
        "--workspace",
        dest="workspace",
        help="Workspace directory exposed to the sandbox (default: current directory)",
    )
    parser.add_argument(
        "--session-root",
        dest="session_root",
        help="Directory for the v2 session store (default: ~/.sage/v2/runtime)",
    )
    parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    parser.add_argument(
        "--approval-mode",
        dest="approval_mode",
        choices=["ask", "always", "approve-all", "deny-all"],
        default=None,
        help=(
            "How tool approvals are handled: ask = approve write-class tools "
            "(default on a TTY; deny-all otherwise), always = confirm every tool "
            "call, approve-all = never ask, deny-all = deny everything that asks"
        ),
    )
    parser.add_argument(
        "--read-only",
        dest="read_only",
        action="store_true",
        help="Restrict the sandbox to read/list operations and read-only shell commands",
    )
    parser.add_argument(
        "--mode",
        dest="mode",
        choices=["normal", "plan", "goal"],
        default="normal",
        help=(
            "v2 invocation mode: plan = inspect only (read-only sandbox) and submit a "
            "plan for approval; goal = must explicitly report completion"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print native v2 events as NDJSON and read approval decisions from stdin",
    )
    parser.add_argument("--verbose", action="store_true", help="Show runtime logs")


def _add_v2_parser(v2_subparsers, *, default_user_id: str) -> None:
    """在已有的 ``sage v2`` 子命令组上挂载进程内运行相关的子命令。"""

    run_parser = v2_subparsers.add_parser(
        "run", help="Run a single task in-process on the v2 runtime"
    )
    run_parser.add_argument("task", help="Task prompt to execute")
    run_parser.add_argument(
        "--session-id",
        dest="session_id",
        help="Continue an existing v2 session instead of creating a new one",
    )
    _add_v2_common_args(run_parser, default_user_id=default_user_id)

    chat_parser = v2_subparsers.add_parser(
        "chat", help="Start an interactive multi-turn session on the v2 runtime"
    )
    chat_parser.add_argument(
        "--session-id",
        dest="session_id",
        help="Continue an existing v2 session instead of creating a new one",
    )
    _add_v2_common_args(chat_parser, default_user_id=default_user_id)

    resume_parser = v2_subparsers.add_parser(
        "resume", help="Resume an existing v2 session interactively"
    )
    resume_parser.add_argument("session_id", help="v2 session id to resume")
    _add_v2_common_args(resume_parser, default_user_id=default_user_id)

    sessions_parser = v2_subparsers.add_parser(
        "sessions", help="List v2 sessions under a session root"
    )
    sessions_parser.add_argument(
        "--limit", type=int, default=20, help="Maximum number of sessions to show"
    )
    sessions_parser.add_argument(
        "--session-root",
        dest="session_root",
        help="Directory of the v2 session store (default: ~/.sage/v2/runtime)",
    )
    sessions_parser.add_argument(
        "--json", action="store_true", help="Print sessions as JSON"
    )
    sessions_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_command")
    inspect_parser = sessions_subparsers.add_parser(
        "inspect", help="Replay the user/assistant transcript of one v2 session"
    )
    inspect_parser.add_argument("session_id", help="v2 session id to inspect")
    inspect_parser.add_argument(
        "--session-root",
        dest="session_root",
        help="Directory of the v2 session store (default: ~/.sage/v2/runtime)",
    )
    inspect_parser.add_argument(
        "--json", action="store_true", help="Print the transcript as JSON"
    )
    inspect_parser.add_argument(
        "--verbose", action="store_true", help="Show runtime logs"
    )

    approvals_parser = v2_subparsers.add_parser(
        "approvals",
        help="List tool approvals remembered for a workspace (session-scoped ones live in chat)",
    )
    _add_v2_approvals_args(approvals_parser)
    approvals_subparsers = approvals_parser.add_subparsers(dest="approvals_command")
    forget_parser = approvals_subparsers.add_parser(
        "forget", help="Forget one remembered approval (<n> from the list) or all of them"
    )
    forget_parser.add_argument("selector", help="Entry number from `sage v2 approvals`, or `all`")
    _add_v2_approvals_args(forget_parser)


def _add_v2_approvals_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        dest="workspace",
        help="Workspace directory the approvals belong to (default: current directory)",
    )
    parser.add_argument(
        "--session-root",
        dest="session_root",
        help="Directory of the v2 session store (default: ~/.sage/v2/runtime)",
    )
    parser.add_argument("--json", action="store_true", help="Print as JSON")
    parser.add_argument("--verbose", action="store_true", help="Show runtime logs")
