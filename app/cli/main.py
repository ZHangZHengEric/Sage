import argparse
import asyncio
import json
import sys
import time
import uuid
from typing import Any, Dict, Iterable, Optional


CHAT_COMMAND_HELP = (
    "built-in commands:\n"
    "  /help     show this help\n"
    "  /session  print the current session id\n"
    "  /exit     leave the session\n"
    "  /quit     leave the session"
)


def build_argument_parser() -> argparse.ArgumentParser:
    from app.cli.service import get_default_cli_user_id

    parser = argparse.ArgumentParser(prog="sage", description="Sage CLI MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)
    default_user_id = get_default_cli_user_id()

    run_parser = subparsers.add_parser("run", help="Run a single Sage task")
    run_parser.add_argument("task", help="Task prompt to execute")
    run_parser.add_argument("--session-id", dest="session_id")
    run_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    run_parser.add_argument("--agent-id", dest="agent_id")
    run_parser.add_argument(
        "--agent-mode",
        dest="agent_mode",
        choices=["simple", "multi", "fibre"],
        default="simple",
    )
    run_parser.add_argument("--json", action="store_true", help="Print raw JSON events")
    run_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")
    run_parser.add_argument("--stats", action="store_true", help="Print execution summary after completion")

    chat_parser = subparsers.add_parser("chat", help="Start an interactive Sage chat session")
    chat_parser.add_argument("--session-id", dest="session_id")
    chat_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    chat_parser.add_argument("--agent-id", dest="agent_id")
    chat_parser.add_argument(
        "--agent-mode",
        dest="agent_mode",
        choices=["simple", "multi", "fibre"],
        default="simple",
    )
    chat_parser.add_argument("--json", action="store_true", help="Print raw JSON events")
    chat_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")
    chat_parser.add_argument("--stats", action="store_true", help="Print execution summary for each turn")

    resume_parser = subparsers.add_parser("resume", help="Resume an existing Sage chat session")
    resume_parser.add_argument("session_id", help="Session id to resume")
    resume_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    resume_parser.add_argument("--agent-id", dest="agent_id")
    resume_parser.add_argument(
        "--agent-mode",
        dest="agent_mode",
        choices=["simple", "multi", "fibre"],
        default="simple",
    )
    resume_parser.add_argument("--json", action="store_true", help="Print raw JSON events")
    resume_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")
    resume_parser.add_argument("--stats", action="store_true", help="Print execution summary for each turn")

    doctor_parser = subparsers.add_parser("doctor", help="Show local CLI/runtime configuration")
    doctor_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")

    sessions_parser = subparsers.add_parser("sessions", help="List recent CLI sessions")
    sessions_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    sessions_parser.add_argument("--limit", type=int, default=20, help="Maximum number of sessions to show")
    sessions_parser.add_argument("--search", help="Filter sessions by title")
    sessions_parser.add_argument("--agent-id", dest="agent_id")
    sessions_parser.add_argument("--json", action="store_true", help="Print sessions as JSON")
    sessions_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")

    config_parser = subparsers.add_parser("config", help="Inspect CLI configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_show_parser = config_subparsers.add_parser("show", help="Show effective CLI config")
    config_show_parser.add_argument("--json", action="store_true", help="Print config as JSON")
    return parser


def _print_plain_event(event: Dict[str, Any]) -> None:
    event_type = event.get("type")
    if event_type == "stream_end":
        if not sys.stdout.isatty():
            return
        sys.stdout.write("\n")
        sys.stdout.flush()
        return

    tool_calls = event.get("tool_calls") or []
    if tool_calls:
        names = []
        for tool_call in tool_calls:
            function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            name = function.get("name")
            if name:
                names.append(name)
        if names:
            sys.stderr.write(f"\n[tool] {', '.join(names)}\n")
            sys.stderr.flush()

    content = event.get("content")
    role = event.get("role")
    if role == "assistant" and isinstance(content, str) and content:
        sys.stdout.write(content)
        sys.stdout.flush()
        return

    if event_type == "error":
        sys.stderr.write(f"\n[error] {event.get('content', 'Unknown error')}\n")
        sys.stderr.flush()


def _empty_stats() -> Dict[str, Any]:
    return {
        "session_id": None,
        "elapsed_seconds": 0.0,
        "first_output_seconds": None,
        "tools": [],
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "per_step_info": [],
    }


def _record_stats_event(stats: Dict[str, Any], event: Dict[str, Any], start_time: float) -> None:
    session_id = event.get("session_id")
    if session_id and not stats["session_id"]:
        stats["session_id"] = session_id

    has_visible_output = False
    content = event.get("content")
    if isinstance(content, str) and content:
        has_visible_output = True

    tool_calls = event.get("tool_calls") or []
    if tool_calls:
        has_visible_output = True
        tool_names = set(stats["tools"])
        for tool_call in tool_calls:
            function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            name = function.get("name")
            if name:
                tool_names.add(name)
        stats["tools"] = sorted(tool_names)

    if event.get("type") == "error":
        has_visible_output = True

    if has_visible_output and stats["first_output_seconds"] is None:
        stats["first_output_seconds"] = round(time.monotonic() - start_time, 3)

    if event.get("type") == "token_usage":
        token_usage = (event.get("metadata") or {}).get("token_usage") or {}
        stats["prompt_tokens"] = token_usage.get("prompt_tokens")
        stats["completion_tokens"] = token_usage.get("completion_tokens")
        stats["total_tokens"] = token_usage.get("total_tokens")
        stats["per_step_info"] = token_usage.get("per_step_info") or []


def _print_stats(stats: Dict[str, Any], *, json_output: bool) -> None:
    output_lines = [
        "",
        "[stats]",
        f"session_id: {stats.get('session_id') or '(unknown)'}",
        f"elapsed_seconds: {stats.get('elapsed_seconds'):.3f}",
    ]
    first_output = stats.get("first_output_seconds")
    if first_output is not None:
        output_lines.append(f"first_output_seconds: {first_output:.3f}")

    tools = stats.get("tools") or []
    output_lines.append(f"tools: {', '.join(tools) if tools else '(none)'}")

    if stats.get("total_tokens") is not None:
        output_lines.append(
            "tokens: "
            f"prompt={stats.get('prompt_tokens')}, "
            f"completion={stats.get('completion_tokens')}, "
            f"total={stats.get('total_tokens')}"
        )

    per_step_info = stats.get("per_step_info") or []
    if per_step_info:
        output_lines.append("per_step_usage:")
        for step in per_step_info:
            step_name = step.get("step_name", "unknown")
            usage = step.get("usage") or {}
            output_lines.append(
                "  - "
                f"{step_name}: prompt={usage.get('prompt_tokens')}, "
                f"completion={usage.get('completion_tokens')}, "
                f"total={usage.get('total_tokens')}"
            )

    stream = sys.stderr if json_output else sys.stdout
    stream.write("\n".join(output_lines) + "\n")
    stream.flush()


async def _stream_request(request, json_output: bool, stats_output: bool) -> int:
    from app.cli.service import run_request_stream

    start_time = time.monotonic()
    stats = _empty_stats()
    async for event in run_request_stream(request):
        _record_stats_event(stats, event, start_time)
        if json_output:
            print(json.dumps(event, ensure_ascii=False))
        else:
            _print_plain_event(event)
    stats["elapsed_seconds"] = round(time.monotonic() - start_time, 3)
    if stats_output:
        _print_stats(stats, json_output=json_output)
    return 0


def _build_request(args: argparse.Namespace, task: str):
    from app.cli.service import build_run_request

    return build_run_request(
        task=task,
        session_id=args.session_id,
        user_id=args.user_id,
        agent_id=args.agent_id,
        agent_mode=args.agent_mode,
    )


async def _run_command(args: argparse.Namespace) -> int:
    from app.cli.service import cli_runtime, validate_cli_runtime_requirements

    validate_cli_runtime_requirements()
    request = _build_request(args, args.task)
    async with cli_runtime(verbose=args.verbose):
        await _stream_request(request, args.json, args.stats)
    return 0


async def _chat_command(args: argparse.Namespace) -> int:
    from app.cli.service import cli_runtime, validate_cli_runtime_requirements

    if not args.session_id:
        args.session_id = str(uuid.uuid4())

    if not args.json:
        sys.stderr.write(
            f"session_id: {args.session_id}\n"
            "type /help for built-in commands\n"
        )
        sys.stderr.flush()

    validate_cli_runtime_requirements()
    async with cli_runtime(verbose=args.verbose):
        while True:
            try:
                prompt = input("> ").strip()
            except EOFError:
                if not args.json:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                break
            except KeyboardInterrupt:
                if not args.json:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                break

            if not prompt:
                continue
            if prompt in {"/exit", "/quit"}:
                break
            if prompt == "/help":
                print(CHAT_COMMAND_HELP)
                continue
            if prompt == "/session":
                print(args.session_id)
                continue

            request = _build_request(args, prompt)
            await _stream_request(request, args.json, args.stats)
    return 0


async def _resume_command(args: argparse.Namespace) -> int:
    return await _chat_command(args)


def _doctor_command() -> int:
    from app.cli.service import collect_doctor_info

    info = collect_doctor_info()
    for key, value in info.items():
        if isinstance(value, dict):
            print(f"{key}:")
            for sub_key, sub_value in value.items():
                print(f"  {sub_key}: {sub_value}")
            continue
        if isinstance(value, list):
            print(f"{key}:")
            if not value:
                print("  (none)")
                continue
            for item in value:
                print(f"  - {item}")
            continue
        print(f"{key}: {value}")
    return 0


async def _sessions_command(args: argparse.Namespace) -> int:
    from app.cli.service import cli_db_runtime, list_sessions

    async with cli_db_runtime(verbose=args.verbose):
        result = await list_sessions(
            user_id=args.user_id,
            limit=args.limit,
            search=args.search,
            agent_id=args.agent_id,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"user_id: {result['user_id']}")
    print(f"total: {result['total']}")
    print(f"limit: {result['limit']}")
    sessions = result.get("list") or []
    if not sessions:
        print("sessions:\n  (none)")
        return 0

    print("sessions:")
    for item in sessions:
        print(f"  - session_id: {item.get('session_id')}")
        print(f"    title: {item.get('title')}")
        print(f"    agent_name: {item.get('agent_name')}")
        print(f"    updated_at: {item.get('updated_at')}")
        print(f"    message_count: {item.get('message_count')}")
    return 0


def _config_show_command(args: argparse.Namespace) -> int:
    from app.cli.service import collect_config_info

    info = collect_config_info()
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    for key, value in info.items():
        if isinstance(value, dict):
            print(f"{key}:")
            for sub_key, sub_value in value.items():
                print(f"  {sub_key}: {sub_value}")
            continue
        print(f"{key}: {value}")
    return 0


async def _main_async(args: argparse.Namespace) -> int:
    try:
        if args.command == "run":
            return await _run_command(args)
        if args.command == "chat":
            return await _chat_command(args)
        if args.command == "resume":
            return await _resume_command(args)
        if args.command == "doctor":
            return _doctor_command()
        if args.command == "sessions":
            return await _sessions_command(args)
        if args.command == "config" and args.config_command == "show":
            return _config_show_command(args)
        raise ValueError(f"Unsupported command: {args.command}")
    except ModuleNotFoundError as exc:
        sys.stderr.write(
            f"Missing dependency: {exc.name}. Install project dependencies before using this command.\n"
        )
        sys.stderr.flush()
        return 1
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.stderr.flush()
        return 1
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.stderr.flush()
        return 1


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
