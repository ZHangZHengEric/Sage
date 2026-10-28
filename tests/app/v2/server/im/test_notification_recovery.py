"""Full-host restarts retain model drafts, pending messages and uncertain sends."""

import asyncio

import pytest

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.im.feishu import FeishuChannel
from app.v2.server.im.tools import IMNotificationTools
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep
from sagents.v2.tool import DecoratedToolProvider
from sagents.v2.tool.contracts import ReconcileState, ToolCall
from tests.app.v2.server.conftest import (
    FixtureServerHost,
    CompletingJudgeModel,
    make_settings,
    scripted_hello,
)
from tests.app.v2.server.im.test_feishu import config
from tests.app.v2.server.im.test_gateway import pair
from tests.app.v2.server.im.test_notifications import notification_command

NOTICE = "报告已整理完成，可打开 Sage 查看详情。"


def model():
    return ScriptedModelProvider(
        tuple(
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response),
                )
            )
            for response in (
                ModelResponse(
                    response_id="notify-call",
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id="notify",
                            name="im_notify",
                            arguments={"content": NOTICE},
                        ),
                    ),
                    finish_reason="tool_calls",
                ),
                ModelResponse(
                    response_id="final",
                    text="Detailed web result",
                    finish_reason="stop",
                ),
            )
        )
    )


@pytest.mark.parametrize(
    "crash_at", ["before_projection", "after_projection", "during_send"]
)
async def test_model_notification_survives_host_restart_without_rerunning_or_duplicate(
    tmp_path, feishu_creation_probe, monkeypatch, crash_at
):
    sent = []

    async def send(self, chat, text, uid):
        sent.append((text, uid))
        return "receipt-" + uid

    monkeypatch.setattr(FeishuChannel, "send", send)

    def make(provider):
        return FixtureServerHost(
            make_settings(
                tmp_path, public_base_url="https://sage.example", log_level="warning"
            ),
            database=Database(
                DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db")
            ),
            model_provider=CompletingJudgeModel(provider),
        )

    first = make(model())
    await first.start()
    first.im.pause()
    try:
        user = await first.identity.register("restart-notice-owner", "secret1")
        agent = (await first.catalog.get(user.user_id)).agents[0]
        conn = await first.im.create(
            user.user_id, agent.id, "Recovery", config().model_dump()
        )
        await pair(first, conn, user)
        await first.im.tick()  # Deliver the pairing acknowledgement first.
        command = await notification_command(first, conn, user)
        context = first.contexts.for_user(user.user_id)
        run_id = await first.conversations.runs.start_detached_run(
            "native",
            command,
            context,
            user_id=user.user_id,
            session_id=command.session_id,
            label="notification-recovery",
        )
        for _ in range(150):
            run = await first.conversations.session_access.get_run(run_id, context)
            if run.state.value == "completed":
                break
            await asyncio.sleep(0.01)
        assert run.state.value == "completed"
        record = await first.im.notifications.store.find(command, user.user_id)
        assert record.text == NOTICE
        if crash_at != "before_projection":
            await first.im.notifications.observe(command, user.user_id, first.im.worker)
        if crash_at == "during_send":
            sending = await first.im.store.next_delivery(conn.id, first.im.worker)
            assert sending.state == "sending" and sending.text == NOTICE
        assert not any(text == NOTICE for text, _ in sent)
    finally:
        await first.close()

    restarted = make(scripted_hello())
    await restarted.start()
    restarted.im.pause()
    try:
        context = restarted.contexts.for_user(user.user_id)
        stored = await restarted.conversations.session_access.get_start_command(
            run_id, context
        )
        # Simulate a lost tool-result acknowledgement: a fresh provider proves
        # the committed effect from SQL, without issuing another notification.
        provider = DecoratedToolProvider(
            IMNotificationTools(restarted.im.notifications, stored, run_id)
        )
        call = ToolCall(
            tool_call_id="notify",
            tool_name="im_notify",
            arguments={"content": NOTICE},
            operation_id="recovered-operation",
            idempotency_key="recovered-key",
            owner_run_id=run_id,
            owner_session_id=stored.session_id,
        )
        reconciled = await provider.reconcile_call(call, context)
        assert reconciled.state == ReconcileState.SUCCEEDED
        if crash_at == "during_send":
            await restarted.im.tick()
            uncertain = next(
                row
                for row in await restarted.im.store.deliveries(conn.id)
                if row.text == NOTICE
            )
            assert uncertain.state == "unknown"
            assert not any(text == NOTICE for text, _ in sent)
            await restarted.im.retry_delivery(
                uncertain.id,
                user.user_id,
                revision=uncertain.revision,
                allow_duplicate=True,
            )
        for _ in range(100):
            await restarted.im.tick()
            if any(text == NOTICE for text, _ in sent):
                break
            await asyncio.sleep(0.01)
        assert sum(text == NOTICE for text, _ in sent) == 1
        assert (
            len(
                await restarted.conversations.session_access.list_session_runs(
                    command.session_id, context
                )
            )
            == 1
        )
    finally:
        await restarted.close()

    third = make(scripted_hello())
    await third.start()
    third.im.pause()
    try:
        await third.im.tick()
        assert sum(text == NOTICE for text, _ in sent) == 1
    finally:
        await third.close()
