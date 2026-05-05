import argparse
import sys
import uuid
from typing import Any, Callable, Dict, Optional

from common.schemas.goal import GoalStatus


def _current_goal_payload(
    session_summary: Optional[Dict[str, Any]], args: argparse.Namespace
) -> Optional[Dict[str, Any]]:
    if getattr(args, "clear_goal", False):
        return None
    if getattr(args, "goal_objective", None):
        return {
            "objective": args.goal_objective,
            "status": getattr(args, "goal_status", None) or GoalStatus.ACTIVE.value,
        }
    if session_summary:
        raw_goal = session_summary.get("goal")
        if isinstance(raw_goal, dict) and raw_goal.get("objective"):
            payload = dict(raw_goal)
            if getattr(args, "goal_status", None):
                payload["status"] = args.goal_status
            return payload
    return None


def _print_goal_status(session_summary: Optional[Dict[str, Any]], args: argparse.Namespace) -> None:
    goal = _current_goal_payload(session_summary, args)
    if not goal:
        print("goal: (none)")
        return
    print(f"goal: {goal.get('objective')}")
    print(f"goal_status: {goal.get('status') or GoalStatus.ACTIVE.value}")


def _print_resume_goal_hint(session_summary: Optional[Dict[str, Any]]) -> None:
    if not isinstance(session_summary, dict):
        return
    raw_goal = session_summary.get("goal")
    if not isinstance(raw_goal, dict):
        return
    objective = str(raw_goal.get("objective") or "").strip()
    if not objective:
        return
    status = str(raw_goal.get("status") or GoalStatus.ACTIVE.value).strip() or GoalStatus.ACTIVE.value
    print(f"continuing goal: {objective} ({status})")


def _handle_goal_command(
    prompt: str, args: argparse.Namespace, session_summary: Optional[Dict[str, Any]]
) -> Optional[str]:
    parts = prompt.split(maxsplit=2)
    if len(parts) == 1 or (len(parts) == 2 and parts[1] == "show"):
        _print_goal_status(session_summary, args)
        return None
    if len(parts) >= 3 and parts[1] == "set":
        objective = parts[2].strip()
        if not objective:
            print("Usage: /goal | /goal <objective> | /goal show | /goal set <objective> | /goal clear | /goal done")
            return None
        args.goal_objective = objective
        args.goal_status = GoalStatus.ACTIVE.value
        args.clear_goal = False
        print(f"goal set: {objective}")
        return None
    if len(parts) >= 2 and parts[1] not in {"show", "clear", "done"}:
        objective = prompt[len("/goal") :].strip()
        if not objective:
            print("Usage: /goal | /goal <objective> | /goal show | /goal set <objective> | /goal clear | /goal done")
            return None
        args.goal_objective = objective
        args.goal_status = GoalStatus.ACTIVE.value
        args.clear_goal = False
        print(f"goal set: {objective}")
        return objective
    if len(parts) == 2 and parts[1] == "clear":
        args.goal_objective = None
        args.goal_status = None
        args.clear_goal = True
        print("goal clear queued")
        return None
    if len(parts) == 2 and parts[1] == "done":
        if getattr(args, "goal_objective", None) and not (
            session_summary
            and isinstance(session_summary.get("goal"), dict)
            and session_summary["goal"].get("objective")
        ):
            print("goal is queued and will exist after the next request")
            return None
        goal = _current_goal_payload(session_summary, args)
        if not goal:
            print("no active goal")
            return None
        args.goal_objective = None
        args.goal_status = GoalStatus.COMPLETED.value
        args.clear_goal = False
        print(f"goal marked complete: {goal.get('objective')}")
        return None

    print("Usage: /goal | /goal <objective> | /goal show | /goal set <objective> | /goal clear | /goal done")
    return None


def _apply_goal_mutation_to_summary(
    session_summary: Optional[Dict[str, Any]], args: argparse.Namespace
) -> Optional[Dict[str, Any]]:
    if session_summary is None:
        session_summary = {}

    if getattr(args, "clear_goal", False):
        session_summary["goal"] = None
        return session_summary

    if getattr(args, "goal_objective", None):
        session_summary["goal"] = {
            "objective": args.goal_objective,
            "status": getattr(args, "goal_status", None) or GoalStatus.ACTIVE.value,
        }
        return session_summary

    if getattr(args, "goal_status", None):
        raw_goal = session_summary.get("goal")
        if isinstance(raw_goal, dict) and raw_goal.get("objective"):
            session_summary["goal"] = {
                **raw_goal,
                "status": args.goal_status,
            }
    return session_summary


def _clear_pending_goal_mutation(args: argparse.Namespace) -> None:
    args.goal_objective = None
    args.goal_status = None
    args.clear_goal = False


async def build_request(args: argparse.Namespace, task: str):
    from app.cli.service import build_run_request, validate_requested_skills

    skills = await validate_requested_skills(
        requested_skills=args.skills,
        user_id=args.user_id,
        agent_id=args.agent_id,
        workspace=args.workspace,
    )

    goal = None
    if getattr(args, "clear_goal", False):
        goal = {"clear": True}
    elif getattr(args, "goal_objective", None) or getattr(args, "goal_status", None):
        goal = {
            "objective": getattr(args, "goal_objective", None),
            "status": getattr(args, "goal_status", None) or GoalStatus.ACTIVE.value,
            "clear": False,
        }

    return build_run_request(
        task=task,
        session_id=args.session_id,
        user_id=args.user_id,
        agent_id=args.agent_id,
        agent_mode=args.agent_mode,
        available_skills=skills or None,
        max_loop_count=args.max_loop_count,
        goal=goal,
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
        cli_runtime,
        get_session_summary,
        validate_cli_request_options,
        validate_cli_runtime_requirements,
    )

    session_summary: Optional[Dict[str, Any]] = None
    if not args.session_id:
        args.session_id = str(uuid.uuid4())

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
            if args.session_id:
                session_summary = await get_session_summary(
                    session_id=args.session_id,
                    user_id=args.user_id,
                )
                if session_summary and not args.json:
                    print_session_summary_fn(session_summary, prefix="resume")
                    if command_mode == "resume":
                        _print_resume_goal_hint(session_summary)
                    print()

            while True:
                try:
                    prompt = read_chat_prompt_fn("" if args.json else chat_input_prompt)
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
                if prompt.startswith("/goal"):
                    goal_task = _handle_goal_command(prompt, args, session_summary)
                    if goal_task is None:
                        continue
                    prompt = goal_task

                request = await build_request_fn(args, prompt)
                await stream_request_fn(
                    request,
                    args.json,
                    args.stats,
                    workspace=args.workspace,
                    command_mode=command_mode,
                    session_summary=session_summary,
                )
                session_summary = _apply_goal_mutation_to_summary(session_summary, args)
                _clear_pending_goal_mutation(args)
    finally:
        emit_chat_exit_summary_fn(args.session_id, json_output=args.json)
    return 0


async def resume_command(
    args: argparse.Namespace,
    *,
    chat_command_fn: Callable[..., Any],
) -> int:
    return await chat_command_fn(args, command_mode="resume")
