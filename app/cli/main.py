import argparse
import asyncio
import json
import re
import sys
import time
import traceback
import uuid
from typing import Any, Dict, Iterable, List, Optional


CHAT_COMMAND_HELP = (
    "built-in commands:\n"
    "  /help     show this help\n"
    "  /session  print the current session id\n"
    "  /exit     leave the session\n"
    "  /quit     leave the session"
)

TOOL_NAME_TAG_PATTERN = re.compile(r"<tool_name>\s*([A-Za-z0-9_.-]+)\s*</tool_name>")
TOOL_CALL_FUNCTION_PATTERN = re.compile(r"<call\s+function=\"([A-Za-z0-9_.-]+)\"")
TOOL_RESULT_NAME_PATTERN = re.compile(r"<function_result\s+name=\"([A-Za-z0-9_.-]+)\"")
SKILL_TAG_PATTERN = re.compile(r"<skill>\s*([A-Za-z0-9_.-]+)\s*</skill>", re.DOTALL)
SKILL_INPUT_TAG_PATTERN = re.compile(r"<skill_input>", re.DOTALL)
SKILL_RESULT_TAG_PATTERN = re.compile(r"<skill_result>", re.DOTALL)


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


def _print_provider_summary(provider: Optional[Dict[str, Any]], *, prefix: str = "provider") -> None:
    if not provider:
        print(f"{prefix}: (none)")
        return
    print(f"{prefix}_id: {provider.get('id') or '(pending)'}")
    print(f"name: {provider.get('name') or '(unnamed)'}")
    print(f"model: {provider.get('model')}")
    print(f"base_url: {provider.get('base_url')}")
    print(f"api_key: {provider.get('api_key_preview') or '(hidden)'}")
    print(f"is_default: {provider.get('is_default')}")
    if provider.get("user_id") is not None:
        print(f"user_id: {provider.get('user_id')}")
    if provider.get("created_at"):
        print(f"created_at: {provider.get('created_at')}")
    if provider.get("updated_at"):
        print(f"updated_at: {provider.get('updated_at')}")


def _add_provider_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", help="Provider display name")
    parser.add_argument("--base-url", dest="base_url", help="Provider base URL")
    parser.add_argument("--api-key", dest="api_key", help="Provider API key")
    parser.add_argument("--model", help="Provider model name")
    parser.add_argument("--max-tokens", dest="max_tokens", type=int)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--top-p", dest="top_p", type=float)
    parser.add_argument("--presence-penalty", dest="presence_penalty", type=float)
    parser.add_argument("--max-model-len", dest="max_model_len", type=int)

    multimodal_group = parser.add_mutually_exclusive_group()
    multimodal_group.add_argument(
        "--supports-multimodal",
        dest="supports_multimodal",
        action="store_true",
        help="Mark the provider as multimodal-capable",
    )
    multimodal_group.add_argument(
        "--no-supports-multimodal",
        dest="supports_multimodal",
        action="store_false",
        help="Mark the provider as not multimodal-capable",
    )

    structured_group = parser.add_mutually_exclusive_group()
    structured_group.add_argument(
        "--supports-structured-output",
        dest="supports_structured_output",
        action="store_true",
        help="Mark the provider as supporting structured output",
    )
    structured_group.add_argument(
        "--no-supports-structured-output",
        dest="supports_structured_output",
        action="store_false",
        help="Mark the provider as not supporting structured output",
    )

    default_group = parser.add_mutually_exclusive_group()
    default_group.add_argument(
        "--set-default",
        dest="is_default",
        action="store_true",
        help="Mark the provider as default",
    )
    default_group.add_argument(
        "--unset-default",
        dest="is_default",
        action="store_false",
        help="Mark the provider as non-default",
    )
    parser.set_defaults(
        supports_multimodal=None,
        supports_structured_output=None,
        is_default=None,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    from app.cli.service import get_default_cli_max_loop_count, get_default_cli_user_id

    parser = argparse.ArgumentParser(prog="sage", description="Sage CLI MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)
    default_user_id = get_default_cli_user_id()
    default_max_loop_count = get_default_cli_max_loop_count()

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
    run_parser.add_argument(
        "--max-loop-count",
        dest="max_loop_count",
        type=int,
        default=default_max_loop_count,
        help=f"Maximum agent loop count (default: {default_max_loop_count})",
    )
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
    chat_parser.add_argument(
        "--max-loop-count",
        dest="max_loop_count",
        type=int,
        default=default_max_loop_count,
        help=f"Maximum agent loop count per turn (default: {default_max_loop_count})",
    )
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
    resume_parser.add_argument(
        "--max-loop-count",
        dest="max_loop_count",
        type=int,
        default=default_max_loop_count,
        help=f"Maximum agent loop count per turn (default: {default_max_loop_count})",
    )
    resume_parser.add_argument("--json", action="store_true", help="Print raw JSON events")
    resume_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")
    resume_parser.add_argument("--stats", action="store_true", help="Print execution summary for each turn")

    doctor_parser = subparsers.add_parser("doctor", help="Show local CLI/runtime configuration")
    doctor_parser.add_argument("--probe-provider", action="store_true", help="Run a lightweight connection probe against the default provider")
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
    skills_parser.add_argument("--agent-id", dest="agent_id", help="Show the skills currently available to a specific agent")
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

    provider_parser = subparsers.add_parser("provider", help="Manage local LLM providers")
    provider_subparsers = provider_parser.add_subparsers(dest="provider_command", required=True)

    provider_list_parser = provider_subparsers.add_parser("list", help="List providers visible to a CLI user")
    provider_list_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    provider_list_parser.add_argument(
        "--default-only",
        action="store_true",
        help="Show only default providers for the selected user",
    )
    provider_list_parser.add_argument("--model", help="Filter by exact model name")
    provider_list_parser.add_argument("--name-contains", dest="name_contains", help="Filter by provider name substring")
    provider_list_parser.add_argument("--json", action="store_true", help="Print providers as JSON")
    provider_list_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")

    provider_inspect_parser = provider_subparsers.add_parser("inspect", help="Inspect a specific provider")
    provider_inspect_parser.add_argument("provider_id", help="Provider id to inspect")
    provider_inspect_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    provider_inspect_parser.add_argument("--json", action="store_true", help="Print provider details as JSON")
    provider_inspect_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")

    provider_verify_parser = provider_subparsers.add_parser(
        "verify",
        help="Probe a provider configuration without saving it",
    )
    _add_provider_config_args(provider_verify_parser)
    provider_verify_parser.add_argument("--json", action="store_true", help="Print verification result as JSON")
    provider_verify_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")

    provider_create_parser = provider_subparsers.add_parser(
        "create",
        help="Create a provider; omitted API settings fall back to current default CLI env",
    )
    provider_create_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    _add_provider_config_args(provider_create_parser)
    provider_create_parser.add_argument("--json", action="store_true", help="Print saved provider as JSON")
    provider_create_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")

    provider_update_parser = provider_subparsers.add_parser(
        "update",
        help="Update an existing provider; only supplied fields are changed",
    )
    provider_update_parser.add_argument("provider_id", help="Provider id to update")
    provider_update_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    _add_provider_config_args(provider_update_parser)
    provider_update_parser.add_argument("--json", action="store_true", help="Print updated provider as JSON")
    provider_update_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")

    provider_delete_parser = provider_subparsers.add_parser("delete", help="Delete an existing provider")
    provider_delete_parser.add_argument("provider_id", help="Provider id to delete")
    provider_delete_parser.add_argument("--user-id", dest="user_id", default=default_user_id)
    provider_delete_parser.add_argument("--json", action="store_true", help="Print deletion result as JSON")
    provider_delete_parser.add_argument("--verbose", action="store_true", help="Show runtime logs")
    return parser


def _print_plain_event(event: Dict[str, Any]) -> None:
    event_type = event.get("type")
    if event_type == "stream_end":
        if not sys.stdout.isatty():
            return
        sys.stdout.write("\n")
        sys.stdout.flush()
        return

    names = _collect_event_tool_names(event)
    if names:
        if event.get("tool_calls"):
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
        "_tool_tag_buffer": "",
    }


def _collect_event_tool_names(event: Dict[str, Any], *, content_buffer: str = "") -> List[str]:
    tool_names: List[str] = []

    tool_calls = event.get("tool_calls") or []
    for tool_call in tool_calls:
        function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        name = function.get("name")
        if name:
            tool_names.append(name)

    metadata = event.get("metadata") or {}
    metadata_tool_name = metadata.get("tool_name")
    if isinstance(metadata_tool_name, str) and metadata_tool_name:
        tool_names.append(metadata_tool_name)

    event_tool_name = event.get("tool_name")
    if isinstance(event_tool_name, str) and event_tool_name:
        tool_names.append(event_tool_name)

    combined_content = content_buffer
    content = event.get("content")
    if isinstance(content, str) and content:
        combined_content += content
    if combined_content:
        for match in TOOL_NAME_TAG_PATTERN.findall(combined_content):
            if match:
                tool_names.append(match.strip())
        for match in TOOL_CALL_FUNCTION_PATTERN.findall(combined_content):
            if match:
                tool_names.append(match.strip())
        for match in TOOL_RESULT_NAME_PATTERN.findall(combined_content):
            if match:
                tool_names.append(match.strip())
        for match in SKILL_TAG_PATTERN.findall(combined_content):
            if match:
                tool_names.append(match.strip())

    return sorted(set(tool_names))


def _record_stats_event(stats: Dict[str, Any], event: Dict[str, Any], start_time: float) -> None:
    session_id = event.get("session_id")
    if session_id and not stats["session_id"]:
        stats["session_id"] = session_id

    has_visible_output = False
    content = event.get("content")
    if isinstance(content, str) and content:
        has_visible_output = True
        buffer = (stats.get("_tool_tag_buffer") or "") + content
        stats["_tool_tag_buffer"] = buffer[-2048:]

    tool_names = _collect_event_tool_names(event, content_buffer=stats.get("_tool_tag_buffer") or "")
    if tool_names:
        has_visible_output = True
        existing_tool_names = set(stats["tools"])
        existing_tool_names.update(tool_names)
        stats["tools"] = sorted(existing_tool_names)
    elif stats.get("_tool_tag_buffer"):
        buffer = stats["_tool_tag_buffer"]
        if SKILL_INPUT_TAG_PATTERN.search(buffer) or SKILL_RESULT_TAG_PATTERN.search(buffer):
            has_visible_output = True

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


async def _build_request(args: argparse.Namespace, task: str):
    from app.cli.service import build_run_request, validate_requested_skills

    skills = await validate_requested_skills(
        requested_skills=args.skills,
        user_id=args.user_id,
        agent_id=args.agent_id,
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
    from app.cli.service import cli_runtime, validate_cli_request_options, validate_cli_runtime_requirements

    validate_cli_runtime_requirements()
    validate_cli_request_options(workspace=args.workspace, max_loop_count=args.max_loop_count)
    async with cli_runtime(verbose=args.verbose):
        request = await _build_request(args, args.task)
        await _stream_request(request, args.json, args.stats, workspace=args.workspace)
    return 0


async def _chat_command(args: argparse.Namespace) -> int:
    from app.cli.service import (
        cli_db_runtime,
        cli_runtime,
        get_session_summary,
        validate_cli_request_options,
        validate_cli_runtime_requirements,
    )

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

    validate_cli_runtime_requirements()
    validate_cli_request_options(workspace=args.workspace, max_loop_count=args.max_loop_count)
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

            request = await _build_request(args, prompt)
            await _stream_request(request, args.json, args.stats, workspace=args.workspace)
    return 0


async def _resume_command(args: argparse.Namespace) -> int:
    return await _chat_command(args)


async def _doctor_command(args: argparse.Namespace) -> int:
    from app.cli.service import collect_doctor_info, probe_default_provider

    info = collect_doctor_info()
    if args.probe_provider:
        info["provider_probe"] = await probe_default_provider()
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


def _build_cli_error_payload(exc: Exception, *, verbose: bool) -> Dict[str, Any]:
    from app.cli.service import CLIError
    try:
        from common.core.exceptions import SageHTTPException
    except Exception:  # noqa: BLE001
        SageHTTPException = None  # type: ignore[assignment]

    if isinstance(exc, CLIError):
        return {
            "type": "cli_error",
            "message": str(exc),
            "next_steps": list(exc.next_steps),
            "debug_detail": exc.debug_detail if verbose else None,
            "exit_code": exc.exit_code,
        }

    if SageHTTPException is not None and isinstance(exc, SageHTTPException):
        return {
            "type": "cli_error",
            "message": exc.detail or "Sage request failed",
            "next_steps": [],
            "debug_detail": exc.error_detail if verbose and exc.error_detail else None,
            "exit_code": 1,
        }

    if isinstance(exc, ModuleNotFoundError):
        return {
            "type": "cli_error",
            "message": f"Missing dependency: {exc.name}",
            "next_steps": ["Install project dependencies first, for example: `pip install -e .`."],
            "debug_detail": None,
            "exit_code": 1,
        }

    if isinstance(exc, PermissionError):
        return {
            "type": "cli_error",
            "message": str(exc) or "Permission denied",
            "next_steps": ["Check file permissions, selected user id, and agent visibility."],
            "debug_detail": traceback.format_exc() if verbose else None,
            "exit_code": 1,
        }

    if isinstance(exc, FileNotFoundError):
        return {
            "type": "cli_error",
            "message": str(exc) or "File not found",
            "next_steps": ["Check the file or workspace path and try again."],
            "debug_detail": traceback.format_exc() if verbose else None,
            "exit_code": 1,
        }

    if isinstance(exc, (NotADirectoryError, OSError, RuntimeError, ValueError)):
        return {
            "type": "cli_error",
            "message": str(exc) or exc.__class__.__name__,
            "next_steps": [],
            "debug_detail": traceback.format_exc() if verbose else None,
            "exit_code": 1,
        }

    return {
        "type": "cli_error",
        "message": f"Unexpected CLI error: {exc}",
        "next_steps": ["Retry with `--verbose` to inspect the full error detail."],
        "debug_detail": traceback.format_exc() if verbose else None,
        "exit_code": 1,
    }


def _emit_cli_error(args: argparse.Namespace, payload: Dict[str, Any]) -> int:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
        return int(payload.get("exit_code", 1))

    sys.stderr.write(f"{payload.get('message')}\n")
    next_steps = payload.get("next_steps") or []
    if next_steps:
        sys.stderr.write("Next steps:\n")
        for item in next_steps:
            sys.stderr.write(f"- {item}\n")
    debug_detail = payload.get("debug_detail")
    if debug_detail:
        sys.stderr.write("\n[debug]\n")
        sys.stderr.write(f"{debug_detail.rstrip()}\n")
    sys.stderr.flush()
    return int(payload.get("exit_code", 1))


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


async def _skills_command(args: argparse.Namespace) -> int:
    from app.cli.service import cli_db_runtime, list_available_skills

    if args.agent_id:
        async with cli_db_runtime(verbose=False):
            result = await list_available_skills(
                user_id=args.user_id,
                agent_id=args.agent_id,
                workspace=args.workspace,
            )
    else:
        result = await list_available_skills(
            user_id=args.user_id,
            agent_id=None,
            workspace=args.workspace,
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"user_id: {result['user_id']}")
    if result.get("agent_id"):
        print(f"agent_id: {result['agent_id']}")
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


async def _provider_command(args: argparse.Namespace) -> int:
    from app.cli.service import (
        cli_db_runtime,
        create_cli_provider,
        delete_cli_provider,
        inspect_cli_provider,
        query_cli_providers,
        update_cli_provider,
        verify_cli_provider,
    )

    if args.provider_command == "list":
        async with cli_db_runtime(verbose=args.verbose):
            result = await query_cli_providers(
                user_id=args.user_id,
                default_only=args.default_only,
                model=args.model,
                name_contains=args.name_contains,
            )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        print(f"user_id: {result['user_id']}")
        print(f"total: {result['total']}")
        filters = result.get("filters") or {}
        active_filters = [
            f"default_only={filters.get('default_only')}" if filters.get("default_only") else None,
            f"model={filters.get('model')}" if filters.get("model") else None,
            f"name_contains={filters.get('name_contains')}" if filters.get("name_contains") else None,
        ]
        active_filters = [item for item in active_filters if item]
        if active_filters:
            print(f"filters: {', '.join(active_filters)}")
        providers = result.get("list") or []
        if not providers:
            print("providers:\n  (none)")
            return 0
        print("providers:")
        for item in providers:
            print(
                f"  - {item.get('id')} | {item.get('name')} | "
                f"{item.get('model')} | default={item.get('is_default')} | {item.get('base_url')}"
            )
            print(f"    api_key: {item.get('api_key_preview') or '(hidden)'}")
        return 0

    if args.provider_command == "inspect":
        async with cli_db_runtime(verbose=args.verbose):
            result = await inspect_cli_provider(provider_id=args.provider_id, user_id=args.user_id)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        print(f"user_id: {result['user_id']}")
        print(f"provider_id: {result['provider_id']}")
        _print_provider_summary(result.get("provider"))
        return 0

    common_kwargs = {
        "name": getattr(args, "name", None),
        "base_url": getattr(args, "base_url", None),
        "api_key": getattr(args, "api_key", None),
        "model": getattr(args, "model", None),
        "max_tokens": getattr(args, "max_tokens", None),
        "temperature": getattr(args, "temperature", None),
        "top_p": getattr(args, "top_p", None),
        "presence_penalty": getattr(args, "presence_penalty", None),
        "max_model_len": getattr(args, "max_model_len", None),
        "supports_multimodal": getattr(args, "supports_multimodal", None),
        "supports_structured_output": getattr(args, "supports_structured_output", None),
        "is_default": getattr(args, "is_default", None),
    }

    if args.provider_command == "verify":
        result = await verify_cli_provider(**common_kwargs)
    elif args.provider_command == "create":
        async with cli_db_runtime(verbose=args.verbose):
            result = await create_cli_provider(user_id=args.user_id, **common_kwargs)
    elif args.provider_command == "update":
        async with cli_db_runtime(verbose=args.verbose):
            result = await update_cli_provider(
                provider_id=args.provider_id,
                user_id=args.user_id,
                **common_kwargs,
            )
    elif args.provider_command == "delete":
        async with cli_db_runtime(verbose=args.verbose):
            result = await delete_cli_provider(provider_id=args.provider_id, user_id=args.user_id)
    else:
        raise ValueError(f"Unsupported provider command: {args.provider_command}")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"status: {result.get('status')}")
    print(f"message: {result.get('message')}")
    if result.get("user_id"):
        print(f"user_id: {result.get('user_id')}")
    if result.get("provider_id"):
        print(f"provider_id: {result.get('provider_id')}")
    if result.get("deleted"):
        print("deleted: true")
        return 0
    sources = result.get("sources") or {}
    if sources:
        print("sources:")
        for key, value in sources.items():
            print(f"  {key}: {value}")
    _print_provider_summary(result.get("provider"))
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
            return await _doctor_command(args)
        if args.command == "sessions":
            return await _sessions_command(args)
        if args.command == "skills":
            return await _skills_command(args)
        if args.command == "config" and args.config_command == "show":
            return _config_show_command(args)
        if args.command == "config" and args.config_command == "init":
            return _config_init_command(args)
        if args.command == "provider":
            return await _provider_command(args)
        raise ValueError(f"Unsupported command: {args.command}")
    except Exception as exc:
        return _emit_cli_error(args, _build_cli_error_payload(exc, verbose=getattr(args, "verbose", False)))


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
