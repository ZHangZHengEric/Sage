"""Run notifications reuse the operational IM outbox and native Run lifecycle."""

import pytest
from sagents.v2.contracts.commands import StartRun, RunConfig, InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.errors import SageV2Error
from tests.app.v2.server.im.test_gateway import pair, receive


async def notification_command(
    host, conn, user, *, session="web-notice", request="notice-1"
):
    admitted = await host.conversations.admission.prepare(
        user_id=user.user_id,
        session_id=session,
        agent_id=conn.agent_id,
        pin_existing=True,
    )
    command = StartRun(
        session_id=session,
        agent_id=admitted.agent_id,
        input=(InputItem(role="user", content=(TextBlock(text="finish the report"),)),),
        config=RunConfig(
            metadata=admitted.metadata,
            enabled_skills=tuple(s.name for s in admitted.skills),
        ),
        resolved_spec_hash=host.application.composition_hash,
        idempotency_key=request,
    )
    return await host.im.notifications.bind(command, user.user_id, conn.id)


async def test_notify_target_requires_own_enabled_paired_connection(im_host):
    host, conn, user = im_host
    with pytest.raises(SageV2Error):
        await notification_command(host, conn, user)
    await pair(host, conn, user)
    command = await notification_command(host, conn, user)
    route = command.config.metadata["server_v2.im_notify"]
    assert route["owner_id"] == user.user_id
    assert route["connection_id"] == conn.id
    other = await host.identity.register("foreign-notice-owner", "secret1")
    with pytest.raises(SageV2Error):
        await host.im.notifications.bind(command, other.user_id, conn.id)
    current = await host.im.store.get(conn.id)
    await host.im.set_enabled(conn.id, user.user_id, current.revision, False)
    with pytest.raises(SageV2Error):
        await notification_command(host, conn, user)


async def test_notification_draft_is_durable_and_never_sent_before_run_finishes(
    im_host,
):
    host, conn, user = im_host
    await pair(host, conn, user)
    command = await notification_command(host, conn, user)
    record = await host.im.notifications.track(command, user.user_id)
    assert record.state == "prepared"
    assert await host.im.store.claim(conn.id, host.im.worker)
    await host.im.notifications.prepare(
        command, "native-run", user.user_id, "报告已整理完成。"
    )
    # The Run has not even been accepted yet: a draft must never enter sending.
    assert all(
        row.text != "报告已整理完成。"
        for row in await host.im.store.deliveries(conn.id)
    )
    duplicate = await host.im.notifications.prepare(
        command, "native-run", user.user_id, "报告已整理完成。"
    )
    assert duplicate == {"notification_id": record.id, "status": "prepared"}
    with pytest.raises(SageV2Error):
        await host.im.notifications.prepare(
            command, "native-run", user.user_id, "different final"
        )


@pytest.mark.parametrize("ingress", ["web", "im"])
@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
async def test_native_tool_prepares_model_text_and_publishes_once_after_completed(
    tmp_path, feishu_creation_probe, outcome, ingress
):
    import asyncio
    from sagents.v2.model.contracts import (
        ModelEventKind,
        ModelResponse,
        ModelStreamEvent,
        ModelToolCall,
    )
    from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep
    from tests.app.v2.server.conftest import make_test_service
    from tests.app.v2.server.im.test_feishu import config

    class GatedModel(ScriptedModelProvider):
        def __init__(self):
            def step(response):
                return ScriptedModelStep(
                    events=(
                        ModelStreamEvent(
                            kind=ModelEventKind.COMPLETED, response=response
                        ),
                    )
                )

            super().__init__(
                (
                    step(
                        ModelResponse(
                            response_id="notice-tool",
                            tool_calls=(
                                ModelToolCall(
                                    tool_call_id="notify",
                                    name="im_notify",
                                    arguments={"content": "报告已整理完成。"},
                                ),
                            ),
                            finish_reason="tool_calls",
                        )
                    ),
                    step(
                        ModelResponse(
                            response_id="web-final",
                            text="网页中的详细报告。",
                            finish_reason="stop",
                        )
                    ),
                )
            )
            self.prepared = asyncio.Event()
            self.release = asyncio.Event()

        async def stream(self, request):
            assert "im_notify" in {tool.name for tool in request.tools}
            if self.requests:
                assert "prepared" in str(request.messages)
                self.prepared.set()
                await self.release.wait()
            if self.requests and outcome == "failed":
                from sagents.v2.contracts.errors import RuntimeErrorInfo, ErrorCategory

                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="fixture.failure",
                        message="model unavailable",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                    )
                )
            async for event in super().stream(request):
                yield event

    model = GatedModel()
    host = make_test_service(
        tmp_path,
        model_provider=model,
        public_base_url="https://sage.example",
        log_level="warning",
    )
    await host.start()
    host.im.pause()
    try:
        user = await host.identity.register("model-notice-owner", "secret1")
        agent = (await host.catalog.get(user.user_id)).agents[0]
        conn = await host.im.create(
            user.user_id, agent.id, "My IM", config().model_dump()
        )
        await pair(host, conn, user)
        sent = []
        channel = await host.im.channel(conn)

        async def send(chat, text, uid):
            sent.append(text)
            return "receipt-" + uid

        channel.send = send
        if ingress == "web":
            command = await notification_command(host, conn, user)
            run_id = await host.conversations.runs.start_detached_run(
                "native",
                command,
                host.contexts.for_user(user.user_id),
                user_id=user.user_id,
                session_id=command.session_id,
                label="web-notification",
            )
        else:
            await receive(host, conn)
            await host.im.tick()
            inbox = next(
                row
                for row in await host.im.store.inboxes(conn.id)
                if row.kind == "message"
            )
            run_id = inbox.run_id
            command = await host.conversations.session_access.get_start_command(
                run_id, host.contexts.for_user(user.user_id)
            )
        await asyncio.wait_for(model.prepared.wait(), 3)
        await host.im.tick()
        assert "报告已整理完成。" not in sent
        if outcome == "cancelled":
            current = await host.conversations.session_access.get_run(
                run_id, host.contexts.for_user(user.user_id)
            )
            await host.conversations.runs.cancel_run(
                run_id,
                host.contexts.for_user(user.user_id),
                expected_revision=current.revision,
            )
        model.release.set()
        expected = (
            "报告已整理完成。"
            if outcome == "completed"
            else "任务已取消。"
            if outcome == "cancelled"
            else "任务执行失败，请在 Sage 中查看：" + host.im.link(command.session_id)
        )
        for _ in range(100):
            await host.im.tick()
            if expected in sent:
                break
            await asyncio.sleep(0.02)
        assert sent.count(expected) == 1
        assert "网页中的详细报告。" not in sent
        if outcome != "completed":
            assert "报告已整理完成。" not in sent
        await host.im.tick()
        assert sent.count(expected) == 1
        assert (
            await host.conversations.session_access.get_run(
                run_id, host.contexts.for_user(user.user_id)
            )
        ).state.value == outcome
        if ingress == "web":
            assert all(
                row.kind == "pair" for row in await host.im.store.inboxes(conn.id)
            )
    finally:
        model.release.set()
        await host.close()


async def test_acceptance_retry_after_long_delay_keeps_the_completion_notification(
    im_host,
):
    import asyncio
    import time
    from app.v2.server.im.orm import DeliveryRow

    host, conn, user = im_host
    await pair(host, conn, user)
    sent = []

    async def send(chat, text, uid):
        sent.append(text)
        return "receipt-" + uid

    (await host.im.channel(conn)).send = send
    command = await notification_command(host, conn, user)
    record = await host.im.notifications.track(command, user.user_id)
    async with host.im.store.locked(conn.id) as (db, _):
        (await db.get(DeliveryRow, record.id)).created_at = time.time() - 7200
    await host.im.tick()  # The first attempt died before native Run acceptance.
    context = host.contexts.for_user(user.user_id)
    await host.conversations.runs.start_detached_run(
        "native",
        command,
        context,
        user_id=user.user_id,
        session_id=command.session_id,
        label="delayed-acceptance",
    )
    for _ in range(100):
        await host.im.tick()
        if "hello" in sent:
            break
        await asyncio.sleep(0.02)
    assert sent.count("hello") == 1


async def test_native_notify_tool_rejects_model_supplied_targets_and_other_run_identities(
    im_host,
):
    from sagents.v2.tool import DecoratedToolProvider
    from sagents.v2.tool.contracts import ToolCall
    from app.v2.server.im.tools import IMNotificationTools

    host, conn, user = im_host
    await pair(host, conn, user)
    command = await notification_command(host, conn, user)
    provider = DecoratedToolProvider(
        IMNotificationTools(host.im.notifications, command, "root-run")
    )
    call = ToolCall(
        tool_call_id="notice",
        tool_name="im_notify",
        operation_id="op-notice",
        idempotency_key="notice-key",
        owner_run_id="root-run",
        owner_session_id=command.session_id,
        arguments={"content": "done", "connection_id": "someone-else"},
    )
    context = host.contexts.for_user(user.user_id)
    with pytest.raises(SageV2Error) as invalid:
        await provider.execute(call, context)
    assert invalid.value.info.code == "tool.arguments_invalid"
    clean = call.model_copy(
        update={"arguments": {"content": "done"}, "owner_run_id": "child-run"}
    )
    with pytest.raises(SageV2Error) as other_run:
        await provider.execute(clean, context)
    assert other_run.value.info.code == "server.im.notification_forbidden"
    assert await host.im.notifications.store.find(command, user.user_id) is None


@pytest.mark.parametrize("revoke", ["reset", "disable_enable"])
async def test_unaccepted_notification_releases_capacity_after_route_is_revoked(
    im_host, revoke
):
    host, conn, user = im_host
    await pair(host, conn, user)
    command = await notification_command(host, conn, user)
    await host.im.notifications.track(command, user.user_id)
    if revoke == "reset":
        await receive(host, conn, "/new", n=2)
    else:
        current = await host.im.store.get(conn.id)
        current = await host.im.set_enabled(
            conn.id, user.user_id, current.revision, False
        )
        await host.im.set_enabled(conn.id, user.user_id, current.revision, True)
    channel = await host.im.channel(conn)

    async def send(chat, text, uid):
        return "receipt"

    channel.send = send
    await host.im.tick()
    record = await host.im.notifications.store.find(command, user.user_id)
    assert record.state == "projected"
    assert record.text == ""
