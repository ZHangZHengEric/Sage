"""``sage v2 run|chat|resume|sessions``：在进程内用 SAgents v2 运行任务并管理会话。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sagents.v2 import SAgent, SAgentApplication
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES, RunState
from sagents.v2.package.manifest.root import SageManifest

from app.cli.services.base import CLIError
from app.cli.v2.approvals import (
    WorkspaceApprovalMemory,
    build_tool_policy,
    format_remembered_approvals,
    workspace_approvals_json,
)
from app.cli.v2.host import (
    LocalWorkspaceBindingProvider,
    WorkspaceSandboxSettings,
    build_cli_application,
)
from app.cli.v2.interaction import (
    InteractionDecider,
    JsonLineInteractionDecider,
    PromptInteractionDecider,
    StaticInteractionDecider,
)
from app.cli.v2.package import (
    DEFAULT_CREDENTIAL_ENV,
    CliModelSettings,
    build_preset_package,
    load_package,
    plan_visible_tools,
    without_filesystem_scheduler,
)
from app.cli.v2.render import EventRenderer, JsonRenderer, PlainRenderer
from app.cli.v2.runner import (
    RunOutcome,
    build_start_run,
    resume_run,
    run_task,
    wait_for_pending_run_settlement,
)
from app.cli.v2.sessions import (
    format_sessions_table,
    format_transcript,
    inspect_session,
    list_sessions,
    sessions_json,
)
from app.cli.v2.signals import (
    EXIT_INTERRUPTED,
    InterruptController,
    StdinLineReader,
    interrupt_scope,
    read_line_or_interrupt,
)

AgentFactory = Callable[..., Any]

CHAT_INPUT_PROMPT = "Sage> "
CHAT_HELP = (
    "built-in commands:\n"
    "  /help       show this help\n"
    "  /session    print the current session id\n"
    "  /approvals  list tool approvals remembered in this session\n"
    "  /forget     forget remembered approvals: /forget <n> | /forget all\n"
    "  /exit       leave the session\n"
    "  /quit       leave the session\n"
    "\n"
    "Ctrl-C during a run cancels that run; Ctrl-C at the prompt leaves the session.\n"
    "resume later with: sage v2 resume <session_id>"
)


def resolve_workspace(value: str | None) -> Path:
    workspace = Path(value or os.getcwd()).expanduser()
    if not workspace.is_dir():
        raise CLIError(
            f"workspace is not a directory: {workspace}",
            next_steps=["Pass an existing directory with --workspace."],
        )
    return workspace.resolve()


def resolve_session_root(value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    from common.core import config

    return Path(config.get_local_storage_defaults()["sage_home"]) / "v2" / "runtime"


def resolve_package(
    args: argparse.Namespace,
    cfg: Any,
    *,
    scheduler_root: Path | None = None,
) -> SageManifest:
    package_path = getattr(args, "package", None)
    if package_path:
        # 用户自带的 package 原样尊重（含 scheduler 选择）。
        return load_package(package_path)
    model = (cfg.default_llm_model_name or "").strip()
    base_url = (cfg.default_llm_api_base_url or "").strip()
    api_key = (os.environ.get(DEFAULT_CREDENTIAL_ENV) or "").strip()
    next_steps = []
    if not model:
        next_steps.append(
            "Set SAGE_DEFAULT_LLM_MODEL_NAME in your shell, ~/.sage/.sage_env, or local .env."
        )
    if not base_url:
        next_steps.append(
            "Set SAGE_DEFAULT_LLM_API_BASE_URL in your shell, ~/.sage/.sage_env, or local .env."
        )
    if not api_key:
        next_steps.append(
            f"Set {DEFAULT_CREDENTIAL_ENV} in your shell, ~/.sage/.sage_env, or local .env."
        )
    if next_steps:
        raise CLIError(
            "Model configuration is incomplete for `sage v2`.",
            next_steps=next_steps + ["Or pass --package path/to/sage.yaml."],
        )
    return build_preset_package(
        args.preset,
        CliModelSettings(model=model, base_url=base_url),
        scheduler_root=scheduler_root,
    )


def select_decider(
    args: argparse.Namespace,
    renderer: EventRenderer,
    stdin: StdinLineReader,
) -> InteractionDecider:
    if isinstance(renderer, JsonRenderer):
        return JsonLineInteractionDecider(renderer, stdin.read_line)
    mode = getattr(args, "approval_mode", None)
    if mode == "approve-all":
        return StaticInteractionDecider("approve_once", notice=renderer.notice)
    if mode == "deny-all":
        return StaticInteractionDecider("deny", notice=renderer.notice)
    if stdin.isatty():
        return PromptInteractionDecider(stdin.read_line)
    renderer.notice(
        "stdin is not a terminal; tool approvals will be denied and questions "
        "cancel the run (use --approval-mode approve-all|deny-all to choose explicitly)"
    )
    return StaticInteractionDecider("deny", notice=renderer.notice)


async def read_prompt(
    stdin: StdinLineReader,
    prompt_text: str,
    interrupt: asyncio.Event | None,
) -> str | None:
    """读一行用户输入；EOF 或 Ctrl-C 返回 None。非 TTY（管道）下不打印提示符。"""

    echo = bool(prompt_text) and stdin.isatty()
    if echo:
        sys.stdout.write(prompt_text)
        sys.stdout.flush()
    line = await read_line_or_interrupt(stdin, interrupt)
    if line is None and echo:
        sys.stdout.write("\n")
        sys.stdout.flush()
    return line


def _force_quit(controller: InterruptController, renderer: EventRenderer) -> int:
    """第二次 Ctrl-C：吞掉任务取消，干净地以 130 退出而不是打印 traceback。"""

    task = asyncio.current_task()
    if task is not None:
        task.uncancel()
    renderer.notice("force quit")
    return EXIT_INTERRUPTED


@dataclass
class CliSession:
    """一次 CLI 调用共享的运行时资源：同一个 ``SAgent`` 跑多轮 Run。"""

    application: SAgentApplication
    agent: SAgent
    stdin: StdinLineReader
    bindings: LocalWorkspaceBindingProvider
    package: SageManifest
    spec_hash: str
    agent_id: str
    context: RequestContext
    renderer: EventRenderer
    decider: InteractionDecider
    workspace: Path
    session_root: Path
    invocation_mode: str | None = None
    # Run 进行中读到的 stdin 行是否作为 SteerRun 追加：TTY 交互和 --json 驱动时开启，
    # 管道喂入的纯文本脚本关闭（那些行是后续提示词，不是对当前 Run 的补充）。
    steer_enabled: bool = False
    # plan 模式下对模型可见的工具子集（None = 不限制）。
    enabled_tools: tuple[str, ...] | None = None

    def origin(self) -> dict[str, str]:
        """随 StartRun 落盘的来源信息，`sage v2 sessions` 据此展示。"""

        return {
            "workspace": str(self.workspace),
            "package_id": self.package.metadata.id,
        }

    async def run(
        self,
        task: str,
        *,
        session_id: str | None,
        interrupt,
    ) -> RunOutcome:
        return await run_task(
            self.agent,
            build_start_run(
                agent_id=self.agent_id,
                task=task,
                resolved_spec_hash=self.spec_hash,
                session_id=session_id,
                metadata=self.origin(),
                invocation_mode=self.invocation_mode,
                enabled_tools=self.enabled_tools,
            ),
            self.context,
            renderer=self.renderer,
            decider=self.decider,
            session_frame={
                **self.origin(),
                "session_root": str(self.session_root),
            },
            interrupt=interrupt,
            **self._steer_kwargs(),
        )

    @property
    def approval_memory(self):
        return self.application.services["agent.approval-memory"]

    async def describe_approvals(self, session_id: str | None) -> str:
        if session_id is None:
            return "(no session yet)"
        remembered = await self.approval_memory.list_remembered(session_id=session_id)
        return format_remembered_approvals(remembered)

    async def forget_approvals(self, session_id: str | None, selector: str) -> str:
        """``/forget [all|<n>]``：撤销记住的审批（session 与 workspace 两级），编号来自 ``/approvals``。"""

        if session_id is None:
            return "(no session yet)"
        memory = self.approval_memory
        if selector in {"", "all"}:
            removed = await memory.forget(session_id=session_id)
            return f"forgot {removed} remembered approval(s)"
        remembered = await memory.list_remembered(session_id=session_id)
        try:
            index = int(selector)
        except ValueError:
            return "usage: /forget <n> (from /approvals) | /forget all"
        if not 1 <= index <= len(remembered):
            return f"no remembered approval #{index} (see /approvals)"
        target = remembered[index - 1]
        await memory.forget(session_id=session_id, matcher=target.matcher)
        return f"forgot #{index}: {target.matcher.summary}"

    def _steer_kwargs(self) -> dict[str, Any]:
        if not self.steer_enabled:
            return {}
        return {
            "steer_source": self.stdin.read_line,
            "steer_json": isinstance(self.renderer, JsonRenderer),
        }

    async def settle_session(self, session_id: str, interrupt) -> RunOutcome | None:
        """接管上一个进程留在会话里的非终态 Run，否则 SERIAL 会话无法开始新 Run。

        - SUSPENDED（崩溃发生在等审批时）：回答其交互并续跑到终态；
        - RUNNING/QUEUED（崩溃发生在执行中）：等本进程 dispatcher 的启动恢复把它结算为
          ``execution.worker_restarted``；没有 filesystem scheduler 时无法自动恢复，报错说明。
        """

        runs = await self.agent.runtime.session_store.list_session_runs(session_id)
        if not runs:
            return None
        last = runs[-1]
        if last.state in TERMINAL_RUN_STATES:
            return None
        if last.state != RunState.SUSPENDED:
            self.renderer.notice(
                f"waiting for run {last.run_id} ({last.state.value}) left by a "
                "previous process to settle"
            )
            last = await wait_for_pending_run_settlement(self.agent, last, self.context)
        if last.state == RunState.SUSPENDED:
            self.renderer.notice(f"resuming suspended run {last.run_id}")
            return await resume_run(
                self.agent,
                last.run_id,
                self.context,
                renderer=self.renderer,
                decider=self.decider,
                session_frame={
                    **self.origin(),
                    "session_root": str(self.session_root),
                },
                interrupt=interrupt,
                **self._steer_kwargs(),
            )
        if last.state in TERMINAL_RUN_STATES:
            self.renderer.notice(
                f"run {last.run_id} was settled as {last.state.value}"
            )
            return None
        raise CLIError(
            f"session {session_id} still has an active run {last.run_id} "
            f"({last.state.value})",
            next_steps=[
                "If another sage v2 process is using this session, wait for it "
                "or stop it first.",
                "Orphaned runs are recovered automatically only with the "
                "filesystem scheduler; it was unavailable in this process.",
            ],
        )

    async def ensure_session_exists(self, session_id: str) -> None:
        try:
            await self.agent.runtime.session_store.get_session(session_id)
        except SageV2Error as exc:
            if exc.info.code != "session.not_found":
                raise
            raise CLIError(
                f"v2 session {session_id!r} was not found under {self.session_root}",
                next_steps=[
                    "Check the session id, or pass the --session-root it was created with."
                ],
            ) from exc

    async def close(self) -> None:
        try:
            await self.application.close()
        except RuntimeError as exc:
            # SAgentApplication 把内部关闭错误包成 RuntimeError；只容忍"被取消的 Run
            # 其 driver 仍在收尾"这一种，其余照常抛出。
            if not _is_active_run_close_error(exc):
                raise
            self.renderer.notice(
                "a cancelled run's driver is still finishing; it is abandoned on exit"
            )
        await self.bindings.close()
        self.stdin.close()


def _has_error_code(exc: BaseException, code: str) -> bool:
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, SageV2Error) and cause.info.code == code:
            return True
        cause = cause.__cause__
    return False


def _is_active_run_close_error(exc: BaseException) -> bool:
    return _has_error_code(exc, "agent.close_active_runs")


async def open_cli_session(
    args: argparse.Namespace,
    *,
    build_agent_fn: AgentFactory = build_cli_application,
    stdin: StdinLineReader | None = None,
) -> CliSession:
    from app.cli.service import configure_cli_logging

    cfg = configure_cli_logging(verbose=args.verbose)
    workspace = resolve_workspace(getattr(args, "workspace", None))
    session_root = resolve_session_root(getattr(args, "session_root", None))
    scheduler_root = session_root / "scheduler"
    package = resolve_package(args, cfg, scheduler_root=scheduler_root)
    agent_id = package.entrypoint.agent
    if agent_id is None:
        raise CLIError("the selected package has no agent entrypoint")

    stdin = stdin if stdin is not None else StdinLineReader()
    renderer = JsonRenderer() if args.json else PlainRenderer(verbose=args.verbose)
    decider = select_decider(args, renderer, stdin)
    mode = getattr(args, "mode", None) or "normal"
    if mode not in {"normal", "plan", "goal"}:
        raise CLIError(f"unknown invocation mode {mode!r}")
    # plan 模式只做检查与提案：沙箱退到只读，写类工具对模型隐藏（即使被调用也会被策略拒绝）。
    read_only = bool(getattr(args, "read_only", False)) or mode == "plan"
    bindings = LocalWorkspaceBindingProvider(
        workspace, settings=WorkspaceSandboxSettings(read_only=read_only)
    )
    tool_policy = build_tool_policy(getattr(args, "approval_mode", None))
    try:
        application = await build_agent_fn(
            package=package,
            session_root=session_root,
            bindings=bindings,
            tool_policy=tool_policy,
        )
    except SageV2Error as exc:
        if _has_error_code(exc, "session_store.in_use"):
            raise CLIError(
                f"another sage v2 process is using the session root {session_root}",
                next_steps=[
                    "Wait for that process to finish, or stop it.",
                    "Or run with a different --session-root.",
                ],
            ) from exc
        if not _has_error_code(exc, "scheduler.in_use"):
            raise
        fallback = without_filesystem_scheduler(package)
        if fallback is package:
            raise
        renderer.notice(
            f"another sage v2 process owns the scheduler at {scheduler_root}; "
            "running without restart recovery for this process"
        )
        package = fallback
        application = await build_agent_fn(
            package=package,
            session_root=session_root,
            bindings=bindings,
            tool_policy=tool_policy,
        )
    context = RequestContext(
        actor=ActorRef(principal_id=args.user_id, principal_type=PrincipalType.USER)
    )
    return CliSession(
        application=application,
        agent=application.entrypoint(),
        stdin=stdin,
        bindings=bindings,
        package=package,
        spec_hash=application.composition_hash,
        agent_id=agent_id,
        context=context,
        renderer=renderer,
        decider=decider,
        workspace=workspace,
        session_root=session_root,
        invocation_mode=None if mode == "normal" else mode,
        steer_enabled=bool(args.json) or stdin.isatty(),
        enabled_tools=plan_visible_tools(package, agent_id) if mode == "plan" else None,
    )


async def v2_run_command(
    args: argparse.Namespace,
    *,
    build_agent_fn: AgentFactory = build_cli_application,
    stdin: StdinLineReader | None = None,
) -> int:
    session = await open_cli_session(args, build_agent_fn=build_agent_fn, stdin=stdin)
    try:
        with interrupt_scope() as controller:
            try:
                session_id = getattr(args, "session_id", None)
                if session_id:
                    await session.ensure_session_exists(session_id)
                    settled = await session.settle_session(session_id, controller.event)
                    if settled is not None and settled.interrupted:
                        return settled.exit_code
                    controller.reset()
                outcome = await session.run(
                    args.task,
                    session_id=session_id,
                    interrupt=controller.event,
                )
            except asyncio.CancelledError:
                if not controller.forced:
                    raise
                return _force_quit(controller, session.renderer)
    finally:
        await session.close()
    return outcome.exit_code


async def v2_chat_command(
    args: argparse.Namespace,
    *,
    command_mode: str = "chat",
    build_agent_fn: AgentFactory = build_cli_application,
    stdin: StdinLineReader | None = None,
) -> int:
    session = await open_cli_session(args, build_agent_fn=build_agent_fn, stdin=stdin)
    session_id: str | None = getattr(args, "session_id", None)
    renderer = session.renderer
    exit_code = 0
    try:
        with interrupt_scope() as controller:
            if command_mode == "resume":
                if not session_id:
                    raise CLIError("resume requires a session id")
            if session_id:
                await session.ensure_session_exists(session_id)
                try:
                    settled = await session.settle_session(session_id, controller.event)
                except asyncio.CancelledError:
                    if not controller.forced:
                        raise
                    return _force_quit(controller, renderer)
                if settled is not None and settled.interrupted:
                    controller.reset()
            if not args.json:
                renderer.notice(
                    f"session_id: {session_id or '(new session on first message)'}\n"
                    "type /help for built-in commands"
                )
            queued_prompts: list[str] = []
            while True:
                if queued_prompts:
                    prompt = queued_prompts.pop(0)
                    renderer.notice(f"(steer) sending as the next message: {prompt}")
                else:
                    prompt = await read_prompt(
                        session.stdin,
                        "" if args.json else CHAT_INPUT_PROMPT,
                        controller.event,
                    )
                if prompt is None:
                    # EOF，或提示符处的 Ctrl-C：离开会话。
                    break
                prompt = prompt.strip()
                if not prompt:
                    continue
                if prompt in {"/exit", "/quit"}:
                    break
                if prompt == "/help":
                    renderer.notice(CHAT_HELP)
                    continue
                if prompt == "/session":
                    renderer.notice(session_id or "(no session yet)")
                    continue
                if prompt == "/approvals":
                    renderer.notice(await session.describe_approvals(session_id))
                    continue
                if prompt == "/forget" or prompt.startswith("/forget "):
                    renderer.notice(
                        await session.forget_approvals(
                            session_id, prompt[len("/forget") :].strip()
                        )
                    )
                    continue
                try:
                    outcome = await session.run(
                        prompt, session_id=session_id, interrupt=controller.event
                    )
                except asyncio.CancelledError:
                    if not controller.forced:
                        raise
                    exit_code = _force_quit(controller, renderer)
                    break
                session_id = outcome.session_id
                # 运行中输入若没赶上模型的下一步，就作为后续消息继续发，不能静默丢掉。
                if not outcome.interrupted:
                    queued_prompts.extend(outcome.unapplied_steers)
                # 本轮的 Ctrl-C（如有）已处理完，下一次重新从"第一次"算起。
                controller.reset()
    finally:
        await session.close()
    if not args.json and session_id and exit_code == 0:
        renderer.notice(f"resume later with: sage v2 resume {session_id}")
    return exit_code


async def v2_sessions_command(args: argparse.Namespace) -> int:
    from app.cli.service import configure_cli_logging

    configure_cli_logging(verbose=args.verbose)
    session_root = resolve_session_root(getattr(args, "session_root", None))
    if getattr(args, "sessions_command", None) == "inspect":
        return await _inspect_session(args, session_root)
    # 只读扫描，不取 SessionStore 的写锁：另一个 sage v2 进程在跑时也能列。
    summaries, unreadable = await list_sessions(
        session_root, limit=getattr(args, "limit", None)
    )
    if args.json:
        print(sessions_json(session_root, summaries, unreadable))
        return 0
    print(format_sessions_table(summaries))
    if unreadable:
        sys.stderr.write(
            f"skipped {len(unreadable)} unreadable session(s): {', '.join(unreadable)}\n"
        )
    return 0


async def v2_approvals_command(args: argparse.Namespace) -> int:
    """``sage v2 approvals [forget <n>|all]``：离线管理 workspace 作用域的审批记忆。

    只碰 ``session_root/approvals`` 下的文件，不打开会话存储（不取写锁），
    另一个 ``sage v2`` 进程在跑时也能用。session 作用域的条目在 ``sage v2 chat``
    里用 ``/approvals`` / ``/forget`` 管理。
    """

    from app.cli.service import configure_cli_logging

    configure_cli_logging(verbose=args.verbose)
    workspace = resolve_workspace(getattr(args, "workspace", None))
    session_root = resolve_session_root(getattr(args, "session_root", None))
    memory = WorkspaceApprovalMemory(
        store_root=session_root / "approvals", workspace=workspace
    )
    if getattr(args, "approvals_command", None) == "forget":
        return await _forget_workspace_approvals(args, memory)
    remembered = await memory.list_workspace()
    if args.json:
        print(json.dumps(workspace_approvals_json(memory, remembered), ensure_ascii=False))
        return 0
    print(
        format_remembered_approvals(
            remembered,
            heading=(
                f"remembered approvals for workspace {memory.workspace} "
                "(sage v2 approvals forget <n> | forget all):"
            ),
            empty=f"no remembered approvals for workspace {memory.workspace}",
        )
    )
    return 0


async def _forget_workspace_approvals(
    args: argparse.Namespace, memory: WorkspaceApprovalMemory
) -> int:
    selector = str(getattr(args, "selector", "") or "").strip()
    if selector == "all":
        removed = await memory.forget_workspace()
        print(f"forgot {removed} remembered approval(s) for workspace {memory.workspace}")
        return 0
    remembered = await memory.list_workspace()
    try:
        index = int(selector)
    except ValueError:
        raise CLIError(
            f"invalid selector {selector!r}",
            next_steps=["Use: sage v2 approvals forget <n> (from `sage v2 approvals`) | all"],
        ) from None
    if not 1 <= index <= len(remembered):
        raise CLIError(
            f"no remembered approval #{index} for workspace {memory.workspace}",
            next_steps=["List remembered approvals with: sage v2 approvals"],
        )
    target = remembered[index - 1]
    await memory.forget_workspace(target.matcher)
    print(f"forgot #{index}: {target.matcher.summary}")
    return 0


async def _inspect_session(args: argparse.Namespace, session_root: Path) -> int:
    try:
        transcript = await asyncio.to_thread(
            inspect_session, session_root, args.session_id
        )
    except FileNotFoundError as exc:
        raise CLIError(
            str(exc),
            next_steps=["List known sessions with: sage v2 sessions"],
        ) from exc
    if args.json:
        print(json.dumps(transcript.to_json(), ensure_ascii=False))
    else:
        print(format_transcript(transcript))
    return 0
