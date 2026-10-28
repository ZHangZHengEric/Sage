import time

import pytest

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.im.service import IMService
from tests.app.v2.server.conftest import (
    FixtureServerHost,
    make_settings,
    CompletingJudgeModel,
    scripted_hello,
)
from tests.app.v2.server.im.test_feishu import config
from tests.app.v2.server.im.test_gateway import pair, receive, settled


@pytest.fixture
def persistent(tmp_path, monkeypatch):
    for name, value in [("SECRET", "secret"), ("TOKEN", "verify"), ("KEY", "key")]:
        monkeypatch.setenv("SAGE_IM_FEISHU_" + name, value)

    def make():
        return FixtureServerHost(
            make_settings(
                tmp_path, public_base_url="https://sage.example", log_level="warning"
            ),
            database=Database(
                DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db")
            ),
            model_provider=CompletingJudgeModel(scripted_hello(3)),
        )

    return make


async def test_full_host_restart_recovers_acked_input_and_pending_output(persistent):
    host = persistent()
    await host.start()
    host.im.pause()
    try:
        user = await host.identity.register("durable-owner", "secret1")
        agent = (await host.catalog.get(user.user_id)).agents[0]
        conn = await host.im.create(
            user.user_id, agent.id, "Durable", config().model_dump()
        )
        await pair(host, conn, user)
        await receive(host, conn)
    finally:
        await host.close()
    # New host, SQL repositories and SessionStore: nothing is copied in memory.
    restarted = persistent()
    await restarted.start()
    restarted.im.pause()
    try:
        captured = []
        channel = await restarted.im.channel(conn)

        async def send(chat, text, uid):
            captured.append(text)
            return "receipt-" + uid

        channel.send = send
        rows = await settled(restarted, conn)
        run_id = rows[0].run_id
        await restarted.im.tick()
        assert captured.count("hello") == 1
        await receive(
            restarted, conn
        )  # Repeat even after the original body is cleared.
        assert (
            len(
                [
                    r
                    for r in await restarted.im.store.inboxes(conn.id)
                    if r.kind == "message"
                ]
            )
            == 1
        )
        assert (
            await restarted.conversations.session_access.get_run(
                run_id, restarted.contexts.for_user(user.user_id)
            )
        ).state.value == "completed"
        # Prepare an actual unsent intent, then discard the entire process host.
        await receive(restarted, conn, "/new", n=2)
    finally:
        await restarted.close()
    third = persistent()
    await third.start()
    third.im.pause()
    try:
        sent = []
        channel = await third.im.channel(conn)

        async def send(chat, text, uid):
            sent.append(text)
            return "new-receipt"

        channel.send = send
        await third.im.tick()
        assert sent == ["已开启新会话。"]
    finally:
        await third.close()


async def test_lost_link_after_acceptance_reuses_run(persistent):
    host = persistent()
    await host.start()
    host.im.pause()
    try:
        user = await host.identity.register("accepted-owner", "secret1")
        agent = (await host.catalog.get(user.user_id)).agents[0]
        conn = await host.im.create(
            user.user_id, agent.id, "Accepted", config().model_dump()
        )
        await pair(host, conn, user)
        await receive(host, conn)
        await host.im.tick()
        row = [r for r in await host.im.store.inboxes(conn.id) if r.kind == "message"][
            0
        ]
        assert row.run_id
        run_id = row.run_id
        await host.im.store.change_inbox(
            row, host.im.worker, state="pending", run_id=""
        )
        rows = await settled(host, conn)
        assert rows[0].run_id == run_id
        assert (
            len(
                await host.conversations.session_access.list_session_runs(
                    row.session_id, host.contexts.for_user(user.user_id)
                )
            )
            == 1
        )
    finally:
        await host.close()


async def test_expired_sending_becomes_unknown_and_never_auto_resends(persistent):
    host = persistent()
    await host.start()
    host.im.pause()
    try:
        user = await host.identity.register("send-owner", "secret1")
        conn = await host.im.create(
            user.user_id,
            (await host.catalog.get(user.user_id)).agents[0].id,
            "Send",
            config().model_dump(),
        )
        await pair(host, conn, user)
        assert await host.im.store.claim(conn.id, host.im.worker)
        sending = await host.im.store.next_delivery(conn.id, host.im.worker)
        assert sending.state == "sending"
        async with host.im.store.locked(conn.id) as (_, current):
            current.lease_until = time.time() - 1
        replacement = IMService(host)
        assert await replacement.store.claim(conn.id, replacement.worker)
        assert (await replacement.store.deliveries(conn.id))[0].state == "unknown"
        assert (
            await replacement.store.next_delivery(conn.id, replacement.worker) is None
        )
        with pytest.raises(Exception):
            await replacement.retry_delivery(
                sending.id, user.user_id, revision=sending.revision + 1
            )
        await replacement.retry_delivery(
            sending.id,
            user.user_id,
            revision=sending.revision + 1,
            allow_duplicate=True,
        )
        retried = await replacement.store.next_delivery(conn.id, replacement.worker)
        assert retried.source_key == sending.source_key
        # A stale worker cannot confirm a message after losing its lease.
        with pytest.raises(Exception):
            await host.im.store.finish_delivery(
                sending, host.im.worker, "platform_accepted"
            )
    finally:
        await host.close()


async def test_suspended_run_and_approval_link_survive_full_host_restart(persistent):
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.app.v2.server.test_a2a_resume import _step
    import asyncio

    host = persistent()
    host.execution.fallback_model = CompletingJudgeModel(
        ScriptedModelProvider(
            (
                _step(
                    1,
                    "write",
                    "file_write",
                    {"file_path": "restarted.txt", "content": "approved"},
                ),
                _step(2, "written"),
            )
        )
    )
    await host.start()
    host.im.pause()
    try:
        user = await host.identity.register("suspended-owner", "secret1")
        agent = (await host.catalog.get(user.user_id)).agents[0]
        await host.catalog.update_agent(
            user.user_id, agent.id, {"name": "Suspended", "tools": ["file_write"]}
        )
        conn = await host.im.create(
            user.user_id, agent.id, "Suspended", config().model_dump()
        )
        await pair(host, conn, user)
        await receive(host, conn)
        for _ in range(150):
            await host.im.tick()
            approvals = await host.conversations.pending_approvals(user.user_id)
            if approvals["items"]:
                break
            await asyncio.sleep(0.01)
        run_id = approvals["items"][0]["run_id"]
    finally:
        await host.close()
    restarted = persistent()
    await restarted.start()
    restarted.im.pause()
    try:
        item = (await restarted.conversations.pending_approvals(user.user_id))["items"][
            0
        ]
        assert item["run_id"] == run_id
        await restarted.conversations.decide_approval(
            run_id,
            user_id=user.user_id,
            decision="approve_once",
            payload={},
            expected=item["expected"],
        )
        rows = await settled(restarted, conn)
        assert rows[0].run_id == run_id
        assert (
            restarted.paths.workspace_dir(user.user_id, agent.id) / "restarted.txt"
        ).read_text() == "approved"
    finally:
        await restarted.close()


async def test_partial_delivery_keeps_order_and_retries_only_unconfirmed_part(
    persistent,
):
    from app.v2.server.im.contracts import DeliveryError
    from app.v2.server.im.orm import DeliveryRow

    host = persistent()
    await host.start()
    host.im.pause()
    try:
        user = await host.identity.register("parts-owner", "secret1")
        conn = await host.im.create(
            user.user_id,
            (await host.catalog.get(user.user_id)).agents[0].id,
            "Parts",
            config().model_dump(),
        )
        await pair(host, conn, user)
        sent = []
        limited = [True]

        async def send(chat, text, uid):
            sent.append((text, uid))
            if text.startswith("b") and limited[0]:
                limited[0] = False
                raise DeliveryError("retry", "rate_limit", 1)
            return "receipt-" + uid

        (await host.im.channel(conn)).send = send
        await host.im.tick()  # pairing reply
        await receive(host, conn)
        row = [r for r in await host.im.store.inboxes(conn.id) if r.kind == "message"][
            0
        ]
        await host.im.store.project(
            row,
            host.im.worker,
            "final",
            "a" * 2000 + "b" * 2000 + "c" * 1000,
            final=True,
        )
        await host.im.tick()
        await host.im.tick()
        deliveries = await host.im.store.deliveries(conn.id)
        pending = [r for r in deliveries if r.state == "pending"]
        assert len(pending) == 2
        assert not any(text.startswith("c") for text, _ in sent)
        async with host.im.store.locked(conn.id) as (db, _):
            retry = await db.get(DeliveryRow, pending[0].id)
            retry.next_attempt = 0
        await host.im.tick()
        await host.im.tick()
        assert len([text for text, _ in sent if text.startswith("a")]) == 1
        assert len([text for text, _ in sent if text.startswith("c")]) == 1
        retried_ids = [uid for text, uid in sent if text.startswith("b")]
        assert len(retried_ids) == 2 and len(set(retried_ids)) == 1
        assert all(
            r.state == "platform_accepted"
            for r in await host.im.store.deliveries(conn.id)
        )
    finally:
        await host.close()
