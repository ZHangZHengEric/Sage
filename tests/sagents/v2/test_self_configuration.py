from contextlib import asynccontextmanager

import pytest

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.agent.policy.tool_policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.agent.self_configuration import (
    SelfConfigurationRequest,
    SelfConfigurationService,
    SqliteSelfConfigurationStore,
)
from sagents.v2.context import DefaultContextAssembler
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.skill.context import (
    ActiveSkillsContextProvider,
    AvailableSkillsContextProvider,
)
from sagents.v2.skill.plugins.ephemeral import (
    InMemorySkillActivationRepository,
    InMemorySkillProvider,
    InMemorySkillWorkspace,
)
from sagents.v2.skill.provider import (
    FilteredSkillCatalog,
    InvocationGrantSkillCatalog,
    SkillLoader,
)
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.tool.contracts import ReconcileState, ToolCall
from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog, InMemoryToolExecutor

CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="user",
        tenant_id="user",
        principal_type=PrincipalType.USER,
        scopes=("skill.load", "tool.external_side_effect"),
    )
)


async def allow(request, context):
    assert context.actor.principal_id == "user"


def loader():
    source = InMemorySkillProvider(())
    return SkillLoader(
        catalog=FilteredSkillCatalog(source, ()),
        source=source,
        workspace=InMemorySkillWorkspace(),
        activations=InMemorySkillActivationRepository(),
    )


def service(tmp_path, *, owner="user:agent", authorize=allow, factory=None):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return SelfConfigurationService(
        store=SqliteSelfConfigurationStore(
            tmp_path / "private" / "capabilities.sqlite3"
        ),
        owner=owner,
        workspace_root=workspace,
        workspace_alias="/workspace",
        authorize=authorize,
        mcp_session_factory=factory,
    )


def bind(controller, skills=None):
    return controller.bind(
        InMemoryToolCatalog(()), InMemoryToolExecutor({}, {}), skills or loader()
    )


def skill(tmp_path, name="review", content="# Review\nCheck edge cases."):
    path = tmp_path / "workspace" / "downloads" / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(content)
    return path


def call(arguments, *, run="run1", operation="configure1", name="agent_self_configure"):
    return ToolCall(
        tool_call_id=operation,
        operation_id=operation,
        idempotency_key=operation,
        tool_name=name,
        arguments=arguments,
        owner_run_id=run,
    )


def completed(*calls, text=""):
    return ScriptedModelStep(
        events=(
            ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="response",
                    text=text,
                    tool_calls=calls,
                    finish_reason="tool_calls" if calls else "stop",
                ),
            ),
        )
    )


@pytest.mark.asyncio
async def test_skill_is_staged_then_usable_and_survives_source_deletion(tmp_path):
    controller = service(tmp_path)
    skills = loader()
    bind(controller, skills)
    await controller.prepare("run1", CONTEXT)
    path = skill(tmp_path)
    result = await controller.execute(call({"add_skill_paths": [str(path)]}), CONTEXT)
    assert result.content[0].value["effective"] == "next_model_step"
    assert not await skills.catalog.list_skills(run_id="run1")
    (path / "SKILL.md").unlink()
    await controller.prepare("run1", CONTEXT)
    loaded = await skills.load("review", run_id="run1")
    assert "Check edge cases" in loaded.instructions
    assert loaded.workspace_path.startswith("/workspace/.sage-capabilities/")
    assert (
        tmp_path
        / "workspace"
        / loaded.workspace_path.removeprefix("/workspace/")
        / "SKILL.md"
    ).exists()


@pytest.mark.asyncio
async def test_next_model_step_sees_and_loads_new_skill_with_empty_initial_grant(
    tmp_path,
):
    controller = service(tmp_path)
    skill(tmp_path)
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(
        StartRun(
            agent_id="agent",
            input=(InputItem(role="user", content=(TextBlock(text="review"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="start",
            config=RunConfig(
                model_bindings={"primary": "test"},
                enabled_tools=(),
                enabled_skills=(),
                max_steps=5,
            ),
        ),
        CONTEXT,
    )
    source = InMemorySkillProvider(())
    skills = loader()
    skills.catalog = InvocationGrantSkillCatalog(
        FilteredSkillCatalog(source, ()), runtime.session_store.get_start_command
    )

    def sees_new_skill(request):
        assert "load_skill" in {tool.name for tool in request.tools}
        assert "review" in str(request.messages)
        assert "agent_self_configure" in {tool.name for tool in request.tools}

    step2 = completed(
        ModelToolCall(
            tool_call_id="load", name="load_skill", arguments={"skill_name": "review"}
        )
    )
    model = ScriptedModelProvider(
        (
            completed(
                ModelToolCall(
                    tool_call_id="configure",
                    name="agent_self_configure",
                    arguments={"add_skill_paths": ["downloads/review"]},
                )
            ),
            ScriptedModelStep(events=step2.events, assertion=sees_new_skill),
            completed(text="done"),
        )
    )
    engine = AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
        self_configuration=controller,
        skill_loader=skills,
        tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE),
        context_assembler=DefaultContextAssembler(
            history_reader=runtime.session_store,
            providers=(
                AvailableSkillsContextProvider(skills.catalog),
                ActiveSkillsContextProvider(skills),
            ),
        ),
    )
    result = await engine.execute(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    assert "Check edge cases" in str(model.requests[2].messages)
    # A host can reuse the original loader for a child; root additions do not leak.
    assert await skills.catalog.list_skills(run_id=handle.run_id) == ()


@pytest.mark.asyncio
async def test_mcp_route_is_available_only_after_safe_boundary(tmp_path):
    class Session:
        async def list_tools(self):
            return {
                "tools": [
                    {
                        "name": "lookup",
                        "description": "lookup",
                        "inputSchema": {"type": "object"},
                    }
                ]
            }

        async def call_tool(self, name, arguments):
            return {"content": [{"type": "text", "text": "found"}], "isError": False}

    @asynccontextmanager
    async def factory(config):
        yield Session()

    controller = service(tmp_path, factory=factory)
    catalog, executor = bind(controller)
    await controller.prepare("run1", CONTEXT)
    await executor.execute(
        call(
            {
                "add_mcp_servers": [
                    {
                        "name": "docs",
                        "protocol": "streamable_http",
                        "url": "https://mcp.test",
                    }
                ]
            }
        ),
        CONTEXT,
    )
    assert "mcp_docs_lookup" not in {
        tool.name for tool in await catalog.list_tools(run_id="run1")
    }
    await controller.prepare("run1", CONTEXT)
    assert "mcp_docs_lookup" in {
        tool.name for tool in await catalog.list_tools(run_id="run1")
    }
    result = await executor.execute(
        call({}, name="mcp_docs_lookup", operation="lookup1"), CONTEXT
    )
    assert result.content[0].text == "found"


@pytest.mark.asyncio
async def test_run_restore_defaults_and_owner_isolation(tmp_path):
    first = service(tmp_path)
    bind(first)
    await first.prepare("run1", CONTEXT)
    # A pre-existing Run keeps its own revision, even after another Run changes defaults.
    old = service(tmp_path)
    bind(old)
    await old.prepare("old", CONTEXT)
    skill(tmp_path)
    invocation = call({"add_skill_paths": ["downloads/review"]})
    await first.execute(invocation, CONTEXT)
    restored = service(tmp_path)
    bind(restored)
    await restored.prepare("run1", CONTEXT)
    assert "review" in restored.bundles
    receipt = await restored.reconcile_call(invocation, CONTEXT)
    assert receipt.state == ReconcileState.SUCCEEDED
    fresh = service(tmp_path)
    bind(fresh)
    await fresh.prepare("new", CONTEXT)
    assert "review" in fresh.bundles
    await old.prepare("old", CONTEXT)
    assert not old.bundles
    other = service(tmp_path, owner="other:agent")
    bind(other)
    await other.prepare("new", CONTEXT)
    assert not other.bundles


@pytest.mark.asyncio
async def test_authorization_failure_never_discovers_or_commits(tmp_path):
    async def deny(request, context):
        if request.add_skill_paths or request.add_mcp_servers:
            raise PermissionError("denied")

    controller = service(tmp_path, authorize=deny)
    bind(controller)
    await controller.prepare("run1", CONTEXT)
    skill(tmp_path)
    with pytest.raises(PermissionError):
        await controller.execute(
            call({"add_skill_paths": ["downloads/review"]}), CONTEXT
        )
    assert (await controller.store.read(controller.owner, "run1"))["revision"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_path", ["../outside", "/etc", "link"])
async def test_workspace_escape_and_symlink_are_rejected(tmp_path, bad_path):
    controller = service(tmp_path)
    bind(controller)
    await controller.prepare("run1", CONTEXT)
    (tmp_path / "workspace" / "link").symlink_to(tmp_path)
    with pytest.raises(SageV2Error):
        await controller.execute(call({"add_skill_paths": [bad_path]}), CONTEXT)
    assert (await controller.store.read(controller.owner, "run1"))["revision"] == 0


@pytest.mark.asyncio
async def test_failed_mcp_discovery_does_not_partially_add_skill(tmp_path):
    @asynccontextmanager
    async def fail(config):
        raise RuntimeError("unreachable")
        yield  # pragma: no cover

    controller = service(tmp_path, factory=fail)
    bind(controller)
    await controller.prepare("run1", CONTEXT)
    skill(tmp_path)
    with pytest.raises(SageV2Error):
        await controller.execute(
            call(
                {
                    "add_skill_paths": ["downloads/review"],
                    "add_mcp_servers": [
                        {
                            "name": "docs",
                            "protocol": "streamable_http",
                            "url": "https://mcp.test",
                        }
                    ],
                }
            ),
            CONTEXT,
        )
    assert not (await controller.store.read(controller.owner, "run1"))["skills"]


@pytest.mark.asyncio
async def test_identical_retry_reuses_receipt_and_different_arguments_conflict(
    tmp_path,
):
    controller = service(tmp_path)
    bind(controller)
    await controller.prepare("run1", CONTEXT)
    skill(tmp_path)
    request = call({"add_skill_paths": ["downloads/review"]})
    await controller.execute(request, CONTEXT)
    await controller.execute(request, CONTEXT)
    assert (await controller.store.read(controller.owner, "run1"))["revision"] == 1
    with pytest.raises(SageV2Error):
        await controller.execute(call({}), CONTEXT)


def test_credentials_are_not_part_of_configuration_schema():
    with pytest.raises(ValueError):
        SelfConfigurationRequest.model_validate(
            {
                "add_mcp_servers": [
                    {
                        "name": "docs",
                        "protocol": "streamable_http",
                        "url": "https://mcp.test",
                        "api_key": "secret",
                    }
                ]
            }
        )


@pytest.mark.asyncio
async def test_public_builder_exposes_self_configuration_without_initial_skills(
    tmp_path,
):
    from sagents.v2 import SAgentBuilder
    from sagents.v2.package.presets import BuiltinPackageFactory

    service(tmp_path)  # Prepare the host workspace before the Builder runs.
    skill(tmp_path)
    source = InMemorySkillProvider(())
    model = ScriptedModelProvider(
        (
            completed(
                ModelToolCall(
                    tool_call_id="configure",
                    name="agent_self_configure",
                    arguments={"add_skill_paths": ["downloads/review"]},
                )
            ),
            completed(
                ModelToolCall(
                    tool_call_id="load",
                    name="load_skill",
                    arguments={"skill_name": "review"},
                )
            ),
            completed(text="done"),
        )
    )
    package = BuiltinPackageFactory.create(
        "assistant", package_id="test.self-configuration", model="test-model"
    )
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path / "sessions")
        .with_model_provider(model)
        .with_tool_provider(InMemoryToolCatalog(()), InMemoryToolExecutor({}, {}))
        .with_skill_provider(source, source, InMemorySkillWorkspace())
        .with_tool_policy(
            DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)
        )
        .with_self_configuration(
            lambda agent_id: service(tmp_path, owner=f"user:{agent_id}")
        )
        .build(package)
    )
    try:
        stream = await application.entrypoint().run_stream(
            StartRun(
                agent_id=package.entrypoint.agent,
                input=(InputItem(role="user", content=(TextBlock(text="review"),)),),
                resolved_spec_hash=application.composition_hash,
                idempotency_key="builder-self-configure",
            ),
            CONTEXT,
        )
        result = await stream.wait()
        assert result.state == RunState.COMPLETED
        assert "Check edge cases" in str(model.requests[-1].messages)
    finally:
        await application.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_snapshot", [False, True])
async def test_paused_run_restores_capabilities_with_fresh_engine_or_fails_closed(
    tmp_path, remove_snapshot
):
    import asyncio
    import sqlite3
    from sagents.v2.contracts.commands import PauseRun, ResumeRun

    controller = service(tmp_path)
    skill(tmp_path)
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(
        StartRun(
            agent_id="agent",
            input=(InputItem(role="user", content=(TextBlock(text="review"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="pause-start",
            config=RunConfig(model_bindings={"primary": "test"}, max_steps=5),
        ),
        CONTEXT,
    )
    waiting = asyncio.Event()

    class Model(ScriptedModelProvider):
        async def _stream(self, request):
            if self.requests:
                waiting.set()
                await asyncio.Event().wait()
            async for event in super()._stream(request):
                yield event

    model = Model(
        (
            completed(
                ModelToolCall(
                    tool_call_id="configure",
                    name="agent_self_configure",
                    arguments={
                        "add_skill_paths": ["downloads/review"],
                        "system_prompt": "Resume with concise answers.",
                    },
                )
            ),
        )
    )

    def engine(config, model):
        skills = loader()
        return AgentLoopEngine(
            runtime=runtime,
            model=model,
            tool_catalog=InMemoryToolCatalog(()),
            tool_executor=InMemoryToolExecutor({}, {}),
            self_configuration=config,
            skill_loader=skills,
            tool_policy=DefaultToolPolicy(
                approval_strategy=ApprovalStrategy.AUTO_APPROVE
            ),
        )

    first = engine(controller, model)
    execution = asyncio.create_task(first.execute(handle.run_id, CONTEXT))
    await asyncio.wait_for(waiting.wait(), timeout=5)
    current = await runtime.get_run(handle.run_id)
    await runtime.pause_run(
        PauseRun(
            run_id=handle.run_id,
            expected_revision=current.revision,
            idempotency_key="pause",
        ),
        CONTEXT,
    )
    suspended = await asyncio.wait_for(execution, timeout=5)
    assert suspended.state == RunState.SUSPENDED
    checkpoint = await runtime.session_store.get_latest_checkpoint(handle.run_id)
    assert checkpoint.state["self_configuration_revision"] == 1
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    await runtime.resume_run(
        ResumeRun(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=suspension.expected_revision,
            idempotency_key="resume",
        ),
        CONTEXT,
    )
    if remove_snapshot:
        with sqlite3.connect(controller.store.path) as db:
            db.execute("DELETE FROM runs")
    resumed_model = ScriptedModelProvider(
        (
            completed(
                ModelToolCall(
                    tool_call_id="load",
                    name="load_skill",
                    arguments={"skill_name": "review"},
                )
            ),
            completed(text="done"),
        )
    )
    fresh = engine(service(tmp_path), resumed_model)
    if remove_snapshot:
        with pytest.raises(SageV2Error, match="revision is missing"):
            await fresh.resume(handle.run_id, CONTEXT)
        assert not resumed_model.requests
    else:
        result = await fresh.resume(handle.run_id, CONTEXT)
        assert result.state == RunState.COMPLETED
        assert "Check edge cases" in str(resumed_model.requests[-1].messages)
        assert "Resume with concise answers." in str(
            resumed_model.requests[-1].messages
        )


@pytest.mark.asyncio
async def test_next_model_step_sees_and_executes_new_mcp_tool(tmp_path):
    calls = []

    class Session:
        async def list_tools(self):
            return {
                "tools": [
                    {
                        "name": "lookup",
                        "description": "lookup",
                        "inputSchema": {"type": "object"},
                    }
                ]
            }

        async def call_tool(self, name, arguments):
            calls.append(name)
            return {
                "content": [{"type": "text", "text": "remote answer"}],
                "isError": False,
            }

    @asynccontextmanager
    async def factory(config):
        yield Session()

    controller = service(tmp_path, factory=factory)
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(
        StartRun(
            agent_id="agent",
            input=(InputItem(role="user", content=(TextBlock(text="lookup"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="mcp-start",
            config=RunConfig(model_bindings={"primary": "test"}, max_steps=5),
        ),
        CONTEXT,
    )

    def sees_remote_tool(request):
        assert "mcp_docs_lookup" in {tool.name for tool in request.tools}

    step2 = completed(
        ModelToolCall(tool_call_id="lookup", name="mcp_docs_lookup", arguments={})
    )
    model = ScriptedModelProvider(
        (
            completed(
                ModelToolCall(
                    tool_call_id="configure",
                    name="agent_self_configure",
                    arguments={
                        "add_mcp_servers": [
                            {
                                "name": "docs",
                                "protocol": "streamable_http",
                                "url": "https://mcp.test",
                            }
                        ]
                    },
                )
            ),
            ScriptedModelStep(events=step2.events, assertion=sees_remote_tool),
            completed(text="done"),
        )
    )
    engine = AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
        self_configuration=controller,
        skill_loader=loader(),
        tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE),
    )
    result = await engine.execute(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    assert calls == ["lookup"], str(model.requests[-1].messages)
    assert "remote answer" in str(model.requests[-1].messages)


@pytest.mark.asyncio
async def test_system_prompt_is_staged_replaced_cleared_and_isolated(tmp_path):
    controller = service(tmp_path)
    _, executor = bind(controller)
    await controller.prepare("run1", CONTEXT)
    # Freeze another Run before the change.
    await controller.store.read(controller.owner, "old")
    assert (
        await executor.execute(call({}, operation="initial-inspect"), CONTEXT)
    ).content
    await executor.execute(call({"system_prompt": "Use concise Chinese."}), CONTEXT)
    assert controller.system_prompt == ""
    await controller.prepare("run1", CONTEXT)
    assert controller.system_prompt == "Use concise Chinese."
    segments = await controller.segments(None)
    assert segments[-1].segment_id == "agent_self_instructions"
    assert "cannot override" in segments[-1].content
    restored = service(tmp_path)
    bind(restored)
    await restored.prepare("run1", CONTEXT)
    assert restored.system_prompt == controller.system_prompt
    newer = service(tmp_path)
    bind(newer)
    await newer.prepare("new", CONTEXT)
    assert newer.system_prompt == controller.system_prompt
    old = service(tmp_path)
    bind(old)
    await old.prepare("old", CONTEXT)
    assert old.system_prompt == ""
    other_owner = service(tmp_path, owner="other")
    bind(other_owner)
    await other_owner.prepare("run1", CONTEXT)
    assert other_owner.system_prompt == ""
    # Reading or adding a Skill must not clear the instructions.
    query = await executor.execute(call({}, operation="inspect"), CONTEXT)
    assert query.content[0].value["system_prompt"] == "Use concise Chinese."
    skill(tmp_path)
    await executor.execute(
        call({"add_skill_paths": ["downloads/review"]}, operation="skill"), CONTEXT
    )
    await controller.prepare("run1", CONTEXT)
    assert controller.system_prompt == "Use concise Chinese."
    await executor.execute(
        call({"system_prompt": "Be explicit."}, operation="replace"), CONTEXT
    )
    await controller.prepare("run1", CONTEXT)
    assert controller.system_prompt == "Be explicit."
    await executor.execute(call({"system_prompt": ""}, operation="clear"), CONTEXT)
    await controller.prepare("run1", CONTEXT)
    assert controller.system_prompt == ""
    assert "agent_self_instructions" not in {
        s.segment_id for s in await controller.segments(None)
    }


@pytest.mark.asyncio
async def test_system_prompt_stale_run_cannot_overwrite_new_defaults(tmp_path):
    first = service(tmp_path)
    _, executor = bind(first)
    await first.prepare("run1", CONTEXT)
    second = service(tmp_path)
    _, other = bind(second)
    await second.prepare("run2", CONTEXT)
    await executor.execute(call({"system_prompt": "First."}), CONTEXT)
    with pytest.raises(ValueError, match="another Run"):
        await other.execute(call({"system_prompt": "Second."}, run="run2"), CONTEXT)
    assert (await first.store.read(first.owner, "run2"))["revision"] == 0
    assert await first.store.receipt(first.owner, "run2", "configure1") is None
    assert (await first.store.read(first.owner, "future"))["system_prompt"] == "First."


@pytest.mark.asyncio
async def test_system_prompt_is_idempotent_and_bounded(tmp_path):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SelfConfigurationRequest(system_prompt="x" * 32769)
    controller = service(tmp_path)
    _, executor = bind(controller)
    await controller.prepare("run1", CONTEXT)
    request = call({"system_prompt": "Keep focused."})
    first = await executor.execute(request, CONTEXT)
    second = await executor.execute(request, CONTEXT)
    assert first.content == second.content
    assert (await controller.store.read(controller.owner, "run1"))["revision"] == 1


@pytest.mark.asyncio
async def test_system_prompt_reaches_next_model_step_without_replacing_host_rules(
    tmp_path,
):
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(
        StartRun(
            agent_id="agent",
            input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="prompt-start",
            config=RunConfig(model_bindings={"primary": "test"}, max_steps=5),
        ),
        CONTEXT,
    )
    prompt = "Answer in concise Chinese."
    model = ScriptedModelProvider(
        (
            completed(
                ModelToolCall(
                    tool_call_id="configure",
                    name="agent_self_configure",
                    arguments={"system_prompt": prompt},
                )
            ),
            completed(text="done"),
        )
    )
    engine = AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
        self_configuration=service(tmp_path),
        skill_loader=loader(),
        tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE),
        context_assembler=DefaultContextAssembler(
            history_reader=runtime.session_store,
            system_instructions="Host permission rules are mandatory.",
            developer_instructions="Host role definition.",
        ),
    )
    assert (await engine.execute(handle.run_id, CONTEXT)).state == RunState.COMPLETED

    def system_text(request):
        return "\n".join(str(m.content) for m in request.messages if m.role == "system")

    assert prompt not in system_text(model.requests[0])
    assert prompt in system_text(model.requests[1])
    for request in model.requests:
        assert "Host permission rules are mandatory." in system_text(request)
        assert "Host role definition." in system_text(request)


@pytest.mark.asyncio
async def test_system_prompt_requires_host_authorization(tmp_path):
    async def authorize(request, context):
        if request.system_prompt is not None:
            raise PermissionError("instructions denied")

    controller = service(tmp_path, authorize=authorize)
    _, executor = bind(controller)
    await controller.prepare("run1", CONTEXT)
    with pytest.raises(PermissionError, match="instructions denied"):
        await executor.execute(call({"system_prompt": "Change my role."}), CONTEXT)
    snapshot = await controller.store.read(controller.owner, "run1")
    assert snapshot["revision"] == 0
    assert snapshot.get("system_prompt", "") == ""
