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


def _truncate(value: Optional[str], max_len: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _print_session_summary(summary: Dict[str, Any], *, prefix: str = "session") -> None:
    print(f"{prefix}_id: {summary.get('session_id')}")
    print(f"title: {_truncate(summary.get('title') or '(untitled)', 80)}")
    print(f"agent_name: {summary.get('agent_name')}")
    print(f"updated_at: {summary.get('updated_at')}")
    print(f"message_count: {summary.get('message_count')}")


def _print_message_preview(message: Optional[Dict[str, Any]], *, label: str) -> None:
    if not message:
        print(f"{label}: (none)")
        return
    role = message.get("role") or "unknown"
    message_type = message.get("type")
    content = _truncate(message.get("content") or "", 120)
    suffix = f" [{message_type}]" if message_type else ""
    print(f"{label}: [{role}]{suffix} {content}")


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
    run_parser.add_argument("--workspace", dest="workspace", help="Use a specific local workspace directory")
    run_parser.add_argument("--skill", dest="skills", action="append", default=[], help="Enable a skill by name (repeatable)")
    run_parser.add_argument(
        "--agent-mode",
        dest="agent_mode",
        choices=["simple", "multi", "fibre"],
        default="simple",
    )
    run_parser.add_argument("--max-loop-count", dest="max_loop_count", type=int, default=50)
    run_parser.add_argument("--json", action="store_true", help="Print raw JSON events")
    run_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")
    run_parser.add_argument("--stats", action="store_true", help="Print execution summary after completion")

    chat_parser = subparsers.add_parser("chat", help="Start an interactive Sage chat session")
    chat_parser.add_argument("--session-id", dest="session_id")
    chat_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    chat_parser.add_argument("--agent-id", dest="agent_id")
    chat_parser.add_argument("--workspace", dest="workspace", help="Use a specific local workspace directory")
    chat_parser.add_argument("--skill", dest="skills", action="append", default=[], help="Enable a skill by name (repeatable)")
    chat_parser.add_argument(
        "--agent-mode",
        dest="agent_mode",
        choices=["simple", "multi", "fibre"],
        default="simple",
    )
    chat_parser.add_argument("--max-loop-count", dest="max_loop_count", type=int, default=50)
    chat_parser.add_argument("--json", action="store_true", help="Print raw JSON events")
    chat_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")
    chat_parser.add_argument("--stats", action="store_true", help="Print execution summary for each turn")

    resume_parser = subparsers.add_parser("resume", help="Resume an existing Sage chat session")
    resume_parser.add_argument("session_id", help="Session id to resume")
    resume_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    resume_parser.add_argument("--agent-id", dest="agent_id")
    resume_parser.add_argument("--workspace", dest="workspace", help="Use a specific local workspace directory")
    resume_parser.add_argument("--skill", dest="skills", action="append", default=[], help="Enable a skill by name (repeatable)")
    resume_parser.add_argument(
        "--agent-mode",
        dest="agent_mode",
        choices=["simple", "multi", "fibre"],
        default="simple",
    )
    resume_parser.add_argument("--max-loop-count", dest="max_loop_count", type=int, default=50)
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
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_command")
    sessions_inspect_parser = sessions_subparsers.add_parser("inspect", help="Inspect a specific CLI session")
    sessions_inspect_parser.add_argument("session_id", help="Session id to inspect, or `latest`")
    sessions_inspect_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    sessions_inspect_parser.add_argument("--agent-id", dest="agent_id")
    sessions_inspect_parser.add_argument(
        "--messages",
        dest="message_limit",
        type=int,
        default=5,
        help="Number of recent messages to preview",
    )
    sessions_inspect_parser.add_argument("--json", action="store_true", help="Print session details as JSON")
    sessions_inspect_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")

    skills_parser = subparsers.add_parser("skills", help="List available CLI skills")
    skills_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    skills_parser.add_argument("--workspace", dest="workspace", help="Include skills from a specific workspace directory")
    skills_parser.add_argument("--json", action="store_true", help="Print skills as JSON")

    config_parser = subparsers.add_parser("config", help="Inspect CLI configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_show_parser = config_subparsers.add_parser("show", help="Show effective CLI config")
    config_show_parser.add_argument("--json", action="store_true", help="Print config as JSON")
    config_init_parser = config_subparsers.add_parser("init", help="Create a minimal local CLI config")
    config_init_parser.add_argument(
        "--path",
        default=None,
        help="Path to write the config file (defaults to ~/.sage/.sage_env)",
    )
    config_init_parser.add_argument("--force", action="store_true", help="Overwrite an existing config file")
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


def _empty_stats(*, request, workspace: Optional[str]) -> Dict[str, Any]:
    return {
        "session_id": getattr(request, "session_id", None),
        "user_id": getattr(request, "user_id", None),
        "agent_id": getattr(request, "agent_id", None),
        "agent_mode": getattr(request, "agent_mode", None),
        "workspace": workspace,
        "requested_skills": list(getattr(request, "available_skills", None) or []),
        "max_loop_count": getattr(request, "max_loop_count", None),
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
    if json_output:
        print(
            json.dumps(
                {
                    "type": "cli_stats",
                    "session_id": stats.get("session_id"),
                    "user_id": stats.get("user_id"),
                    "agent_id": stats.get("agent_id"),
                    "agent_mode": stats.get("agent_mode"),
                    "workspace": stats.get("workspace"),
                    "requested_skills": stats.get("requested_skills") or [],
                    "max_loop_count": stats.get("max_loop_count"),
                    "elapsed_seconds": stats.get("elapsed_seconds"),
                    "first_output_seconds": stats.get("first_output_seconds"),
                    "tools": stats.get("tools") or [],
                    "prompt_tokens": stats.get("prompt_tokens"),
                    "completion_tokens": stats.get("completion_tokens"),
                    "total_tokens": stats.get("total_tokens"),
                    "per_step_info": stats.get("per_step_info") or [],
                },
                ensure_ascii=False,
            )
        )
        return

    output_lines = [
        "",
        "[stats]",
        f"session_id: {stats.get('session_id') or '(unknown)'}",
        f"user_id: {stats.get('user_id') or '(unknown)'}",
        f"agent_mode: {stats.get('agent_mode') or '(unknown)'}",
        f"elapsed_seconds: {stats.get('elapsed_seconds'):.3f}",
    ]
    if stats.get("agent_id"):
        output_lines.append(f"agent_id: {stats.get('agent_id')}")
    if stats.get("workspace"):
        output_lines.append(f"workspace: {stats.get('workspace')}")
    first_output = stats.get("first_output_seconds")
    if first_output is not None:
        output_lines.append(f"first_output_seconds: {first_output:.3f}")
    requested_skills = stats.get("requested_skills") or []
    output_lines.append(
        f"requested_skills: {', '.join(requested_skills) if requested_skills else '(none)'}"
    )
    if stats.get("max_loop_count") is not None:
        output_lines.append(f"max_loop_count: {stats.get('max_loop_count')}")

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

    sys.stdout.write("\n".join(output_lines) + "\n")
    sys.stdout.flush()


async def _stream_request(request, json_output: bool, stats_output: bool, workspace: Optional[str] = None) -> int:
    from app.cli.service import run_request_stream

    start_time = time.monotonic()
    stats = _empty_stats(request=request, workspace=workspace)
    async for event in run_request_stream(request, workspace=workspace):
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
    from app.cli.service import build_run_request, validate_requested_skills

    skills = validate_requested_skills(
        requested_skills=args.skills,
        user_id=args.user_id,
        workspace=args.workspace,
    )

    return build_run_request(
        task=task,
        session_id=args.session_id,
        user_id=args.user_id,
        agent_id=args.agent_id,
        agent_mode=args.agent_mode,
        available_skills=skills or None,
        max_loop_count=args.max_loop_count,
    )


async def _run_command(args: argparse.Namespace) -> int:
    from app.cli.service import cli_runtime, validate_cli_runtime_requirements

    request = _build_request(args, args.task)
    validate_cli_runtime_requirements()
    async with cli_runtime(verbose=args.verbose):
        await _stream_request(request, args.json, args.stats, workspace=args.workspace)
    return 0


async def _chat_command(args: argparse.Namespace) -> int:
    from app.cli.service import cli_db_runtime, cli_runtime, get_session_summary, validate_cli_runtime_requirements

    if not args.session_id:
        args.session_id = str(uuid.uuid4())
    else:
        summary = None
        async with cli_db_runtime(verbose=args.verbose):
            summary = await get_session_summary(session_id=args.session_id, user_id=args.user_id)
        if summary and not args.json:
            _print_session_summary(summary, prefix="resume")
            print()

    if not args.json:
        sys.stderr.write(
            f"session_id: {args.session_id}\n"
            "type /help for built-in commands\n"
        )
        sys.stderr.flush()

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
            validate_cli_runtime_requirements()
            await _stream_request(request, args.json, args.stats, workspace=args.workspace)
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
    from app.cli.service import cli_db_runtime, inspect_session, list_sessions

    if args.sessions_command == "inspect":
        async with cli_db_runtime(verbose=args.verbose):
            result = await inspect_session(
                session_id=args.session_id,
                user_id=args.user_id,
                agent_id=args.agent_id,
                message_limit=args.message_limit,
            )

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        print("session:")
        _print_session_summary(result, prefix="session")
        print(f"user_id: {result.get('user_id')}")
        print(f"agent_id: {result.get('agent_id')}")
        print(f"created_at: {result.get('created_at')}")
        print(f"user_count: {result.get('user_count')}")
        print(f"agent_count: {result.get('agent_count')}")
        _print_message_preview(result.get("last_user_message"), label="last_user_message")
        _print_message_preview(result.get("last_assistant_message"), label="last_assistant_message")
        messages = result.get("recent_messages") or []
        print(f"recent_messages: {len(messages)}")
        if not messages:
            print("  (none)")
            return 0

        for item in messages:
            role = item.get("role") or "unknown"
            index = item.get("index")
            content = _truncate(item.get("content") or "", 120)
            print(f"  - #{index} [{role}] {content}")
        return 0

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
        session_id = item.get("session_id")
        title = _truncate(item.get("title") or "(untitled)", 56)
        updated_at = item.get("updated_at")
        agent_name = item.get("agent_name")
        message_count = item.get("message_count")
        print(
            f"  - {session_id} | {title} | "
            f"{agent_name} | updated={updated_at} | messages={message_count}"
        )
        last_message = item.get("last_message")
        if last_message:
            preview = _truncate(last_message.get("content") or "", 100)
            role = last_message.get("role") or "unknown"
            print(f"    last_message: [{role}] {preview}")
    return 0


def _skills_command(args: argparse.Namespace) -> int:
    from app.cli.service import list_available_skills

    result = list_available_skills(user_id=args.user_id, workspace=args.workspace)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"user_id: {result['user_id']}")
    if result.get("workspace"):
        print(f"workspace: {result['workspace']}")
    print(f"total: {result.get('total', 0)}")
    sources = result.get("sources") or []
    print("sources:")
    if not sources:
        print("  (none)")
    else:
        source_counts = result.get("source_counts") or {}
        for source in sources:
            source_name = source["source"]
            count = source_counts.get(source_name, 0)
            print(f"  - {source_name}: {source['path']} ({count})")

    skills = result.get("list") or []
    print("skills:")
    if not skills:
        print("  (none)")
    else:
        for item in skills:
            print(f"  - {item['name']} [{item['source']}]")
            print(f"    description: {_truncate(item.get('description') or '', 120)}")

    errors = result.get("errors") or []
    if errors:
        print("errors:")
        for item in errors:
            print(f"  - {item['source']}: {item['description']}")
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


def _config_init_command(args: argparse.Namespace) -> int:
    from app.cli.service import write_cli_config_file

    result = write_cli_config_file(path=args.path, force=args.force)
    print(f"config_file: {result['path']}")
    print(f"template: {result['template']}")
    print(f"overwritten: {result['overwritten']}")
    print("next_steps:")
    for item in result["next_steps"]:
        print(f"  - {item}")
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
        if args.command == "skills":
            return _skills_command(args)
        if args.command == "config" and args.config_command == "show":
            return _config_show_command(args)
        if args.command == "config" and args.config_command == "init":
            return _config_init_command(args)
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
