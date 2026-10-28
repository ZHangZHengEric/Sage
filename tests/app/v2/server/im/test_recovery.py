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
def persistent(tmp_path, feishu_creation_probe):
    def make():
        return FixtureServerHost(
            make_settings(
                tmp_path,
                public_base_url="https://sage.example",
                log_level="warning",
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


@pytest.mark.parametrize("damage", ["missing", "corrupt", "wrong_key"])
async def test_key_damage_disables_connection_without_blocking_startup(
    persistent, damage
):
    from cryptography.fernet import Fernet
    from sagents.v2.contracts.errors import SageV2Error

    host = persistent()
    await host.start()
    host.im.pause()
    user = await host.identity.register("key-owner", "secret1")
    agent = (await host.catalog.get(user.user_id)).agents[0]
    conn = await host.im.create(
        user.user_id, agent.id, "Key recovery", config().model_dump()
    )
    key_file = host.paths.data_root / "secrets" / "im-credentials.key"
    original = key_file.read_bytes()
    await host.close()
    if damage == "missing":
        key_file.unlink()
    else:
        key_file.write_bytes(
            b"broken" if damage == "corrupt" else Fernet.generate_key()
        )
    restarted = persistent()
    await restarted.start()
    restarted.im.pause()
    try:
        row = await restarted.im.store.get(conn.id, user.user_id)
        assert not row.enabled
        assert row.auth_epoch == conn.auth_epoch + 1
        assert restarted.im.credentials_error(conn.id)
        assert row.config == conn.config
        with pytest.raises(SageV2Error) as unavailable:
            await restarted.im.set_enabled(conn.id, user.user_id, row.revision, True)
        assert unavailable.value.info.code == "server.im.credentials_unavailable"
        if damage == "missing":
            assert not key_file.exists()
        key_file.write_bytes(original)
        key_file.chmod(0o600)
        await restarted.im.check_credentials(row)
        assert not restarted.im.credentials_error(conn.id)
        enabled = await restarted.im.set_enabled(
            conn.id, user.user_id, row.revision, True
        )
        assert enabled.enabled
        assert await restarted.im.channel(enabled)
    finally:
        await restarted.close()


async def test_one_corrupt_connection_does_not_disable_healthy_connections(persistent):
    host = persistent()
    await host.start()
    host.im.pause()
    user = await host.identity.register("isolated-key-owner", "secret1")
    agent = (await host.catalog.get(user.user_id)).agents[0]
    healthy = await host.im.create(
        user.user_id, agent.id, "Healthy", config().model_dump()
    )
    broken_config = {**config().model_dump(), "app_id": "cli_broken"}
    broken = await host.im.create(user.user_id, agent.id, "Broken", broken_config)
    async with host.im.store.locked(broken.id) as (_, row):
        row.config = {**row.config, "credentials_ciphertext": "corrupt"}
    await host.close()
    restarted = persistent()
    await restarted.start()
    restarted.im.pause()
    try:
        assert (await restarted.im.store.get(healthy.id)).enabled
        assert not restarted.im.credentials_error(healthy.id)
        assert await restarted.im.channel(healthy)
        assert not (await restarted.im.store.get(broken.id)).enabled
        assert restarted.im.credentials_error(broken.id)
    finally:
        await restarted.close()
