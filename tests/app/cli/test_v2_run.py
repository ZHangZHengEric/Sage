from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import app.cli.commands.v2 as v2_command
from app.cli.parser import build_argument_parser
from app.cli.services.base import CLIError
from app.cli.v2.interaction import (
    JSON_DECISION_TYPE,
    InteractionAnswer,
    JsonLineInteractionDecider,
    PromptInteractionDecider,
    StaticInteractionDecider,
)
from app.cli.v2.host import (
    LocalWorkspaceBindingProvider,
    WorkspaceSandboxSettings,
    build_cli_application,
)
from app.cli.v2.package import (
    CliModelSettings,
    available_presets,
    build_preset_package,
)
from app.cli.v2.render import JsonRenderer, PlainRenderer
from app.cli.v2.runner import build_start_run, run_task
from app.cli.v2.signals import (
    StdinLineReader,
    interrupt_scope,
    read_line_or_interrupt,
)
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.interactions import InteractionRequest, InteractionType
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.runtime.execution.sandbox import FileOperation
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)

CONTEXT = RequestContext(
    actor=ActorRef(principal_id="cli-user", principal_type=PrincipalType.USER)
)
MODEL = CliModelSettings(model="scripted", base_url="https://model.invalid/v1")


def _completed(text, calls=()):
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id=new_id("resp"),
            text=text,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
        ),
    )


def _delta(text):
    return ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta=text)


def write_hello_model():
    """第 1 步调用 file_write（需要审批），第 2 步收尾。"""

    return ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    _delta("Writing hello.txt"),
                    _completed(
                        "Writing hello.txt",
                        calls=(
                            ModelToolCall(
                                tool_call_id="call_1",
                                name="file_write",
                                arguments={
                                    "file_path": "hello.txt",
                                    "content": "hello\n",
                                },
                            ),
                        ),
                    ),
                )
            ),
            ScriptedModelStep(events=(_delta("Done."), _completed("Done."))),
        )
    )


class ClosableAgent:
    """测试便利：像旧的 ``SAgent`` 一样 ``await agent.close()``，实际关闭整个 application。"""

    def __init__(self, application):
        self.application = application
        self.agent = application.entrypoint()

    def __getattr__(self, name):
        return getattr(self.agent, name)

    async def close(self):
        await self.application.close()


async def make_agent(tmp_path, model):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    package = build_preset_package("coder", MODEL)
    bindings = LocalWorkspaceBindingProvider(
        workspace, settings=WorkspaceSandboxSettings(process_enabled=False)
    )
    application = await build_cli_application(
        package=package,
        session_root=tmp_path / "runtime",
        bindings=bindings,
        model_provider=model,
    )
    command = build_start_run(
        agent_id=package.entrypoint.agent,
        task="create hello.txt",
        resolved_spec_hash=application.composition_hash,
    )
    return workspace, bindings, ClosableAgent(application), command


def line_source(*values):
    """测试用的异步行来源：值用完即 EOF（None）。"""

    remaining = list(values)

    async def read_line():
        return remaining.pop(0) if remaining else None

    return read_line


def approval_interaction(allowed=("approve_once", "deny", "cancel")):
    return InteractionRequest(
        interaction_id="interaction_1",
        run_id="run_1",
        interaction_type=InteractionType.APPROVAL,
        allowed_decisions=tuple(allowed),
        payload={
            "tool_name": "file_write",
            "arguments": {"file_path": "hello.txt"},
            "side_effect_level": "write",
        },
        requested_at=datetime.now(timezone.utc),
    )


async def test_approve_once_writes_file_and_persists_session(tmp_path):
    workspace, bindings, agent, command = await make_agent(tmp_path, write_hello_model())
    out, err = io.StringIO(), io.StringIO()

    outcome = await run_task(
        agent,
        command,
        CONTEXT,
        renderer=PlainRenderer(out, err),
        decider=StaticInteractionDecider("approve_once"),
    )
    await agent.close()

    assert outcome.state == RunState.COMPLETED
    assert outcome.exit_code == 0
    assert outcome.final_text == "Writing hello.txt\nDone."
    assert (workspace / "hello.txt").read_text() == "hello\n"
    assert "interaction.requested" in outcome.event_types
    assert "tool.call.succeeded" in outcome.event_types
    assert out.getvalue() == "Writing hello.txt\nDone.\n"
    assert "[tool] file_write" in err.getvalue()
    assert bindings.bindings[0].closed is True
    state_file = tmp_path / "runtime" / "sessions" / outcome.session_id / "state.json"
    assert state_file.exists()


async def test_deny_leaves_workspace_untouched(tmp_path):
    workspace, _, agent, command = await make_agent(tmp_path, write_hello_model())

    outcome = await run_task(
        agent,
        command,
        CONTEXT,
        renderer=PlainRenderer(io.StringIO(), io.StringIO()),
        decider=StaticInteractionDecider("deny"),
    )
    await agent.close()

    assert outcome.state == RunState.COMPLETED
    assert not (workspace / "hello.txt").exists()
    assert "tool.call.cancelled" in outcome.event_types
    assert "tool.call.dispatching" not in outcome.event_types


async def test_json_mode_streams_native_events_and_reads_decision_line(tmp_path):
    workspace, _, agent, command = await make_agent(tmp_path, write_hello_model())
    out = io.StringIO()
    renderer = JsonRenderer(out)
    stdin_lines = line_source(
        "not json",
        json.dumps({"type": "something_else"}),
        json.dumps(
            {
                "type": JSON_DECISION_TYPE,
                "interaction_id": "wrong-id",
                "decision": "approve_once",
            }
        ),
        json.dumps({"type": JSON_DECISION_TYPE, "decision": "approve_once"}),
    )

    outcome = await run_task(
        agent,
        command,
        CONTEXT,
        renderer=renderer,
        decider=JsonLineInteractionDecider(renderer, stdin_lines),
    )
    await agent.close()

    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    types = [line["type"] for line in lines]
    assert outcome.state == RunState.COMPLETED
    assert (workspace / "hello.txt").exists()
    assert types[0] == "cli_v2_session"
    assert types[-1] == "cli_v2_result"
    assert "cli_v2_interaction" in types
    assert "run.completed" in types
    interaction = next(line for line in lines if line["type"] == "cli_v2_interaction")
    assert interaction["allowed_decisions"] == ["approve_once", "deny", "cancel"]
    assert interaction["payload"]["tool_name"] == "file_write"
    native = next(line for line in lines if line["type"] == "run.accepted")
    assert native["protocol_version"] == "sage.runtime/v2"
    assert lines[-1]["state"] == "completed"
    assert lines[-1]["final_text"] == "Writing hello.txt\nDone."


async def test_static_decider_never_widens_to_a_disallowed_decision():
    decider = StaticInteractionDecider("approve_and_remember")
    assert await decider.decide(approval_interaction()) == InteractionAnswer("deny")
    assert await StaticInteractionDecider("cancel").decide(
        approval_interaction(("approve_once", "cancel"))
    ) == InteractionAnswer("cancel")


def recovery_interaction():
    return InteractionRequest(
        interaction_id="interaction_2",
        run_id="run_1",
        interaction_type=InteractionType.USER_INPUT,
        allowed_decisions=("retry", "change_direction", "cancel"),
        payload={
            "title": "The agent needs your guidance",
            "prompt": "The model provider is temporarily unavailable.",
            "error": {
                "code": "model.provider_transient",
                "message": "The model provider is temporarily unavailable.",
                "metadata": {"diagnostic_message": "Error code: 502"},
            },
            "questions": [
                {
                    "id": "recovery_action",
                    "type": "single",
                    "title": "What should happen next?",
                    "options": [
                        {"label": "Try again", "value": "retry"},
                        {"label": "Stop this run", "value": "cancel"},
                    ],
                }
            ],
        },
        requested_at=datetime.now(timezone.utc),
    )


def user_input_interaction():
    return InteractionRequest(
        interaction_id="interaction_3",
        run_id="run_1",
        interaction_type=InteractionType.USER_INPUT,
        allowed_decisions=("submit", "cancel"),
        payload={"prompt": "Which target?", "questions": [{"id": "q", "type": "text"}]},
        requested_at=datetime.now(timezone.utc),
    )


async def test_static_decider_cancels_user_input_and_explains_why():
    notices: list[str] = []
    decider = StaticInteractionDecider("approve_once", notice=notices.append)

    answer = await decider.decide(recovery_interaction())

    assert answer == InteractionAnswer("cancel")
    text = notices[0]
    assert "The model provider is temporarily unavailable." in text
    assert "Error code: 502" in text
    assert "[retry] Try again" in text
    assert "non-interactive decision: cancel" in text


async def test_prompt_decider_handles_recovery_and_free_text_questions():
    decider = PromptInteractionDecider(line_source("?", "c", "use staging"), err=io.StringIO())
    assert await decider.decide(recovery_interaction()) == InteractionAnswer(
        "change_direction", {"text": "use staging"}
    )

    retry = PromptInteractionDecider(line_source("r"), err=io.StringIO())
    assert await retry.decide(recovery_interaction()) == InteractionAnswer("retry")

    submit = PromptInteractionDecider(line_source("Use staging."), err=io.StringIO())
    assert await submit.decide(user_input_interaction()) == InteractionAnswer(
        "submit", {"text": "Use staging."}
    )

    empty = PromptInteractionDecider(line_source("   "), err=io.StringIO())
    assert await empty.decide(user_input_interaction()) == InteractionAnswer("cancel")


async def test_prompt_decider_maps_keys_and_falls_back_on_eof():
    err = io.StringIO()
    decider = PromptInteractionDecider(line_source("?", "r", "a"), err=err)
    assert await decider.decide(approval_interaction()) == InteractionAnswer(
        "approve_once"
    )
    assert err.getvalue().count("please answer one of") == 2

    decider = PromptInteractionDecider(line_source(), err=io.StringIO())
    assert await decider.decide(approval_interaction()) == InteractionAnswer("deny")

    remember = PromptInteractionDecider(line_source("r"), err=io.StringIO())
    assert await remember.decide(
        approval_interaction(("approve_once", "approve_and_remember", "deny"))
    ) == InteractionAnswer("approve_and_remember")


async def test_provider_failure_becomes_recovery_question_then_cancels_headless(
    tmp_path,
):
    failing_model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(),
                error=RuntimeErrorInfo(
                    code="model.provider_transient",
                    category=ErrorCategory.PROVIDER_TRANSIENT,
                    message="provider unreachable",
                    retryable=True,
                    safe_to_resume=True,
                ),
            ),
        )
    )
    _, _, agent, command = await make_agent(tmp_path, failing_model)
    out, err = io.StringIO(), io.StringIO()
    renderer = PlainRenderer(out, err)

    outcome = await run_task(
        agent,
        command,
        CONTEXT,
        renderer=renderer,
        decider=StaticInteractionDecider("deny", notice=renderer.notice),
    )
    await agent.close()

    assert outcome.state == RunState.CANCELLED
    assert outcome.exit_code == 1
    assert "interaction.requested" in outcome.event_types
    assert "non-interactive decision: cancel" in err.getvalue()
    assert "[run cancelled] reason=interaction_cancelled" in err.getvalue()
    assert out.getvalue() == ""


def test_binding_provider_exposes_host_workspace_paths(tmp_path):
    provider = LocalWorkspaceBindingProvider(tmp_path)
    spec = provider.sandbox_spec()

    assert spec.workspace_root == tmp_path.resolve().as_posix()
    assert spec.filesystem.allowed_roots == (spec.workspace_root,)
    assert spec.metadata["host_workspace"] == str(tmp_path.resolve())
    assert spec.process.enabled is True
    assert spec.filesystem.allowed_operations == frozenset(FileOperation)

    read_only = LocalWorkspaceBindingProvider(
        tmp_path, settings=WorkspaceSandboxSettings(read_only=True)
    ).sandbox_spec()
    assert read_only.filesystem.allowed_operations == frozenset(
        {FileOperation.READ, FileOperation.LIST}
    )
    assert read_only.process.read_only is True
    assert read_only.policy_hash != spec.policy_hash


def test_parser_v2_run_defaults():
    args = build_argument_parser().parse_args(["v2", "run", "hello"])
    assert args.command == "v2"
    assert args.v2_command == "run"
    assert args.task == "hello"
    assert args.preset == "coder"
    assert args.package is None
    assert args.approval_mode is None
    assert args.json is False


def test_available_presets_only_include_loop_entrypoints():
    presets = available_presets()
    assert "coder" in presets
    assert "assistant" in presets
    assert "flow_orchestrator" not in presets


def _command_args(tmp_path, **overrides):
    values = {
        "task": "create hello.txt",
        "preset": "coder",
        "package": None,
        "workspace": str(tmp_path / "workspace"),
        "session_id": None,
        "session_root": str(tmp_path / "runtime"),
        "user_id": "cli-user",
        "approval_mode": "approve-all",
        "read_only": False,
        "mode": "normal",
        "json": False,
        "verbose": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


async def test_v2_run_command_requires_model_configuration(tmp_path, monkeypatch):
    (tmp_path / "workspace").mkdir()
    monkeypatch.delenv("SAGE_DEFAULT_LLM_API_KEY", raising=False)
    cfg = SimpleNamespace(default_llm_model_name="", default_llm_api_base_url="")

    with patch("app.cli.service.configure_cli_logging", return_value=cfg):
        with pytest.raises(CLIError) as raised:
            await v2_command.v2_run_command(_command_args(tmp_path))

    steps = " ".join(raised.value.next_steps)
    assert "SAGE_DEFAULT_LLM_MODEL_NAME" in steps
    assert "SAGE_DEFAULT_LLM_API_KEY" in steps
    assert "--package" in steps


async def test_v2_run_command_end_to_end_with_injected_model(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "test-key")
    cfg = SimpleNamespace(
        default_llm_model_name="scripted",
        default_llm_api_base_url="https://model.invalid/v1",
    )

    async def build_agent(**kwargs):
        return await build_cli_application(**kwargs, model_provider=write_hello_model())

    with patch("app.cli.service.configure_cli_logging", return_value=cfg):
        exit_code = await v2_command.v2_run_command(
            _command_args(tmp_path), build_agent_fn=build_agent
        )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert (tmp_path / "workspace" / "hello.txt").read_text() == "hello\n"
    assert captured.out == "Writing hello.txt\nDone.\n"
    assert "session_id:" in captured.err
    assert (tmp_path / "runtime" / "sessions").is_dir()


# ---------- C1-b：中断、续聊、多轮 chat ----------


def talk_model(*answers):
    return ScriptedModelProvider(
        tuple(ScriptedModelStep(events=(_completed(text),)) for text in answers)
    )


def _request_texts(request):
    return [
        block.text
        for message in request.messages
        for block in message.content
        if hasattr(block, "text")
    ]


class InterruptOnFirstDelta(PlainRenderer):
    def __init__(self, interrupt: asyncio.Event, out, err):
        super().__init__(out, err)
        self.interrupt = interrupt

    def handle(self, event):
        super().handle(event)
        if event.type == "message.delta" and not self.interrupt.is_set():
            self.interrupt.set()


async def test_interrupt_cancels_run_durably_and_exits_130(tmp_path):
    slow_model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(*(_delta("x") for _ in range(40)), _completed("x" * 40))
            ),
        )
    )
    _, _, agent, command = await make_agent(tmp_path, slow_model)
    interrupt = asyncio.Event()
    out, err = io.StringIO(), io.StringIO()

    outcome = await run_task(
        agent,
        command,
        CONTEXT,
        renderer=InterruptOnFirstDelta(interrupt, out, err),
        decider=StaticInteractionDecider("deny"),
        interrupt=interrupt,
    )
    stored = await agent.runtime.get_run(outcome.run_id)
    await agent.close()

    assert outcome.interrupted is True
    assert outcome.state == RunState.CANCELLED
    assert outcome.exit_code == 130
    assert stored.state == RunState.CANCELLED
    assert "run.cancelled" in outcome.event_types
    assert "run.completed" not in outcome.event_types
    assert "cancelling run" in err.getvalue()
    assert "[run cancelled] reason=user_interrupt" in err.getvalue()


async def test_second_run_in_same_session_sees_previous_history(tmp_path):
    model = talk_model("first answer", "second answer")
    _, _, agent, _ = await make_agent(tmp_path, model)
    spec_hash = agent.application.composition_hash
    renderer = PlainRenderer(io.StringIO(), io.StringIO())
    decider = StaticInteractionDecider("deny")

    first = await run_task(
        agent,
        build_start_run(agent_id="coder", task="first task", resolved_spec_hash=spec_hash),
        CONTEXT,
        renderer=renderer,
        decider=decider,
    )
    second = await run_task(
        agent,
        build_start_run(
            agent_id="coder",
            task="second task",
            resolved_spec_hash=spec_hash,
            session_id=first.session_id,
        ),
        CONTEXT,
        renderer=renderer,
        decider=decider,
    )
    await agent.close()

    assert second.session_id == first.session_id
    assert second.run_id != first.run_id
    assert second.final_text == "second answer"
    texts = _request_texts(model.requests[1])
    assert "first task" in texts
    assert "first answer" in texts
    assert texts[-1] == "second task"


def model_session_id(text: str) -> str:
    return next(
        part
        for part in text.split()
        if part.startswith("session_") and not part.startswith("session_id")
    )


def _patched_cfg():
    return patch(
        "app.cli.service.configure_cli_logging",
        return_value=SimpleNamespace(
            default_llm_model_name="scripted",
            default_llm_api_base_url="https://model.invalid/v1",
        ),
    )


async def test_chat_loop_runs_turns_in_one_session_until_exit(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "test-key")
    model = talk_model("hi there", "hi again")
    stdin = StdinLineReader(
        io.StringIO("/help\n/session\nhello\n/session\n  \nagain\n/exit\nnever\n")
    )

    async def build_agent(**kwargs):
        return await build_cli_application(**kwargs, model_provider=model)

    with _patched_cfg():
        exit_code = await v2_command.v2_chat_command(
            _command_args(tmp_path, task=None),
            build_agent_fn=build_agent,
            stdin=stdin,
        )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "hi there\nhi again\n"
    assert "built-in commands" in captured.err
    assert "(no session yet)" in captured.err
    assert captured.err.count("session_id: session_") == 1
    assert captured.err.count(model_session_id(captured.err)) >= 3
    assert "resume later with: sage v2 resume session_" in captured.err
    assert len(model.requests) == 2
    assert "hello" in _request_texts(model.requests[1])
    assert "hi there" in _request_texts(model.requests[1])


async def test_resume_unknown_session_fails_before_prompting(tmp_path, monkeypatch):
    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "test-key")

    async def build_agent(**kwargs):
        return await build_cli_application(**kwargs, model_provider=talk_model("unused"))

    with _patched_cfg():
        with pytest.raises(CLIError) as raised:
            await v2_command.v2_chat_command(
                _command_args(tmp_path, task=None, session_id="session_missing"),
                command_mode="resume",
                build_agent_fn=build_agent,
                stdin=StdinLineReader(io.StringIO("never\n")),
            )
    assert "session_missing" in str(raised.value)


def test_parser_v2_chat_and_resume():
    parser = build_argument_parser()
    chat = parser.parse_args(["v2", "chat", "--approval-mode", "deny-all"])
    assert (chat.v2_command, chat.session_id, chat.approval_mode) == (
        "chat",
        None,
        "deny-all",
    )
    resume = parser.parse_args(["v2", "resume", "session_abc", "--read-only"])
    assert (resume.v2_command, resume.session_id, resume.read_only) == (
        "resume",
        "session_abc",
        True,
    )


# ---------- C1-d：会话列表 ----------


async def test_sessions_listing_reads_authoritative_state(tmp_path):
    from app.cli.v2.sessions import (
        discover_session_ids,
        format_sessions_table,
        list_sessions,
    )

    session_root = tmp_path / "runtime"
    assert discover_session_ids(session_root) == []
    assert format_sessions_table([]) == "no v2 sessions found"

    model = talk_model("one", "two")
    _, _, agent, _ = await make_agent(tmp_path, model)
    spec_hash = agent.application.composition_hash
    renderer = PlainRenderer(io.StringIO(), io.StringIO())
    decider = StaticInteractionDecider("deny")
    first = await run_task(
        agent,
        build_start_run(
            agent_id="coder",
            task="first task",
            resolved_spec_hash=spec_hash,
            metadata={"workspace": "/w", "package_id": "sage.cli.coder"},
        ),
        CONTEXT,
        renderer=renderer,
        decider=decider,
    )
    second = await run_task(
        agent,
        build_start_run(
            agent_id="coder",
            task="second task\nwith detail",
            resolved_spec_hash=spec_hash,
            metadata={"workspace": "/w", "package_id": "sage.cli.coder"},
        ),
        CONTEXT,
        renderer=renderer,
        decider=decider,
    )
    await agent.close()

    summaries, unreadable = await list_sessions(session_root)
    limited, _ = await list_sessions(session_root, limit=1)

    assert unreadable == []
    assert [value.session_id for value in summaries] == [
        second.session_id,
        first.session_id,
    ]
    newest = summaries[0]
    assert newest.task == "second task\nwith detail"
    assert newest.run_count == 1
    assert newest.last_run_id == second.run_id
    assert newest.last_state == "completed"
    assert newest.agent_id == "coder"
    assert newest.workspace == "/w"
    assert newest.package_id == "sage.cli.coder"
    assert [value.session_id for value in limited] == [second.session_id]
    table = format_sessions_table(summaries)
    assert second.session_id in table
    assert "last=completed" in table
    assert "second task with detail" in table
    assert newest.to_json()["updated_at"] == newest.updated_at.isoformat()


async def test_v2_sessions_command_prints_json(tmp_path, monkeypatch, capsys):
    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "test-key")

    async def build_agent(**kwargs):
        return await build_cli_application(**kwargs, model_provider=talk_model("hi"))

    with _patched_cfg():
        assert (
            await v2_command.v2_run_command(
                _command_args(tmp_path), build_agent_fn=build_agent
            )
            == 0
        )
        capsys.readouterr()
        exit_code = await v2_command.v2_sessions_command(
            argparse.Namespace(
                limit=5,
                session_root=str(tmp_path / "runtime"),
                json=True,
                verbose=False,
            )
        )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["total"] == 1
    assert payload["unreadable"] == []
    entry = payload["list"][0]
    assert entry["task"] == "create hello.txt"
    assert entry["last_state"] == "completed"
    assert entry["workspace"] == str((tmp_path / "workspace").resolve())
    assert entry["package_id"] == "sage.cli.coder"


def test_parser_v2_sessions():
    args = build_argument_parser().parse_args(["v2", "sessions", "--limit", "5"])
    assert (args.v2_command, args.limit, args.json) == ("sessions", 5, False)



# ---------- 取消安全：CAS 撞车、审批等待期间中断、关闭容忍 ----------


async def test_cancel_retries_when_run_revision_races_with_driver():
    from sagents.v2.contracts.commands import CommandDecision, CommandReceipt
    from sagents.v2.contracts.run_state import RunSnapshot, SessionConcurrencyMode

    from app.cli.v2.runner import _InterruptCanceller

    now = datetime.now(timezone.utc)
    state = {"revision": 3, "run_state": RunState.RUNNING, "cancel_calls": []}

    def snapshot():
        return RunSnapshot(
            session_id="session_1",
            run_id="run_1",
            state=state["run_state"],
            revision=state["revision"],
            last_run_sequence=0,
            concurrency_mode=SessionConcurrencyMode.SERIAL,
            base_session_revision=0,
            base_session_sequence=0,
            accepted_session_revision=0,
            resolved_spec_hash="sha256:x",
            created_at=now,
            updated_at=now,
        )

    class FakeRuntime:
        async def get_run(self, run_id):
            return snapshot()

        async def cancel_run(self, command, context):
            state["cancel_calls"].append(command.expected_revision)
            if command.expected_revision != state["revision"]:
                return CommandReceipt(
                    command_id="cmd",
                    decision=CommandDecision.REJECTED,
                    error=RuntimeErrorInfo(
                        code="run.revision_conflict",
                        category=ErrorCategory.CONFLICT,
                        message="stale",
                    ),
                )
            state["run_state"] = RunState.CANCELLED
            return CommandReceipt(command_id="cmd", decision=CommandDecision.ACCEPTED)

    notices: list[str] = []
    renderer = SimpleNamespace(notice=notices.append)
    canceller = _InterruptCanceller(
        SimpleNamespace(runtime=FakeRuntime()), "run_1", CONTEXT, renderer, None
    )

    # 第一次 get_run 之后 driver 又提交了一次（revision 前进），CancelRun 撞车。
    original_get_run = FakeRuntime.get_run
    calls = {"n": 0}

    async def racing_get_run(self, run_id):
        calls["n"] += 1
        value = await original_get_run(self, run_id)
        if calls["n"] == 1:
            state["revision"] += 1
        return value

    FakeRuntime.get_run = racing_get_run
    assert await canceller.cancel_run() is True
    assert state["cancel_calls"] == [3, 4]
    assert state["run_state"] == RunState.CANCELLED
    assert notices == []


async def test_interrupt_while_waiting_for_approval_exits_cleanly(tmp_path):
    workspace, _, agent, command = await make_agent(tmp_path, write_hello_model())
    interrupt = asyncio.Event()

    class InterruptingDecider:
        async def decide(self, interaction):
            interrupt.set()
            for _ in range(5):
                await asyncio.sleep(0)
            return InteractionAnswer("approve_once")

    err = io.StringIO()
    outcome = await run_task(
        agent,
        command,
        CONTEXT,
        renderer=PlainRenderer(io.StringIO(), err),
        decider=InterruptingDecider(),
        interrupt=interrupt,
    )
    await agent.close()

    assert outcome.interrupted is True
    assert outcome.state == RunState.CANCELLED
    assert outcome.exit_code == 130
    assert "tool.call.dispatching" not in outcome.event_types
    assert not (workspace / "hello.txt").exists()
    assert "cancelling run" in err.getvalue()


async def test_close_tolerates_only_pending_driver_errors(tmp_path):
    from sagents.v2.contracts.errors import SageV2Error

    notices: list[str] = []

    class FakeApplication:
        def __init__(self, error):
            self.error = error

        async def close(self):
            if self.error is not None:
                raise self.error

    class FakeBindings:
        async def close(self):
            return None

    def session(error):
        return v2_command.CliSession(
            application=FakeApplication(error),
            agent=None,
            stdin=StdinLineReader(io.StringIO("")),
            bindings=FakeBindings(),
            package=None,
            spec_hash="sha256:test",
            agent_id="coder",
            context=CONTEXT,
            renderer=SimpleNamespace(notice=notices.append),
            decider=None,
            workspace=tmp_path,
            session_root=tmp_path,
        )

    active = SageV2Error(
        RuntimeErrorInfo(
            code="agent.close_active_runs",
            category=ErrorCategory.CONFLICT,
            message="active",
        )
    )
    wrapped = RuntimeError("1 application scope(s) failed to close")
    wrapped.__cause__ = active
    await session(wrapped).close()
    assert notices and "still finishing" in notices[0]

    with pytest.raises(RuntimeError, match="unrelated"):
        await session(RuntimeError("unrelated")).close()


async def test_interrupt_does_not_wait_for_a_blocked_prompt(tmp_path):
    """用户 Ctrl-C 时哪怕审批提示还卡在 stdin 上，也要立刻取消并返回。"""

    _, _, agent, command = await make_agent(tmp_path, write_hello_model())
    interrupt = asyncio.Event()
    never = asyncio.Event()

    class BlockedDecider:
        async def decide(self, interaction):
            interrupt.set()
            await never.wait()
            raise AssertionError("must not be reached")

    outcome = await asyncio.wait_for(
        run_task(
            agent,
            command,
            CONTEXT,
            renderer=PlainRenderer(io.StringIO(), io.StringIO()),
            decider=BlockedDecider(),
            interrupt=interrupt,
        ),
        timeout=1.5,
    )
    await agent.close()

    assert outcome.interrupted is True
    assert outcome.state == RunState.CANCELLED
    assert outcome.exit_code == 130



# ---------- 单一 stdin 读取者 / SIGINT 控制器 / 跨 Run cursor ----------


async def test_stdin_reader_uses_the_event_loop_for_real_descriptors():
    import os

    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "r")
    reader = StdinLineReader(stream)
    os.write(write_fd, b"first\r\nsec")
    assert await reader.read_line() == "first"
    os.write(write_fd, b"ond\ntail-without-newline")
    assert await reader.read_line() == "second"
    os.close(write_fd)
    assert await reader.read_line() == "tail-without-newline"
    assert await reader.read_line() is None
    assert await reader.read_line() is None
    reader.close()
    stream.close()


async def test_stdin_reader_falls_back_to_a_thread_for_non_descriptor_streams():
    reader = StdinLineReader(io.StringIO("one\ntwo\n"))
    assert reader.isatty() is False
    assert await reader.read_line() == "one"
    assert await reader.read_line() == "two"
    assert await reader.read_line() is None


async def test_read_line_or_interrupt_returns_none_without_waiting_for_stdin():
    import os

    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "r")
    reader = StdinLineReader(stream)
    interrupt = asyncio.Event()

    async def press_ctrl_c():
        await asyncio.sleep(0.05)
        interrupt.set()

    asyncio.get_running_loop().create_task(press_ctrl_c())
    assert await asyncio.wait_for(read_line_or_interrupt(reader, interrupt), 1.0) is None
    # 之后到达的输入仍由同一个读取者交付，不会被"孤儿"读取者吞掉。
    os.write(write_fd, b"later\n")
    assert await asyncio.wait_for(reader.read_line(), 1.0) == "later"
    os.close(write_fd)
    reader.close()
    stream.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals only")
async def test_interrupt_scope_first_sigint_signals_second_force_cancels():
    import os
    import signal

    with interrupt_scope() as controller:
        os.kill(os.getpid(), signal.SIGINT)
        for _ in range(20):
            if controller.event.is_set():
                break
            await asyncio.sleep(0.01)
        assert controller.event.is_set()
        assert controller.forced is False

        os.kill(os.getpid(), signal.SIGINT)
        with pytest.raises(asyncio.CancelledError):
            for _ in range(50):
                await asyncio.sleep(0.01)
        assert controller.forced is True
        asyncio.current_task().uncancel()

        controller.reset()
        assert controller.event.is_set() is False


async def test_resume_cursor_is_per_run_when_one_renderer_spans_two_runs(tmp_path):
    """第二轮也需要审批时，续订阅必须从本 Run 的序号开始，而不是上一轮的。"""

    model = ScriptedModelProvider(
        (
            *write_hello_model()._steps,
            *write_hello_model()._steps,
        )
    )
    workspace, _, agent, _ = await make_agent(tmp_path, model)
    spec_hash = agent.application.composition_hash
    renderer = PlainRenderer(io.StringIO(), io.StringIO())
    decider = StaticInteractionDecider("approve_once")

    first = await run_task(
        agent,
        build_start_run(agent_id="coder", task="first", resolved_spec_hash=spec_hash),
        CONTEXT,
        renderer=renderer,
        decider=decider,
    )
    second = await asyncio.wait_for(
        run_task(
            agent,
            build_start_run(
                agent_id="coder",
                task="second",
                resolved_spec_hash=spec_hash,
                session_id=first.session_id,
            ),
            CONTEXT,
            renderer=renderer,
            decider=decider,
        ),
        timeout=1.5,
    )
    await agent.close()

    assert first.state == RunState.COMPLETED
    assert second.state == RunState.COMPLETED
    assert second.event_types.count("tool.call.succeeded") == 1
    assert second.event_types[-1] == "run.completed"


# ---------- C1-e：崩溃恢复与跨进程接管挂起的 Run ----------


def test_preset_package_selects_filesystem_scheduler_only_when_root_given(tmp_path):
    from app.cli.v2.package import (
        FILESYSTEM_SCHEDULER_PLUGIN,
        SCHEDULER_CAPABILITY,
        without_filesystem_scheduler,
    )

    plain = build_preset_package("coder", MODEL)
    assert SCHEDULER_CAPABILITY not in plain.runtime.capabilities

    durable = build_preset_package("coder", MODEL, scheduler_root=tmp_path / "sched")
    selection = durable.runtime.capabilities[SCHEDULER_CAPABILITY]
    assert selection.plugin == FILESYSTEM_SCHEDULER_PLUGIN
    assert selection.config["root"] == str(tmp_path / "sched")

    fallback = without_filesystem_scheduler(durable)
    assert SCHEDULER_CAPABILITY not in fallback.runtime.capabilities
    assert without_filesystem_scheduler(plain) is plain


async def test_cli_session_uses_filesystem_scheduler_and_falls_back_when_owned(
    tmp_path, monkeypatch, capsys
):
    from sagents.v2.runtime.execution.scheduler import (
        FilesystemScheduler,
        InMemoryScheduler,
    )

    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "test-key")

    async def build_agent(**kwargs):
        return await build_cli_application(**kwargs, model_provider=talk_model("x"))

    with _patched_cfg():
        session = await v2_command.open_cli_session(
            _command_args(tmp_path), build_agent_fn=build_agent
        )
        try:
            scheduler = session.application.services["execution.scheduler"]
            assert isinstance(scheduler, FilesystemScheduler)
            assert (tmp_path / "runtime" / "scheduler" / ".writer.lock").exists()
        finally:
            await session.close()

        owner = FilesystemScheduler(tmp_path / "runtime" / "scheduler")
        try:
            degraded = await v2_command.open_cli_session(
                _command_args(tmp_path), build_agent_fn=build_agent
            )
            try:
                assert isinstance(
                    degraded.application.services["execution.scheduler"],
                    InMemoryScheduler,
                )
            finally:
                await degraded.close()
        finally:
            await owner.close()

    assert "running without restart recovery" in capsys.readouterr().err


async def test_run_orphaned_by_a_crash_is_settled_then_the_session_resumes(
    tmp_path, monkeypatch, capsys
):
    """模拟上一个进程在执行中被 kill：session 里留下 RUNNING 的 run + scheduler 里的 WorkItem。"""

    from sagents.v2.contracts.common import utc_now
    from sagents.v2.runtime import HarnessRuntime
    from sagents.v2.runtime.execution.scheduler import FilesystemScheduler, WorkItem

    from app.cli.v2.sessions import list_sessions, open_session_store

    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "test-key")
    session_root = tmp_path / "runtime"

    store = open_session_store(session_root)
    runtime = HarnessRuntime(store)
    handle = await runtime.start_run(
        build_start_run(agent_id="coder", task="orphan", resolved_spec_hash="sha256:x"),
        CONTEXT,
    )
    running = await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=handle.run_revision,
        context=CONTEXT,
        idempotency_key="crash:start",
    )
    assert running.state == RunState.RUNNING
    await store.close()
    scheduler = FilesystemScheduler(session_root / "scheduler")
    await scheduler.submit(
        WorkItem(
            work_id=f"work-{handle.run_id}",
            run_id=handle.run_id,
            available_at=utc_now(),
            idempotency_key=f"dispatch:{handle.run_id}",
            payload={
                "resume": False,
                "request_context": CONTEXT.model_dump(mode="json"),
            },
        )
    )
    await scheduler.close()

    async def build_agent(**kwargs):
        return await build_cli_application(**kwargs, model_provider=talk_model("hi there"))

    with _patched_cfg():
        exit_code = await v2_command.v2_chat_command(
            _command_args(tmp_path, task=None, session_id=handle.session_id),
            command_mode="resume",
            build_agent_fn=build_agent,
            stdin=StdinLineReader(io.StringIO("hello\n/exit\n")),
        )

    captured = capsys.readouterr()
    assert exit_code == 0
    # 孤儿 run 通常在 build() 内的 dispatcher.start() 就被结算；若恢复稍慢，
    # settle_session 会等它。两条路径都必须以"新 run 正常完成"收尾。
    assert captured.out == "hi there\n"

    summaries, _ = await list_sessions(session_root)
    store = open_session_store(session_root)
    try:
        runs = await store.list_session_runs(handle.session_id)
        orphan_result = await store.get_run_result(handle.run_id)
    finally:
        await store.close()
    assert summaries[0].run_count == 2
    assert [run.state for run in runs] == [RunState.FAILED, RunState.COMPLETED]
    assert orphan_result.error is not None
    # 上游把无检查点孤儿 run 的结算码从 worker_restarted 演进为 barrier_recovery_failed；
    # 对 CLI 重要的是：它被结算为终态 FAILED，会话可以继续。
    assert orphan_result.error.code in {
        "execution.worker_restarted",
        "execution.barrier_recovery_failed",
    }


async def test_suspended_run_from_a_previous_process_is_resumed_first(
    tmp_path, monkeypatch, capsys
):
    """模拟上一个进程在等审批时退出：run 停在 SUSPENDED，新进程 resume 应先接管它。"""

    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "test-key")
    workspace = tmp_path / "workspace"
    session_root = tmp_path / "runtime"
    package = build_preset_package("coder", MODEL, scheduler_root=session_root / "scheduler")

    first_bindings = LocalWorkspaceBindingProvider(
        workspace, settings=WorkspaceSandboxSettings(process_enabled=False)
    )
    first = await build_cli_application(
        package=package,
        session_root=session_root,
        bindings=first_bindings,
        model_provider=write_hello_model(),
    )
    agent = first.entrypoint()
    stream = await agent.run_stream(
        build_start_run(
            agent_id="coder",
            task="create hello.txt",
            resolved_spec_hash=first.composition_hash,
        ),
        CONTEXT,
    )
    async for _ in stream.events:
        pass
    suspended = await stream.wait()
    assert suspended.state == RunState.SUSPENDED
    await first.close()
    assert not (workspace / "hello.txt").exists()

    async def build_agent(**kwargs):
        return await build_cli_application(**kwargs, model_provider=talk_model("Done."))

    with _patched_cfg():
        exit_code = await v2_command.v2_chat_command(
            _command_args(tmp_path, task=None, session_id=suspended.session_id),
            command_mode="resume",
            build_agent_fn=build_agent,
            stdin=StdinLineReader(io.StringIO("/exit\n")),
        )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"resuming suspended run {suspended.run_id}" in captured.err
    assert (workspace / "hello.txt").read_text() == "hello\n"
    assert captured.out.endswith("Done.\n")



async def test_sessions_listing_is_read_only_and_sees_journal_deltas(tmp_path):
    """另一个进程正占着 store 写锁时也能列会话，且读到 journal 里最新的 run 状态。"""

    from app.cli.v2.sessions import list_sessions, open_session_store

    session_root = tmp_path / "runtime"
    _, _, agent, command = await make_agent(tmp_path, write_hello_model())
    outcome = await run_task(
        agent,
        command,
        CONTEXT,
        renderer=PlainRenderer(io.StringIO(), io.StringIO()),
        decider=StaticInteractionDecider("approve_once"),
    )
    await agent.close()

    owner = open_session_store(session_root)
    try:
        summaries, unreadable = await list_sessions(session_root)
    finally:
        await owner.close()

    assert unreadable == []
    assert [value.session_id for value in summaries] == [outcome.session_id]
    assert summaries[0].last_state == "completed"
    assert summaries[0].task == "create hello.txt"


async def test_cli_session_reports_when_the_session_root_is_owned(
    tmp_path, monkeypatch
):
    from app.cli.v2.sessions import open_session_store

    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "test-key")
    owner = open_session_store(tmp_path / "runtime")
    try:
        with _patched_cfg():
            with pytest.raises(CLIError) as raised:
                await v2_command.open_cli_session(_command_args(tmp_path))
    finally:
        await owner.close()
    assert "another sage v2 process is using the session root" in str(raised.value)
    assert any("--session-root" in step for step in raised.value.next_steps)


# ---------- --mode plan|goal 与 sessions inspect ----------


def plan_model():
    """plan 模式：先提交计划（需审批），再给出解释文本完成。"""

    return ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    _completed(
                        "",
                        calls=(
                            ModelToolCall(
                                tool_call_id="call_plan",
                                name="goal_submit",
                                arguments={"content": "1. read files\n2. propose patch"},
                            ),
                        ),
                    ),
                )
            ),
            ScriptedModelStep(events=(_completed("Here is the plan."),)),
        )
    )


async def test_plan_mode_submits_a_plan_for_approval_on_a_read_only_sandbox(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "test-key")
    model = plan_model()

    async def build_agent(**kwargs):
        return await build_cli_application(**kwargs, model_provider=model)

    with _patched_cfg():
        session = await v2_command.open_cli_session(
            _command_args(tmp_path, mode="plan"), build_agent_fn=build_agent
        )
        try:
            assert session.bindings.settings.read_only is True
            assert session.invocation_mode == "plan"
            outcome = await session.run("plan the change", session_id=None, interrupt=None)
            command = await session.agent.runtime.session_store.get_start_command(
                outcome.run_id
            )
        finally:
            await session.close()

    assert outcome.state == RunState.COMPLETED
    assert command.invocation_mode == "plan"
    assert "tool.call.awaiting_approval" in outcome.event_types
    assert "tool.call.succeeded" in outcome.event_types
    assert outcome.final_text.endswith("Here is the plan.")
    assert "goal_submit" in capsys.readouterr().err


async def test_sessions_inspect_replays_the_transcript_read_only(tmp_path):
    from app.cli.v2.sessions import format_transcript, inspect_session

    session_root = tmp_path / "runtime"
    model = ScriptedModelProvider((*write_hello_model()._steps, *talk_model("bye")._steps))
    _, _, agent, command = await make_agent(tmp_path, model)
    renderer = PlainRenderer(io.StringIO(), io.StringIO())
    first = await run_task(
        agent, command, CONTEXT, renderer=renderer, decider=StaticInteractionDecider("approve_once")
    )
    spec_hash = agent.application.composition_hash
    second = await run_task(
        agent,
        build_start_run(
            agent_id="coder",
            task="say bye",
            resolved_spec_hash=spec_hash,
            session_id=first.session_id,
        ),
        CONTEXT,
        renderer=renderer,
        decider=StaticInteractionDecider("deny"),
    )
    await agent.close()

    transcript = inspect_session(session_root, first.session_id)
    assert transcript.summary.run_count == 2
    assert [run.run_id for run in transcript.runs] == [first.run_id, second.run_id]
    kinds = [(entry.kind, entry.text) for entry in transcript.runs[0].entries]
    assert kinds[0] == ("user", "create hello.txt")
    assert ("assistant", "Writing hello.txt") in kinds
    assert ("interaction", "approval -> approve_once") in kinds
    assert ("tool", "file_write succeeded") in kinds
    assert kinds[-1] == ("assistant", "Done.")
    assert [(e.kind, e.text) for e in transcript.runs[1].entries] == [
        ("user", "say bye"),
        ("assistant", "bye"),
    ]
    text = format_transcript(transcript)
    assert "> create hello.txt" in text
    assert "[tool] file_write succeeded" in text
    assert transcript.to_json()["runs"][1]["entries"][-1] == {"kind": "assistant", "text": "bye"}

    with pytest.raises(FileNotFoundError):
        inspect_session(session_root, "session_missing")


async def test_v2_sessions_inspect_command_prints_json(tmp_path, monkeypatch, capsys):
    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "test-key")

    async def build_agent(**kwargs):
        return await build_cli_application(**kwargs, model_provider=talk_model("hi"))

    with _patched_cfg():
        assert (
            await v2_command.v2_run_command(_command_args(tmp_path), build_agent_fn=build_agent)
            == 0
        )
        capsys.readouterr()
        listing = await v2_command.v2_sessions_command(
            argparse.Namespace(
                limit=5, session_root=str(tmp_path / "runtime"), json=True, verbose=False
            )
        )
        session_id = json.loads(capsys.readouterr().out)["list"][0]["session_id"]
        exit_code = await v2_command.v2_sessions_command(
            argparse.Namespace(
                sessions_command="inspect",
                session_id=session_id,
                session_root=str(tmp_path / "runtime"),
                json=True,
                verbose=False,
            )
        )
        payload = json.loads(capsys.readouterr().out)
        with pytest.raises(CLIError):
            await v2_command.v2_sessions_command(
                argparse.Namespace(
                    sessions_command="inspect",
                    session_id="session_missing",
                    session_root=str(tmp_path / "runtime"),
                    json=False,
                    verbose=False,
                )
            )

    assert listing == 0 and exit_code == 0
    assert payload["session"]["session_id"] == session_id
    assert payload["runs"][0]["entries"] == [
        {"kind": "user", "text": "create hello.txt"},
        {"kind": "assistant", "text": "hi"},
    ]


def test_parser_v2_mode_and_sessions_inspect():
    parser = build_argument_parser()
    run = parser.parse_args(["v2", "run", "x", "--mode", "plan"])
    assert run.mode == "plan"
    assert parser.parse_args(["v2", "chat"]).mode == "normal"
    inspect = parser.parse_args(["v2", "sessions", "inspect", "session_abc", "--json"])
    assert (inspect.sessions_command, inspect.session_id, inspect.json) == (
        "inspect",
        "session_abc",
        True,
    )


# ---------- shell 工具：CLI job runtime ----------


def shell_model(command="printf hello-from-shell"):
    return ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    _completed(
                        "",
                        calls=(
                            ModelToolCall(
                                tool_call_id="call_sh",
                                name="execute_shell_command",
                                arguments={"command": command},
                            ),
                        ),
                    ),
                )
            ),
            ScriptedModelStep(events=(_completed("shell done"),)),
        )
    )


def shell_tool_result(request):
    """execute_shell_command 的结果是 JsonBlock：从第二次模型请求的 tool 消息里取出来。"""

    for message in request.messages:
        if message.role != "tool":
            continue
        for block in message.content:
            if getattr(block, "kind", None) == "json":
                return block.value
    raise AssertionError("no json tool result in request")


async def make_shell_agent(tmp_path, model, *, read_only=False):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    package = build_preset_package("coder", MODEL)
    bindings = LocalWorkspaceBindingProvider(
        workspace, settings=WorkspaceSandboxSettings(read_only=read_only)
    )
    application = await build_cli_application(
        package=package,
        session_root=tmp_path / "runtime",
        bindings=bindings,
        model_provider=model,
    )
    command = build_start_run(
        agent_id="coder", task="run it", resolved_spec_hash=application.composition_hash
    )
    return workspace, bindings, ClosableAgent(application), command


async def test_binding_carries_the_request_lifecycle_so_suspension_hooks_do_not_raise(tmp_path):
    from sagents.v2.runtime.execution import ExecutionBindingRequest

    provider = LocalWorkspaceBindingProvider(tmp_path)
    binding = await provider.acquire(
        ExecutionBindingRequest(run_id="run_1", agent_id="coder", context=CONTEXT)
    )
    try:
        assert binding.lifecycle is None
        await binding.on_suspended(CONTEXT)  # 不能因缺少属性而抛 AttributeError
    finally:
        await binding.close()


async def test_shell_tool_runs_inside_the_run_sandbox_via_cli_job_runtime(tmp_path):
    from app.cli.v2.jobs import CliShellJobRuntime

    model = shell_model()
    _, _, agent, command = await make_shell_agent(tmp_path, model)
    assert isinstance(
        agent.application.services["execution.job-runtime"], CliShellJobRuntime
    )
    outcome = await run_task(
        agent,
        command,
        CONTEXT,
        renderer=PlainRenderer(io.StringIO(), io.StringIO()),
        decider=StaticInteractionDecider("approve_once"),
    )
    await agent.close()

    assert outcome.state == RunState.COMPLETED
    assert "tool.call.succeeded" in outcome.event_types
    result = shell_tool_result(model.requests[1])
    assert result["success"] is True
    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert result["stdout"] == "hello-from-shell"


async def test_read_only_sandbox_rejects_mutating_shell_commands(tmp_path):
    model = shell_model("rm -rf important")
    _, _, agent, command = await make_shell_agent(tmp_path, model, read_only=True)
    err = io.StringIO()
    outcome = await run_task(
        agent,
        command,
        CONTEXT,
        renderer=PlainRenderer(io.StringIO(), err),
        decider=StaticInteractionDecider("approve_once"),
    )
    await agent.close()

    # 本地 workspace 沙箱在只读策略下拒绝任何进程执行；工具以结构化失败告知模型，文件未动。
    assert outcome.state == RunState.COMPLETED
    result = shell_tool_result(model.requests[1])
    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error"]["code"] == "job.runner_failed"
    assert "read-only" in result["error"]["message"]
    assert "kind_unsupported" not in err.getvalue()


async def test_cli_job_runtime_refuses_shell_jobs_without_a_live_binding():
    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.contracts.jobs import JobSpec

    from app.cli.v2.jobs import CliShellJobRuntime

    class NoBindings:
        def binding_for_run(self, run_id):
            return None

    runtime = CliShellJobRuntime(NoBindings())
    handle = await runtime.submit(
        JobSpec(
            owner_run_id="run_x",
            kind="official.shell",
            payload={"command": "true", "cwd": "/tmp", "tool_call_id": "c"},
            idempotency_key="k",
        )
    )
    snapshot = await runtime.wait(handle.job_id)
    assert snapshot.state.value == "failed"
    await runtime.close()

    async def emit(stream, data):
        return None

    with pytest.raises(SageV2Error) as raised:
        await runtime._run_shell(
            JobSpec(
                owner_run_id="run_x",
                kind="official.shell",
                payload={"command": "true", "cwd": "/tmp", "tool_call_id": "c"},
                idempotency_key="k2",
            ),
            emit,
            None,
        )
    assert raised.value.info.code == "job.sandbox_unavailable"


def test_packages_select_the_cli_job_runtime(tmp_path):
    from app.cli.v2.package import (
        CLI_JOB_RUNTIME_PLUGIN,
        JOB_RUNTIME_CAPABILITY,
        with_cli_job_runtime,
    )

    preset = build_preset_package("coder", MODEL)
    assert preset.runtime.capabilities[JOB_RUNTIME_CAPABILITY].plugin == CLI_JOB_RUNTIME_PLUGIN
    assert with_cli_job_runtime(preset) is preset
    bare = preset.model_copy(
        update={
            "runtime": preset.runtime.model_copy(
                update={
                    "capabilities": {
                        k: v
                        for k, v in preset.runtime.capabilities.items()
                        if k != JOB_RUNTIME_CAPABILITY
                    }
                }
            )
        }
    )
    assert JOB_RUNTIME_CAPABILITY not in bare.runtime.capabilities
    assert (
        with_cli_job_runtime(bare).runtime.capabilities[JOB_RUNTIME_CAPABILITY].plugin
        == CLI_JOB_RUNTIME_PLUGIN
    )


# ---------- C1-g：运行中输入 → SteerRun ----------


class GatedListDirModel:
    """第 1 步等放行后调用 list_dir（无需审批），第 2 步收尾；用于在模型步骤之间注入 steer。"""

    def __init__(self):
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()
        self.requests = []

    async def capabilities(self, model_binding):
        from sagents.v2.model.contracts import ModelCapabilities

        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_parallel_tool_calls=False,
            supports_reasoning=False,
            supports_multimodal_input=False,
            supports_structured_output=False,
        )

    def stream(self, request):
        return self._stream(request)

    async def _stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            self.first_started.set()
            await self.release_first.wait()
            yield _completed(
                "",
                calls=(ModelToolCall(tool_call_id="c1", name="list_dir", arguments={}),),
            )
        else:
            yield _completed("done")


async def test_typing_during_a_run_steers_the_next_model_step(tmp_path):
    model = GatedListDirModel()
    _, _, agent, command = await make_agent(tmp_path, model)
    accepted = asyncio.Event()
    err = io.StringIO()

    class Observer(PlainRenderer):
        def handle(self, event):
            super().handle(event)
            if event.type == "steer.accepted":
                accepted.set()

    sent = {"count": 0}

    async def steer_source():
        if sent["count"] == 0:
            sent["count"] += 1
            await model.first_started.wait()
            return "also check the tests"
        await asyncio.Event().wait()  # 之后不再有输入；结束时会被取消

    async def release_when_accepted():
        await accepted.wait()
        model.release_first.set()

    releaser = asyncio.create_task(release_when_accepted())
    outcome = await asyncio.wait_for(
        run_task(
            agent,
            command,
            CONTEXT,
            renderer=Observer(io.StringIO(), err),
            decider=StaticInteractionDecider("deny"),
            steer_source=steer_source,
        ),
        timeout=1.8,
    )
    await releaser
    await agent.close()

    assert outcome.state == RunState.COMPLETED
    assert "steer.accepted" in outcome.event_types
    assert "steer.applied" in outcome.event_types
    assert "also check the tests" in _request_texts(model.requests[1])
    assert "(steer) queued for the next model step: also check the tests" in err.getvalue()


async def test_steerer_parses_frames_and_defers_until_the_turn_starts():
    from app.cli.v2.runner import JSON_STEER_TYPE, _Steerer

    notices: list[str] = []
    frames: list[dict] = []
    renderer = SimpleNamespace(notice=notices.append, frame=frames.append)

    json_steerer = _Steerer(None, "run_1", CONTEXT, renderer, None, json_frames=True)
    assert json_steerer.parse(json.dumps({"type": JSON_STEER_TYPE, "text": " go "})) == "go"
    assert json_steerer.parse("garbage") is None
    assert json_steerer.parse(json.dumps({"type": JSON_DECISION_TYPE, "decision": "deny"})) is None
    assert frames[-1]["status"] == "rejected"
    assert frames[-1]["detail"] == "no interaction is pending"

    plain = _Steerer(None, "run_1", CONTEXT, renderer, None, json_frames=False)
    assert plain.parse("   ") is None
    assert plain.parse("/help") is None
    assert "not available while a run is active" in notices[-1]
    assert plain.parse("more detail please") == "more detail please"
    assert await plain.submit("early") is False
    assert plain.pending == ["early"]


async def test_steering_is_enabled_only_for_tty_or_json_stdin(tmp_path, monkeypatch, capsys):
    (tmp_path / "workspace").mkdir()
    monkeypatch.setenv("SAGE_DEFAULT_LLM_API_KEY", "test-key")

    async def build_agent(**kwargs):
        return await build_cli_application(**kwargs, model_provider=talk_model("x"))

    with _patched_cfg():
        piped = await v2_command.open_cli_session(
            _command_args(tmp_path), build_agent_fn=build_agent, stdin=StdinLineReader(io.StringIO(""))
        )
        try:
            assert piped.steer_enabled is False
        finally:
            await piped.close()
        driven = await v2_command.open_cli_session(
            _command_args(tmp_path, json=True),
            build_agent_fn=build_agent,
            stdin=StdinLineReader(io.StringIO("")),
        )
        try:
            assert driven.steer_enabled is True
            assert driven._steer_kwargs()["steer_json"] is True
        finally:
            await driven.close()
    capsys.readouterr()


async def test_steer_accepted_after_the_last_model_step_is_reported_as_unapplied(tmp_path):
    """模型一步收尾时，已接受的 steer 没有下一步可应用：不能静默丢掉。"""

    class GatedOneStepModel(GatedListDirModel):
        async def _stream(self, request):
            self.requests.append(request)
            self.first_started.set()
            await self.release_first.wait()
            yield _completed("done in one step")

    model = GatedOneStepModel()
    _, _, agent, command = await make_agent(tmp_path, model)
    accepted = asyncio.Event()
    err = io.StringIO()

    class Observer(PlainRenderer):
        def handle(self, event):
            super().handle(event)
            if event.type == "steer.accepted":
                accepted.set()

    sent = {"count": 0}

    async def steer_source():
        if sent["count"] == 0:
            sent["count"] += 1
            await model.first_started.wait()
            return "one more thing"
        await asyncio.Event().wait()

    async def release_when_accepted():
        await accepted.wait()
        model.release_first.set()

    releaser = asyncio.create_task(release_when_accepted())
    outcome = await asyncio.wait_for(
        run_task(
            agent,
            command,
            CONTEXT,
            renderer=Observer(io.StringIO(), err),
            decider=StaticInteractionDecider("deny"),
            steer_source=steer_source,
        ),
        timeout=1.8,
    )
    await releaser
    await agent.close()

    assert outcome.state == RunState.COMPLETED
    assert "steer.accepted" in outcome.event_types
    assert "steer.applied" not in outcome.event_types
    assert outcome.unapplied_steers == ("one more thing",)
    assert "(steer) the run ended before it could be applied: one more thing" in err.getvalue()
