import argparse
import sys
import uuid
from typing import Any, Callable, Dict, Optional


async def build_request(args: argparse.Namespace, task: str):
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


async def run_command(
    args: argparse.Namespace,
    *,
    build_request_fn: Callable[[argparse.Namespace, str], Any],
    stream_request_fn: Callable[..., Any],
) -> int:
    from app.cli.service import cli_runtime, validate_cli_request_options, validate_cli_runtime_requirements

    validate_cli_runtime_requirements()
    args.workspace = validate_cli_request_options(
        workspace=args.workspace,
        max_loop_count=args.max_loop_count,
    )
    async with cli_runtime(verbose=args.verbose):
        request = await build_request_fn(args, args.task)
        await stream_request_fn(
            request,
            args.json,
            args.stats,
            workspace=args.workspace,
            command_mode="run",
        )
    return 0


async def chat_command(
    args: argparse.Namespace,
    *,
    command_mode: str = "chat",
    build_request_fn: Callable[[argparse.Namespace, str], Any],
    stream_request_fn: Callable[..., Any],
    read_chat_prompt_fn: Callable[[str], Optional[str]],
    emit_chat_exit_summary_fn: Callable[..., None],
    print_session_summary_fn: Callable[..., None],
    chat_command_help: str,
    chat_input_prompt: str,
) -> int:
    from app.cli.service import (
        cli_db_runtime,
        cli_runtime,
        get_session_summary,
        validate_cli_request_options,
        validate_cli_runtime_requirements,
    )

    session_summary: Optional[Dict[str, Any]] = None
    if not args.session_id:
        args.session_id = str(uuid.uuid4())
    else:
        async with cli_db_runtime(verbose=args.verbose):
            session_summary = await get_session_summary(
                session_id=args.session_id,
                user_id=args.user_id,
            )
        if session_summary and not args.json:
            print_session_summary_fn(session_summary, prefix="resume")
            print()

    if not args.json:
        sys.stderr.write(
            f"session_id: {args.session_id}\n"
            "type /help for built-in commands\n"
        )
        sys.stderr.flush()

    validate_cli_runtime_requirements()
    args.workspace = validate_cli_request_options(
        workspace=args.workspace,
        max_loop_count=args.max_loop_count,
    )
    try:
        async with cli_runtime(verbose=args.verbose):
            while True:
                try:
                    prompt = read_chat_prompt_fn(chat_input_prompt)
                    if prompt is None:
                        if not args.json:
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                        break
                    prompt = prompt.strip()
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
                    print(chat_command_help)
                    continue
                if prompt == "/session":
                    print(args.session_id)
                    continue

                request = await build_request_fn(args, prompt)
                await stream_request_fn(
                    request,
                    args.json,
                    args.stats,
                    workspace=args.workspace,
                    command_mode=command_mode,
                    session_summary=session_summary,
                )
    finally:
        emit_chat_exit_summary_fn(args.session_id, json_output=args.json)
    return 0


async def resume_command(
    args: argparse.Namespace,
    *,
    chat_command_fn: Callable[..., Any],
) -> int:
    return await chat_command_fn(args, command_mode="resume")
