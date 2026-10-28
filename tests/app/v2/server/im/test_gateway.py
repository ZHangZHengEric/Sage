import asyncio

import pytest

from tests.app.v2.server.conftest import make_test_service
from tests.app.v2.server.im.test_feishu import (
    config,
    event,
    signed,
)


@pytest.fixture
async def im_host(tmp_path, feishu_creation_probe):
    host = make_test_service(
        tmp_path,
        public_base_url="https://sage.example",
        log_level="warning",
    )
    await host.start()
    host.im.pause()  # Tests advance durable workers explicitly, without timing races.
    user = await host.identity.register("im-owner", "secret1")
    if isinstance(user, dict):
        user = await host.users.get_by_username("im-owner")
    catalog = await host.catalog.get(user.user_id)
    conn = await host.im.create(
        user.user_id, catalog.agents[0].id, "Private bot", config().model_dump()
    )
    yield host, conn, user
    await host.close()


async def receive(host, conn, text="hello", n=1, sender="ou_owner"):
    payload = event(text)
    payload["header"]["event_id"] = f"event-{n}"
    payload["event"]["message"]["message_id"] = f"om_{n}"
    payload["event"]["sender"]["sender_id"]["open_id"] = sender
    return await host.im.receive(conn.id, *signed(payload))


async def pair(host, conn, user):
    challenge = await host.im.pairing(conn.id, user.user_id)
    await receive(host, conn, "/pair " + challenge["code"], n=999)


async def settled(host, conn, count=1):
    for _ in range(150):
        await host.im.tick()
        rows = await host.im.store.inboxes(conn.id)
        chats = [r for r in rows if r.kind == "message"]
        if len(chats) >= count and all(
            r.state in ("complete", "superseded", "failed") for r in chats
        ):
            return chats
        await asyncio.sleep(0.02)
    pytest.fail("IM run did not settle")


async def test_private_run_uses_native_session_and_duplicate_never_reruns(im_host):
    host, conn, user = im_host
    sent = []
    channel = await host.im.channel(conn)

    async def send(chat, text, delivery_id):
        sent.append((chat, text, delivery_id))
        return "receipt-" + delivery_id

    channel.send = send
    await receive(host, conn, sender="stranger")
    assert not await host.im.store.inboxes(conn.id)
    await pair(host, conn, user)
    await receive(host, conn)
    await receive(host, conn)
    rows = await settled(host, conn)
    assert len(rows) == 1 and rows[0].run_id
    result = await host.application.service("session.access").get_run_result(
        rows[0].run_id, host.contexts.for_user(user.user_id)
    )
    assert result.outcome.value == "completed"
    await host.im.tick()
    assert [x[1] for x in sent].count("hello") == 1
    assert len(await host.threads.list_for(user.user_id)) == 1


async def test_new_changes_session_and_old_queued_answer_is_suppressed(im_host):
    host, conn, user = im_host
    await pair(host, conn, user)
    await receive(host, conn, "old")
    await receive(host, conn, "/new", n=2)
    await receive(host, conn, "new", n=3)
    rows = await settled(host, conn, 2)
    assert rows[0].session_id != rows[1].session_id
    assert rows[0].state == "superseded"
    assert rows[1].state == "complete"


async def test_cancel_before_handoff_does_not_start_agent(im_host):
    host, conn, user = im_host
    await pair(host, conn, user)
    await receive(host, conn)
    await receive(host, conn, "/stop", n=2)
    rows = await settled(host, conn)
    assert not rows[0].run_id
    assert rows[0].state == "complete"


async def test_full_input_queue_still_accepts_stop(im_host):
    import time

    from sqlalchemy import insert
    from app.v2.server.im.orm import InboxRow
    from sagents.v2.contracts.errors import ErrorCategory, SageV2Error

    host, conn, user = im_host
    await pair(host, conn, user)
    await receive(host, conn)
    row = [r for r in await host.im.store.inboxes(conn.id) if r.kind == "message"][0]
    async with host.database.transaction() as db:
        await db.execute(
            insert(InboxRow),
            [
                {
                    "connection_id": conn.id,
                    "message_key": f"{n:064x}",
                    "event_key": f"{n:064x}",
                    "digest": "queued",
                    "binding_id": row.binding_id,
                    "session_id": row.session_id,
                    "generation": row.generation,
                    "auth_epoch": row.auth_epoch,
                    "sender_id": row.sender_id,
                    "chat_id": row.chat_id,
                    "kind": "message",
                    "text": "queued",
                    "created_at": time.time(),
                }
                for n in range(1, 1000)
            ],
        )
    with pytest.raises(SageV2Error) as exc:
        await receive(host, conn, "overflow", n=1001)
    assert exc.value.info.category == ErrorCategory.RATE_LIMITED
    await receive(host, conn, "/stop", n=1002)
    async with host.database.session() as db:
        assert (await db.get(InboxRow, row.id)).cancel_requested


async def test_suspended_run_sends_authenticated_sage_link_and_revocation_blocks_approval(
    im_host,
):
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.app.v2.server.conftest import CompletingJudgeModel
    from tests.app.v2.server.test_a2a_resume import _step
    from sagents.v2.contracts.errors import SageV2Error

    host, conn, user = im_host
    host.execution.fallback_model = CompletingJudgeModel(
        ScriptedModelProvider(
            (
                _step(
                    1,
                    "write",
                    "file_write",
                    {"file_path": "private.txt", "content": "yes"},
                ),
                _step(2, "written"),
            )
        )
    )
    await host.catalog.update_agent(
        user.user_id, conn.agent_id, {"name": "IM", "tools": ["file_write"]}
    )
    await pair(host, conn, user)
    await receive(host, conn)
    for _ in range(150):
        await host.im.tick()
        approvals = await host.conversations.pending_approvals(user.user_id)
        if approvals["items"]:
            break
        await asyncio.sleep(0.01)
    item = approvals["items"][0]
    # Polling a persistent suspension must enqueue only one link.
    await host.im.tick()
    await host.im.tick()
    rows = await host.im.store.deliveries(conn.id, limit=100)
    links = [r for r in rows if "?thread=" in r.text]
    assert len(links) == 1
    assert links[0].text.endswith("https://sage.example/?thread=" + item["thread_id"])
    assert not (
        host.paths.workspace_dir(user.user_id, conn.agent_id) / "private.txt"
    ).exists()
    await host.im.store.set_enabled(conn.id, user.user_id, conn.revision, False)
    with pytest.raises(SageV2Error) as exc:
        await host.conversations.decide_approval(
            item["run_id"],
            user_id=user.user_id,
            decision="approve_once",
            payload={},
            expected=item["expected"],
        )
    assert exc.value.info.code == "server.execution_grant.forbidden"


async def test_approval_via_existing_conversation_service_continues_same_run(im_host):
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.app.v2.server.conftest import CompletingJudgeModel
    from tests.app.v2.server.test_a2a_resume import _step

    host, conn, user = im_host
    host.execution.fallback_model = CompletingJudgeModel(
        ScriptedModelProvider(
            (
                _step(
                    1,
                    "write",
                    "file_write",
                    {"file_path": "approved.txt", "content": "yes"},
                ),
                _step(2, "written"),
            )
        )
    )
    await host.catalog.update_agent(
        user.user_id, conn.agent_id, {"name": "IM", "tools": ["file_write"]}
    )
    await pair(host, conn, user)
    await receive(host, conn)
    for _ in range(150):
        await host.im.tick()
        approvals = await host.conversations.pending_approvals(user.user_id)
        if approvals["items"]:
            break
        await asyncio.sleep(0.01)
    item = approvals["items"][0]
    await host.conversations.decide_approval(
        item["run_id"],
        user_id=user.user_id,
        decision="approve_once",
        payload={},
        expected=item["expected"],
    )
    rows = await settled(host, conn)
    assert rows[0].run_id == item["run_id"]
    assert (
        host.paths.workspace_dir(user.user_id, conn.agent_id) / "approved.txt"
    ).read_text() == "yes"


async def test_cancel_running_run_and_durable_cancel_window(im_host):
    host, conn, user = im_host
    await pair(host, conn, user)
    # A blocked model makes cancellation observable without a fragile sleep.
    started = asyncio.Event()
    original = host.execution.fallback_model

    class BlockingModel:
        async def capabilities(self, binding):
            return await original.capabilities(binding)

        async def stream(self, request):
            started.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover

    host.execution.fallback_model = BlockingModel()
    await receive(host, conn)
    await host.im.tick()
    await asyncio.wait_for(started.wait(), 3)
    rows = [r for r in await host.im.store.inboxes(conn.id) if r.kind == "message"]
    run_id = rows[0].run_id
    # Simulate a crash after canonical Run acceptance but before inbox linkage.
    await host.im.store.change_inbox(
        rows[0], host.im.worker, state="pending", run_id=""
    )
    await receive(host, conn, "/stop", n=2)
    rows = await settled(host, conn)
    run = await host.application.service("session.access").get_run(
        run_id, host.contexts.for_user(user.user_id)
    )
    assert run.state.value == "cancelled"
    assert rows[0].run_id == run_id


@pytest.mark.parametrize("provider_transient", [False, True])
async def test_frozen_command_survives_handoff_failure_and_agent_edits(
    im_host, monkeypatch, provider_transient
):
    from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

    host, conn, user = im_host
    await pair(host, conn, user)
    await receive(host, conn)
    original = host.conversations.runs.start_detached_run

    async def unavailable(*args, **kwargs):
        if provider_transient:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="provider_unavailable",
                    category=ErrorCategory.PROVIDER_TRANSIENT,
                    message="Try again later",
                )
            )
        raise OSError("handoff unavailable")

    monkeypatch.setattr(host.conversations.runs, "start_detached_run", unavailable)
    await host.im.tick()
    row = [r for r in await host.im.store.inboxes(conn.id) if r.kind == "message"][0]
    frozen = row.command
    assert frozen and not row.run_id
    assert row.state == "pending" and row.attempts == 1
    await host.catalog.update_agent(
        user.user_id,
        conn.agent_id,
        {"name": "Edited", "instructions": "different instructions"},
    )
    await host.im.store.change_inbox(row, host.im.worker, next_attempt=0)
    monkeypatch.setattr(host.conversations.runs, "start_detached_run", original)
    rows = await settled(host, conn)
    accepted = await host.conversations.session_access.get_start_command(
        rows[0].run_id, host.contexts.for_user(user.user_id)
    )
    assert (
        accepted.config.metadata["server_v2.composition"]
        == frozen["config"]["metadata"]["server_v2.composition"]
    )


async def test_connection_disable_is_checked_before_next_model_request(im_host):
    from app.v2.server.runtime.policy import live_execution_policy

    host, conn, user = im_host
    await pair(host, conn, user)
    await receive(host, conn)
    rows = await settled(host, conn)
    context = host.contexts.for_user(user.user_id)
    command = await host.conversations.session_access.get_start_command(
        rows[0].run_id, context
    )
    assert await host.im.authorize_run(command)
    await host.im.store.set_enabled(conn.id, user.user_id, conn.revision, False)
    assert not await host.im.authorize_run(command)
    assert (
        await live_execution_policy(
            command,
            users=host.users,
            keys=host.credentials.keys,
            catalog=host.catalog_store,
            settings=host.settings,
            user_id=user.user_id,
            ingress_authorizer=host.im.authorize_run,
        )
        is None
    )
    # The real model-provider seam checks before borrowing/calling any client.
    from app.v2.server.packages.builder import CatalogPackageModel

    async def revoked():
        assert not await host.im.authorize_run(command)
        raise PermissionError("revoked")

    provider = CatalogPackageModel(
        host.catalog_store, host.execution, user.user_id, {}, authorize=revoked
    )
    with pytest.raises(PermissionError):
        await provider.capabilities("primary")
