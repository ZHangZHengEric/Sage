from pathlib import Path
from contextlib import asynccontextmanager
from datetime import timedelta

from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.runtime.execution.scheduler import WorkItem, LeaseReleaseReason
from sagents.v2.agent.policy.continuation import CompositeContinuationPolicy
from sagents.v2.tool.plugins.selection_direct import DirectToolSelectionPolicy
from sagents.v2.model import (
    ScriptedModelProvider,
    ModelEventKind,
    ModelStreamEvent,
    ModelResponse,
    ModelToolCall,
)
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep

import pytest
from pydantic import ValidationError

from app.desktop_v2.backend.schemas import (
    DesktopRunRequest,
    RunMessage,
    ModelProviderPatch,
    AgentSettingsPatch,
)
from app.desktop_v2.backend.service import DesktopV2Service
from app.desktop_v2.backend.studio import (
    StudioStore,
    StudioSyncRequest,
    StudioMemberInput,
    StudioHistoryInput,
    STUDIO_TOOLS,
    StudioContextProvider,
    DesktopStudioMixin,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.tool import ToolCall


@asynccontextmanager
async def execution_lease(service, run_id):
    work_id = new_id("studio_test")
    await service.scheduler.submit(
        WorkItem(
            work_id=work_id,
            run_id=run_id,
            available_at=utc_now(),
            idempotency_key=work_id,
        )
    )
    lease = await service.scheduler.claim(
        "studio-test", lease_duration=timedelta(seconds=30), wait_timeout=0
    )
    assert lease is not None
    async with service.driver_session_store.lease_scope(lease):
        yield
    await service.scheduler.release(lease, LeaseReleaseReason.COMPLETED, requeue=False)


def scripted_step(text="", calls=(), assertion=None):
    return ScriptedModelStep(
        assertion=assertion,
        events=(
            ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id=new_id("response"),
                    text=text,
                    tool_calls=calls,
                    finish_reason="tool_calls" if calls else "stop",
                ),
            ),
        ),
    )


def group(session="session_studio"):
    return StudioSyncRequest(
        name="Design",
        coordinator_id="member_sage",
        members=[
            StudioMemberInput(
                id="member_sage", agent_id="sage", name="Sage", session_id=session
            )
        ],
        messages=[
            StudioHistoryInput(
                id="studio_message_first",
                turn_id="studio_message_first",
                sender="user",
                kind="user",
                text="Check earlier design decisions",
            )
        ],
    )


def test_store_scopes_search_paging_and_immutable_membership(tmp_path):
    store = StudioStore(tmp_path / "studios.db")
    data = group()
    data.messages.extend(
        StudioHistoryInput(
            id=f"studio_message_{i}",
            turn_id=f"studio_message_{i}",
            sender="user",
            kind="user",
            text=f"decision {i}",
        )
        for i in range(8)
    )
    store.sync("group", "owner", data)
    assert len(store.context_history("group", "owner")["messages"]) == 9
    assert store.context_history("group", "owner")["history_complete"]
    store.sync("group", "owner", data)
    page = store.read("group", "owner", limit=3)
    assert [m["text"] for m in page["messages"]] == [
        "decision 5",
        "decision 6",
        "decision 7",
    ]
    next_page = store.read(
        "group", "owner", limit=3, before_sequence=page["next_before_sequence"]
    )
    assert [m["text"] for m in next_page["messages"]] == [
        "decision 2",
        "decision 3",
        "decision 4",
    ]
    assert (
        store.read("group", "owner", query="decision 7")["messages"][0]["text"]
        == "decision 7"
    )
    with pytest.raises(SageV2Error):
        store.read("group", "intruder")
    with pytest.raises(SageV2Error):
        store.sync("other", "owner", group())
    with pytest.raises(ValueError):
        store.sync("group", "owner", group("replacement_session"))
    assert (
        len(StudioStore(tmp_path / "studios.db").read("group", "owner")["messages"])
        == 9
    )


def test_group_owner_changes_preserve_one_public_history(tmp_path):
    store = StudioStore(tmp_path / "studios.db")
    data = group()
    data.members.append(
        StudioMemberInput(
            id="member_designer",
            agent_id="designer",
            name="Designer",
            session_id="session_designer",
        )
    )
    store.sync("group", "owner", data)
    previous = store.read("group", "owner")
    data.coordinator_id = "member_designer"
    store.sync("group", "owner", data)
    reopened = StudioStore(tmp_path / "studios.db")
    assert reopened.group("group", "owner")["coordinator_id"] == "member_designer"
    assert reopened.read("group", "owner") == previous
    data.coordinator_id = "missing"
    with pytest.raises(ValueError):
        store.sync("group", "owner", data)
    assert reopened.group("group", "owner")["coordinator_id"] == "member_designer"


@pytest.mark.asyncio
async def test_targeted_message_keeps_parallel_addresses_and_validates_references(
    tmp_path,
):
    from types import SimpleNamespace

    service = DesktopStudioMixin()
    service.studio_store = StudioStore(tmp_path / "studios.db")
    data = group()
    data.members.append(
        StudioMemberInput(
            id="designer",
            agent_id="designer",
            name="Designer",
            session_id="session_designer",
        )
    )
    data.members.append(
        StudioMemberInput(
            id="observer",
            agent_id="observer",
            name="Observer",
            session_id="session_observer",
        )
    )
    original = "@Sage review code; @Designer review layout"
    reference = {
        "type": "reference",
        "name": "earlier answer",
        "path": "conversation://reply",
        "quote": "keep the existing layout",
    }
    data.messages = [
        StudioHistoryInput(
            id="studio_message_parallel",
            turn_id="studio_message_parallel",
            sender="user",
            kind="user",
            text=original,
            content=[reference],
            recipient_member_ids=["member_sage", "designer"],
        )
    ]
    service.studio_store.sync("group", "owner", data)
    for member_id, agent_id, session_id in [
        ("member_sage", "sage", "session_studio"),
        ("designer", "designer", "session_designer"),
    ]:
        request = DesktopRunRequest(
            agent_id=agent_id,
            session_id=session_id,
            studio_id="group",
            studio_member_id=member_id,
            studio_message_id="studio_message_parallel",
            invocation_mode="plan",
            messages=[RunMessage(role="user", text=original, content=[reference])],
        )
        binding = service.studio_request_binding(request, "owner")
        command = SimpleNamespace(config=SimpleNamespace(metadata={"studio": binding}))
        segments = await StudioContextProvider(
            service.studio_store, "owner", binding
        ).segments(command)
        assert f"You are {member_id}" in segments[0].content
        assert "execute in parallel" in segments[0].content
        assert (
            "member_sage" in segments[0].content and "designer" in segments[0].content
        )
        assert "keep the existing layout" in segments[1].content
        request.messages[0].content[0].quote = "forged reference"
        with pytest.raises(ValueError, match="references must match"):
            service.studio_request_binding(request, "owner")
    with pytest.raises(SageV2Error):
        service.studio_request_binding(
            DesktopRunRequest(
                agent_id="observer",
                session_id="session_observer",
                studio_id="group",
                studio_member_id="observer",
                studio_message_id="studio_message_parallel",
                messages=[RunMessage(role="user", text=original, content=[reference])],
            ),
            "owner",
        )


def test_studio_request_requires_complete_identity():
    with pytest.raises(ValidationError):
        DesktopRunRequest(agent_id="sage", messages=[], studio_id="group")


@pytest.mark.asyncio
async def test_studio_tools_are_per_run_and_recovered_without_global_configuration(
    tmp_path: Path,
):
    service = DesktopV2Service(tmp_path)
    resources = []
    try:
        await service.list_agents("owner")
        await service.patch_model_provider(
            "model_main", ModelProviderPatch(api_keys=["test-key"]), "owner"
        )
        await service.patch_agent_settings(
            "sage", AgentSettingsPatch(available_tools=["file_read"]), "owner"
        )
        agent = await service._agent("sage", "owner")
        provider = await service._provider(agent, "owner")
        workspace = await service.workspace_root(None, "sage")
        await service.sync_studio("group", group(), "owner")
        await service._stop_studio_delivery_worker()
        resolved = CompositionResolver().resolve(
            service._manifest(agent, provider, ("file_read",), ())
        )
        request = DesktopRunRequest(
            agent_id="sage",
            session_id="session_studio",
            studio_id="group",
            studio_member_id="member_sage",
            studio_message_id="studio_message_first",
            messages=[RunMessage(role="user", text="Check earlier design decisions")],
        )
        command = service._command(
            request, resolved, agent=agent, provider=provider, workspace=workspace
        )
        assert STUDIO_TOOLS <= set(command.config.enabled_tools)
        handle = await service.runtime.start_run(command, service._context("owner"))
        await service.sync_studio("group", group(), "owner")
        for _ in range(2):
            _, loop, sandbox = await service._build_loop(
                agent=agent,
                provider=provider,
                workspace=workspace,
                preferred_skills=(),
                approval_mode="high_risk",
                session_id=handle.session_id,
                run_id=handle.run_id,
            )
            resources.append(sandbox)
            names = {
                t.name for t in await loop.tool_catalog.list_tools(run_id=handle.run_id)
            }
            assert STUDIO_TOOLS <= names
            assert any(
                isinstance(p, StudioContextProvider)
                for p in loop.context_assembler.providers
            )
        regular = service._command(
            DesktopRunRequest(
                agent_id="sage",
                session_id="session_plain",
                messages=[RunMessage(role="user", text="ordinary")],
            ),
            resolved,
            agent=agent,
            provider=provider,
            workspace=workspace,
        )
        assert not STUDIO_TOOLS.intersection(regular.config.enabled_tools)
        regular_handle = await service.runtime.start_run(
            regular, service._context("owner")
        )
        _, regular_loop, sandbox = await service._build_loop(
            agent=agent,
            provider=provider,
            workspace=workspace,
            preferred_skills=(),
            approval_mode="high_risk",
            session_id=regular_handle.session_id,
            run_id=regular_handle.run_id,
        )
        resources.append(sandbox)
        assert not STUDIO_TOOLS.intersection(
            t.name
            for t in await regular_loop.tool_catalog.list_tools(
                run_id=regular_handle.run_id
            )
        )
        for name in STUDIO_TOOLS:
            with pytest.raises(SageV2Error):
                await regular_loop.tool_catalog.get_tool(
                    name, run_id=regular_handle.run_id
                )
        assert not STUDIO_TOOLS.intersection(
            (await service._agent("sage", "owner")).config["availableTools"]
        )
        # Being in the old Studio Session cannot silently retain tools outside Studio mode.
        with pytest.raises(SageV2Error):
            service._command(
                DesktopRunRequest(
                    agent_id="sage", session_id="session_studio", messages=[]
                ),
                resolved,
                agent=agent,
            )
        with pytest.raises(SageV2Error):
            service.studio_request_binding(
                request.model_copy(update={"session_id": "session_plain"}), "owner"
            )
        with pytest.raises(SageV2Error):
            service.studio_request_binding(request, "intruder")

        binding = command.config.metadata["studio"]
        tool_provider = service.studio_tool_provider(handle.run_id, "owner", binding)
        call = ToolCall(
            tool_call_id="call_publish",
            tool_name="studio_send_message",
            arguments={
                "text": "Earlier decision verified",
                "recipient_member_ids": ["member_sage"],
            },
            operation_id="op_publish",
            idempotency_key="key_publish",
            owner_run_id=handle.run_id,
        )
        result = await tool_provider.execute(call, service._context("owner"))
        assert result.content[0].value["kind"] == "note"
        recovered = service.studio_tool_provider(handle.run_id, "owner", binding)
        replayed = await recovered.execute(call, service._context("owner"))
        assert replayed.content == result.content
        with pytest.raises(SageV2Error):
            await tool_provider.execute(call, service._context("intruder"))
        with pytest.raises(SageV2Error):
            await tool_provider.execute(
                call.model_copy(update={"owner_run_id": regular_handle.run_id}),
                service._context("owner"),
            )
        with pytest.raises(SageV2Error):
            await recovered.execute(
                call.model_copy(
                    update={
                        "tool_call_id": "bad",
                        "idempotency_key": "bad",
                        "arguments": {
                            "text": "bad",
                            "recipient_member_ids": ["outsider"],
                        },
                    }
                ),
                service._context("owner"),
            )
        read_call = call.model_copy(
            update={
                "tool_call_id": "read",
                "tool_name": "studio_read_messages",
                "operation_id": "read",
                "idempotency_key": "read",
                "arguments": {"query": "verified"},
            }
        )
        read = await recovered.execute(read_call, service._context("owner"))
        assert [m["text"] for m in read.content[0].value["messages"]] == [
            "Earlier decision verified"
        ]
        assert len(service.studio_store.read("group", "owner")["messages"]) == 2

        def assert_studio_payload(payload):
            assert STUDIO_TOOLS <= {t.name for t in payload.tools}
            assert "Check earlier design decisions" in str(payload.messages)

        loop.tool_selection_policy = DirectToolSelectionPolicy()
        loop.step_request_builder.tool_selection_policy = loop.tool_selection_policy
        loop.continuation_policy = CompositeContinuationPolicy()
        loop.model = ScriptedModelProvider(
            (
                scripted_step(
                    calls=(
                        ModelToolCall(
                            tool_call_id="wire_read",
                            name="studio_read_messages",
                            arguments={"query": "earlier"},
                        ),
                        ModelToolCall(
                            tool_call_id="wire_send",
                            name="studio_send_message",
                            arguments={
                                "text": "Published through the real tool executor"
                            },
                        ),
                    ),
                    assertion=assert_studio_payload,
                ),
                scripted_step(text="Finished"),
            )
        )
        async with execution_lease(service, handle.run_id):
            await loop.execute(handle.run_id, service._context("owner"))
        # Recover by public turn identity, without starting another Run.
        found = await service.find_studio_run(
            "group", "member_sage", "studio_message_first", "owner"
        )
        assert found["run_id"] == handle.run_id
        with pytest.raises(SageV2Error):
            await service.find_studio_run(
                "group", "member_sage", "studio_message_first", "outsider"
            )
        # Backfill from canonical Run events even with no Desktop client connected.
        public = await service.read_studio("group", "owner")
        assert sum(m["text"] == "Finished" for m in public["messages"]) == 1
        await service.publish_studio_run_result(handle.run_id)
        public = await service.read_studio("group", "owner")
        assert sum(m["text"] == "Finished" for m in public["messages"]) == 1
        events = await service.session_store.read_events(handle.run_id)
        assert STUDIO_TOOLS <= {
            e.data.tool_name for e in events if e.type == "tool.call.succeeded"
        }
        assert any(
            m["text"] == "Published through the real tool executor"
            for m in service.studio_store.read("group", "owner")["messages"]
        )

        def assert_plain_payload(payload):
            assert not STUDIO_TOOLS.intersection(t.name for t in payload.tools)

        regular_loop.tool_selection_policy = DirectToolSelectionPolicy()
        regular_loop.step_request_builder.tool_selection_policy = (
            regular_loop.tool_selection_policy
        )
        regular_loop.continuation_policy = CompositeContinuationPolicy()
        regular_loop.model = ScriptedModelProvider(
            (scripted_step(text="Ordinary reply", assertion=assert_plain_payload),)
        )
        async with execution_lease(service, regular_handle.run_id):
            await regular_loop.execute(regular_handle.run_id, service._context("owner"))

    finally:
        for resource in resources:
            await resource.close()
        await service.close()

    reopened = DesktopV2Service(tmp_path)
    try:
        await reopened.start()
        await reopened._stop_studio_delivery_worker()
        restored_agent = await reopened._agent("sage", "owner")
        restored_binding = await reopened.studio_run_binding(
            handle.run_id, restored_agent, handle.session_id
        )
        replay_provider = reopened.studio_tool_provider(
            handle.run_id, "owner", restored_binding
        )
        assert (
            await replay_provider.execute(call, reopened._context("owner"))
        ).content == result.content
    finally:
        await reopened.close()


def test_host_context_retains_pins_and_exposes_history_omissions(tmp_path):
    store = StudioStore(tmp_path / "studios.db")
    data = group()
    data.messages.extend(
        StudioHistoryInput(
            id=f"studio_message_{i}",
            turn_id=f"studio_message_{i}",
            sender="user",
            kind="user",
            text=f"decision {i} " + "context " * 200,
        )
        for i in range(50)
    )
    data.pinned_turn_ids = ["studio_message_3"]
    store.sync("group", "owner", data)
    history = store.context_history("group", "owner")
    ids = {m["id"] for m in history["messages"]}
    assert {"studio_message_first", "studio_message_3", "studio_message_49"} <= ids
    assert history["omitted_messages"] > 0
    assert not history["history_complete"]


def test_studio_http_sync_and_history_are_authenticated(tmp_path):
    from fastapi.testclient import TestClient
    from app.desktop_v2.backend.app import create_app

    service = DesktopV2Service(tmp_path)
    app = create_app(service=service, auth_token="studio-test-token")
    headers = {"Authorization": "Bearer studio-test-token"}
    with TestClient(app) as client:
        assert client.get("/api/v2/studios/group/messages").status_code == 401
        assert client.get("/api/v2/agents", headers=headers).status_code == 200
        response = client.put(
            "/api/v2/studios/group", json=group().model_dump(), headers=headers
        )
        assert response.status_code == 200, response.text
        history = client.get("/api/v2/studios/group/messages", headers=headers)
        assert history.status_code == 200
        assert (
            history.json()["data"]["messages"][0]["text"]
            == "Check earlier design decisions"
        )
        assert (
            client.get("/api/v2/studios/missing/messages", headers=headers).status_code
            == 403
        )


def test_public_messages_share_mentions_and_final_answer_deduplication(tmp_path):
    from app.desktop_v2.backend.studio import studio_mentions

    members = [
        {"id": "designer", "name": "设计师"},
        {"id": "engineer", "name": "工程师"},
    ]
    text = "@设计师 看配色，@工程师 查性能，@用户 请确认"
    mentions = studio_mentions(text, members)
    assert [m["participant_id"] for m in mentions] == ["designer", "engineer", "user"]
    assert [text[m["start"] : m["end"]] for m in mentions] == [
        "@设计师",
        "@工程师",
        "@用户",
    ]
    assert studio_mentions("email@设计师 @设计师额外", members) == []
    assert (
        studio_mentions("@设计师", [*members, {"id": "other", "name": "设计师"}]) == []
    )
    store = StudioStore(tmp_path / "studio.db")
    store.sync("group", "owner", group())
    binding = {
        "studio_id": "group",
        "member_id": "member_sage",
        "turn_id": "studio_message_first",
    }
    message = store.send(
        "group",
        "owner",
        message_id="tool:final",
        sender="member_sage",
        turn_id="studio_message_first",
        text="@用户 已完成",
        recipients=[],
        reply_to=None,
        run_id="run",
    )
    assert message["mentions"][0]["participant_id"] == "user"
    assert message["recipient_member_ids"] == ["user"]
    store.publish_result(binding, "owner", "run", "final_item", "@用户 已完成")
    assert len(store.read("group", "owner")["messages"]) == 2
    assert store.result_published("run")


@pytest.mark.asyncio
async def test_studio_send_database_write_does_not_block_event_loop(tmp_path):
    import asyncio
    import threading
    from types import SimpleNamespace
    from app.desktop_v2.backend.studio import StudioTools

    store = StudioStore(tmp_path / "studio.db")
    store.sync("group", "owner", group())
    binding = {
        "studio_id": "group",
        "member_id": "member_sage",
        "turn_id": "studio_message_first",
    }

    async def command_reader(_):
        return SimpleNamespace(
            agent_id="sage",
            session_id="session_studio",
            config=SimpleNamespace(
                metadata={"studio": binding}, enabled_tools=["studio_send_message"]
            ),
        )

    tools = StudioTools(
        store, command_reader, run_id="run", owner="owner", binding=binding
    )
    release = threading.Event()
    entered = threading.Event()
    original = store.send

    def slow_send(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    store.send = slow_send
    invocation = SimpleNamespace(
        call=SimpleNamespace(
            owner_run_id="run",
            owner_agent_id="sage",
            owner_session_id="session_studio",
            tool_name="studio_send_message",
            tool_call_id="call",
        ),
        request_context=SimpleNamespace(actor=SimpleNamespace(principal_id="owner")),
    )
    task = asyncio.create_task(tools.send("public", invocation))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        assert not task.done()  # Event loop remains responsive during the write.
    finally:
        release.set()
    assert (await task)["text"] == "public"


@pytest.mark.asyncio
async def test_mentions_queue_wakeups_without_waiting_or_requiring_reply(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from app.desktop_v2.backend.studio_delivery import StudioDeliveryMixin
    from sagents.v2.contracts.run_state import RunState

    store = StudioStore(tmp_path / "studio.db")
    request = group()
    request.members.append(
        StudioMemberInput(
            id="designer", agent_id="design", name="设计师", session_id="design_session"
        )
    )
    store.sync("group", "owner", request)

    def send(message_id, text, turn_id="studio_message_first"):
        return store.send(
            "group",
            "owner",
            message_id=message_id,
            sender="member_sage",
            turn_id=turn_id,
            text=text,
            recipients=[],
            reply_to=None,
            run_id="source_run",
        )

    send("tool:one", "@设计师 看配色，@Sage 查需求，@用户 请确认")
    send("tool:one", "@设计师 看配色，@Sage 查需求，@用户 请确认")
    send("tool:public", "我公开补充一下，不需要回复")
    assert len(store.pending_deliveries()) == 2  # No duplicate and no user Run.
    release = asyncio.Event()

    class Host(StudioDeliveryMixin):
        def __init__(self):
            self.studio_store = store
            self._studio_delivery_tasks = {}
            self.started = []
            self.busy = True
            self.logger = SimpleNamespace(exception=lambda *a: None)
            self.session_access = SimpleNamespace(list_session_runs=self.runs)

        def _context(self, owner):
            return owner

        async def runs(self, session, context):
            return (
                [SimpleNamespace(state=RunState.RUNNING)]
                if session == "design_session" and self.busy
                else []
            )

        async def find_studio_run(self, *args):
            return None

        async def run_events(self, request, owner):
            self.started.append(request)
            yield __import__("json").dumps(
                {
                    "kind": "stream.opened",
                    "handle": {"run_id": "run_" + request.studio_member_id},
                }
            )
            await release.wait()

    host = Host()
    try:
        await host.dispatch_studio_deliveries()
        await asyncio.sleep(0.05)
        assert [r.studio_member_id for r in host.started] == ["member_sage"]
        assert (
            host.started[0].messages[0].text
            == "@设计师 看配色，@Sage 查需求，@用户 请确认"
        )
        assert not next(iter(host._studio_delivery_tasks.values())).done()
        assert len(store.pending_deliveries()) == 1
        host.busy = False
        await host.dispatch_studio_deliveries()
        await asyncio.sleep(0.05)
        assert {r.studio_member_id for r in host.started} == {"member_sage", "designer"}
        assert store.pending_deliveries() == []
        # A mentioned Agent can complete without publishing any public response.
        binding = {"studio_id": "group", "member_id": "designer", "turn_id": "tool:one"}
        before = len(store.read("group", "owner")["messages"])
        store.publish_result(
            binding, "owner", "run_designer", "internal", "No reply needed"
        )
        assert len(store.read("group", "owner")["messages"]) == before
        # A public response with no @ does not bounce back to its sender.
        send("tool:reply", "颜色已检查", turn_id="tool:one")
        assert store.pending_deliveries() == []
        assert (
            store.read("group", "owner", message_id="tool:reply")["messages"][0][
                "turn_id"
            ]
            == "studio_message_first"
        )
    finally:
        release.set()
        await host._stop_studio_delivery_worker()


def test_mention_queue_is_durable_and_bounds_cycles(tmp_path):
    path = tmp_path / "studio.db"
    store = StudioStore(path)
    store.sync("group", "owner", group())
    parent = "studio_message_first"
    for index in range(8):
        message_id = f"tool:hop{index}"
        store.send(
            "group",
            "owner",
            message_id=message_id,
            sender="member_sage",
            turn_id=parent,
            text="@Sage 继续",
            recipients=[],
            reply_to=None,
            run_id=f"run{index}",
        )
        parent = message_id
    with pytest.raises(ValueError, match="8-hop"):
        store.send(
            "group",
            "owner",
            message_id="tool:overflow",
            sender="member_sage",
            turn_id=parent,
            text="@Sage 继续",
            recipients=[],
            reply_to=None,
            run_id="run8",
        )
    restored = StudioStore(path)
    assert [r["message_id"] for r in restored.pending_deliveries()] == ["tool:hop0"]
    restored.delivery_started("tool:hop0", "member_sage", "accepted_run")
    assert [r["message_id"] for r in StudioStore(path).pending_deliveries()] == [
        "tool:hop1"
    ]


@pytest.mark.asyncio
async def test_mention_delivery_executes_real_v2_run_and_reconciles_lost_receipt(
    tmp_path, monkeypatch
):
    import asyncio

    service = DesktopV2Service(tmp_path)
    try:
        await service.list_agents("owner")
        await service.patch_model_provider(
            "model_main", ModelProviderPatch(api_keys=["test-key"]), "owner"
        )
        await service.patch_agent_settings(
            "sage", AgentSettingsPatch(available_tools=[]), "owner"
        )
        await service.sync_studio("group", group(), "owner")
        await service._stop_studio_delivery_worker()
        service._studio_delivery_tasks = {}
        original = service._build_loop
        requests = []

        async def build(**kwargs):
            resolved, loop, resources = await original(**kwargs)
            loop.continuation_policy = CompositeContinuationPolicy()
            loop.model = ScriptedModelProvider(
                (
                    scripted_step(
                        text="Internal completion, no reply needed",
                        assertion=requests.append,
                    ),
                )
            )
            return resolved, loop, resources

        monkeypatch.setattr(service, "_build_loop", build)
        service.studio_store.send(
            "group",
            "owner",
            message_id="tool:wake",
            sender="member_sage",
            turn_id="studio_message_first",
            text="@Sage 请处理此消息",
            recipients=[],
            reply_to=None,
            run_id="source",
        )
        await service.dispatch_studio_deliveries()
        await asyncio.wait_for(
            asyncio.gather(*service._studio_delivery_tasks.values()), timeout=15
        )
        found = await service.find_studio_run(
            "group", "member_sage", "tool:wake", "owner"
        )
        assert found["state"] == "completed"
        assert len(requests) == 1
        assert "请处理此消息" in str(requests[0].messages)
        assert "user" in str(requests[0].messages)
        # Simulate a receipt write lost after the canonical Run already committed.
        with service.studio_store.connection() as db:
            db.execute("UPDATE studio_deliveries SET run_id=NULL")
        await service.dispatch_studio_deliveries()
        assert service.studio_store.pending_deliveries() == []
        assert len(requests) == 1
        public = await service.read_studio("group", "owner")
        assert len(public["member_runs"]) == 1
        assert not any("Internal completion" in m["text"] for m in public["messages"])
    finally:
        await service.close()
