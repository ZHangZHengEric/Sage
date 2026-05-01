import argparse
import asyncio
from typing import Iterable, Optional

from app.cli.commands.management import (
    agents_command as _agents_command,
    config_init_command as _config_init_command,
    config_show_command as _config_show_command,
    doctor_command as _doctor_command,
    provider_command as _provider_command,
    sessions_command as _sessions_command,
    skills_command as _skills_command,
)
from app.cli.commands.session import (
    build_request as _build_request_impl,
    chat_command as _chat_command_impl,
    resume_command as _resume_command_impl,
    run_command as _run_command_impl,
)
from app.cli.errors import (
    _build_cli_error_payload,
    _emit_cli_error,
)
from app.cli.formatting import (
    _print_session_summary,
)
from app.cli.parser import build_argument_parser
from app.cli.runtime.rendering import (
    _collect_event_file_paths,
    _collect_event_tool_names,
    _emit_chat_exit_summary,
    _emit_stream_idle_notice,
    _emit_stream_idle_notice_for_state,
    _empty_render_state,
    _print_plain_event,
    _read_chat_prompt,
    _render_assistant_content_delta,
)
from app.cli.runtime.stats import (
    _empty_stats,
    _finalize_stats,
    _print_stats,
    _record_stats_event,
)
from app.cli.runtime.stream import (
    STREAM_IDLE_NOTICE_SECONDS,
    STREAM_IDLE_REPEAT_SECONDS,
    _stream_request,
)


CHAT_COMMAND_HELP = (
    "built-in commands:\n"
    "  /help     show this help\n"
    "  /session  print the current session id\n"
    "  /exit     leave the session\n"
    "  /quit     leave the session\n"
    "\n"
    "session recovery:\n"
    "  sage resume <session_id>\n"
    "  sage sessions\n"
    "  sage sessions inspect latest"
)
CHAT_INPUT_PROMPT = "Sage> "


async def _build_request(args: argparse.Namespace, task: str):
    return await _build_request_impl(args, task)


async def _run_command(args: argparse.Namespace) -> int:
    return await _run_command_impl(
        args,
        build_request_fn=_build_request,
        stream_request_fn=_stream_request,
    )


async def _chat_command(args: argparse.Namespace, *, command_mode: str = "chat") -> int:
    return await _chat_command_impl(
        args,
        command_mode=command_mode,
        build_request_fn=_build_request,
        stream_request_fn=_stream_request,
        read_chat_prompt_fn=_read_chat_prompt,
        emit_chat_exit_summary_fn=_emit_chat_exit_summary,
        print_session_summary_fn=_print_session_summary,
        chat_command_help=CHAT_COMMAND_HELP,
        chat_input_prompt=CHAT_INPUT_PROMPT,
    )


async def _resume_command(args: argparse.Namespace) -> int:
    return await _resume_command_impl(args, chat_command_fn=_chat_command)


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
        if args.command == "agents":
            return await _agents_command(args)
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
