"""Owner-bound notifications across approvals, cancellation and process restarts."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.im.contracts import DeliveryError
from app.v2.server.im.feishu import FeishuChannel
from app.v2.server.im.orm import DeliveryRow
from app.v2.server.main import create_app
from sagents.v2.testing.plugins import ScriptedModelProvider
from tests.app.v2.server.conftest import (
    CompletingJudgeModel,
    FixtureServerHost,
    make_settings,
)
from tests.app.v2.server.im.test_gateway import receive
from tests.app.v2.server.im.test_notification_http import setup_route
from tests.app.v2.server.test_a2a_resume import _step
from tests.app.v2.server.test_agui_chat import _run_input
from tests.app.v2.server.test_file_downloads import identity

NOTICE = "审批后的报告已完成。"


def make_host(path, steps):
    return FixtureServerHost(
        make_settings(
            path, public_base_url="https://sage.example", log_level="warning"
        ),
        database=Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{path}/host.db")),
        model_provider=CompletingJudgeModel(ScriptedModelProvider(tuple(steps))),
    )


async def wait_for_approval(host, owner):
    async with asyncio.timeout(5):
        while True:
            await host.im.tick()
            items = (await host.conversations.pending_approvals(owner))["items"]
            if items:
                return items[0]
            await asyncio.sleep(0.01)


async def drain(host, run_id, owner):
    async with asyncio.timeout(5):
        while True:
            await host.im.tick()
            run = await host.conversations.session_access.get_run(
                run_id, host.contexts.for_user(owner)
            )
            if run.state.value in {"completed", "cancelled", "failed"}:
                command = await host.conversations.session_access.get_start_command(
                    run_id, host.contexts.for_user(owner)
                )
                await host.im.notifications.observe(command, owner, host.im.worker)
                for _ in range(5):
                    await host.im.tick()
                return run
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("ingress", ["web", "im", "scheduled"])
@pytest.mark.parametrize("link_state", ["failed", "unknown"])
@pytest.mark.parametrize(
    "decision",
    [
        "approve_once",
        "accepted_approval",
        "cancel",
        "approval_cancel",
        "approval_cancel_pause",
    ],
)
def test_resolved_approval_does_not_block_final_after_restart(
    tmp_path, feishu_creation_probe, monkeypatch, ingress, link_state, decision
):
    sent = []

    async def send(self, chat, text, uid):
        if "?thread=" in text:
            raise DeliveryError(link_state, "fixture_link_failure")
        sent.append((chat, text, uid))
        return "receipt-" + uid

    monkeypatch.setattr(FeishuChannel, "send", send)
    pause_injected = False
    if decision == "approval_cancel_pause":
        from sagents.v2.runtime.kernel import HarnessRuntime
        from sagents.v2.contracts.commands import PauseRun

        original_cancel = HarnessRuntime.cancel_run

        async def concurrent_pause(runtime, command, context):
            nonlocal pause_injected
            if command.reason == "interaction_cancelled" and not pause_injected:
                pause_injected = True
                receipt = await runtime.pause_run(
                    PauseRun(
                        run_id=command.run_id,
                        expected_revision=command.expected_revision,
                        idempotency_key="race-pause",
                        reason="fixture",
                    ),
                    context,
                )
                assert receipt.error is None
            return await original_cancel(runtime, command, context)

        monkeypatch.setattr(HarnessRuntime, "cancel_run", concurrent_pause)
    first = make_host(
        tmp_path,
        [_step(1, "", "file_write", {"file_path": "approved.txt", "content": "yes"})],
    )
    with TestClient(create_app(first)) as client:
        first.im.pause()
        owner, user_id, agent, cid, _ = setup_route(first, client)
        # setup_route installs a per-instance capture; exercise the platform seam.
        channel = client.portal.call(
            first.im.channel, client.portal.call(first.im.store.get, cid)
        )
        del channel.send
        assert (
            client.put(
                "/api/auth/execution-policy", headers=owner, json={"shell": "ask"}
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"/api/agents/{agent}",
                headers=owner,
                json={"name": "Notifier", "tools": ["file_write"]},
            ).status_code
            == 200
        )
        if ingress == "im":
            client.portal.call(
                receive, first, client.portal.call(first.im.store.get, cid), "hello", 2
            )
        else:
            headers, url = owner, "/api/agent"
            if ingress == "scheduled":
                issued = client.post(
                    "/api/keys",
                    headers=owner,
                    json={
                        "agent_id": agent,
                        "name": "scheduler",
                        "scopes": ["a2a:invoke", "a2a:read"],
                    },
                ).json()["data"]
                headers = {
                    "Authorization": "Bearer " + issued["api_key"],
                    "SAGE-TENANT-ID": user_id,
                }
                url = f"/api/agents/{agent}/runs"
            response = client.post(
                url,
                headers=headers,
                json={
                    **_run_input("notification-lifecycle", "notification-request"),
                    "notification_connection_id": cid,
                },
            )
            assert response.status_code == 200, response.text
        approval = client.portal.call(wait_for_approval, first, user_id)
        for _ in range(3):
            client.portal.call(first.im.tick)
        rows = client.portal.call(first.im.store.deliveries, cid)
        assert sum(row.state == link_state for row in rows) == 1
        foreign, _ = identity(client, "notification-foreign")
        refused = client.post(
            f"/api/approvals/{approval['run_id']}/decisions",
            headers=foreign,
            json={"decision": "approve_once", "expected": approval["expected"]},
        )
        assert refused.status_code in {403, 404}, refused.text
        if decision == "accepted_approval":

            async def interrupted_handoff(*args, **kwargs):
                pass  # The durable reply committed; the process died before drive.

            monkeypatch.setattr(
                first.conversations.runs, "continue_detached_run", interrupted_handoff
            )
            accepted = client.post(
                f"/api/approvals/{approval['run_id']}/decisions",
                headers=owner,
                json={"decision": "approve_once", "expected": approval["expected"]},
            )
            assert accepted.status_code == 200, accepted.text
            current_run = client.portal.call(
                first.conversations.session_access.get_run,
                approval["run_id"],
                first.contexts.for_user(user_id),
            )
            assert current_run.state.value == "resuming"

    restarted = make_host(
        tmp_path,
        [_step(2, "", "im_notify", {"content": NOTICE}), _step(3, "Detailed result")],
    )
    with TestClient(create_app(restarted)) as client:
        restarted.im.pause()
        current = (
            approval
            if decision == "accepted_approval"
            else client.portal.call(restarted.conversations.pending_approvals, user_id)[
                "items"
            ][0]
        )
        assert current["run_id"] == approval["run_id"]
        if decision == "accepted_approval":
            pass
        elif decision in {"approve_once", "approval_cancel", "approval_cancel_pause"}:
            result = client.post(
                f"/api/approvals/{current['run_id']}/decisions",
                headers=owner,
                json={
                    "decision": "cancel"
                    if decision.startswith("approval_cancel")
                    else decision,
                    "payload": {},
                    "expected": current["expected"],
                },
            )
            assert result.status_code == 200, result.text
        elif ingress == "im":
            client.portal.call(
                receive,
                restarted,
                client.portal.call(restarted.im.store.get, cid),
                "/stop",
                3,
            )
        elif ingress == "scheduled":
            result = client.post(
                f"/api/agents/{agent}/runs/notification-lifecycle/notification-request/cancel",
                headers=headers,
            )
            assert result.status_code == 200, result.text
        else:
            result = client.post(
                f"/api/threads/{current['thread_id']}/cancel",
                headers=owner,
                json={"runId": current["run_id"]},
            )
            assert result.status_code == 200, result.text
        run = client.portal.call(drain, restarted, current["run_id"], user_id)
        completed = decision in {"approve_once", "accepted_approval"}
        expected = NOTICE if completed else "任务已取消。"
        assert [text for _, text, _ in sent].count(expected) == 1

        assert all(chat == "oc_dm" for chat, _, _ in sent)
        assert run.state.value == ("completed" if completed else "cancelled")
        assert (
            len(
                client.portal.call(
                    restarted.conversations.session_access.list_session_runs,
                    run.session_id,
                    restarted.contexts.for_user(user_id),
                )
            )
            == 1
        )
        assert (
            restarted.paths.workspace_dir(user_id, agent) / "approved.txt"
        ).exists() == completed
        assert not any(text == NOTICE for _, text, _ in sent) or completed
        assert pause_injected == (decision == "approval_cancel_pause")

    third = make_host(tmp_path, [])
    with TestClient(create_app(third)) as client:
        third.im.pause()
        for _ in range(5):
            client.portal.call(third.im.tick)
        assert [text for _, text, _ in sent].count(expected) == 1


async def test_active_approval_keeps_dedupe_after_completed_delivery_retention(im_host):
    host, conn, user = im_host
    host.execution.fallback_model = CompletingJudgeModel(
        ScriptedModelProvider(
            (
                _step(
                    1, "", "file_write", {"file_path": "first.txt", "content": "yes"}
                ),
                _step(
                    2, "", "file_write", {"file_path": "second.txt", "content": "yes"}
                ),
                _step(3, "done"),
            )
        )
    )
    await host.catalog.update_agent(
        user.user_id, conn.agent_id, {"name": "Approvals", "tools": ["file_write"]}
    )
    from tests.app.v2.server.im.test_gateway import pair

    await pair(host, conn, user)
    sent = []

    async def send(chat, text, uid):
        sent.append((text, uid))
        return "receipt-" + uid

    (await host.im.channel(conn)).send = send
    await receive(host, conn)
    approval = await wait_for_approval(host, user.user_id)
    for _ in range(3):
        await host.im.tick()

    def links():
        return [text for text, _ in sent if "?thread=" in text]

    assert len(links()) == 1
    async with host.im.store.locked(conn.id) as (db, _):
        for row in await host.im.store.deliveries(conn.id):
            if row.run_context and row.run_context["purpose"].startswith(
                "interaction:"
            ):
                (await db.get(DeliveryRow, row.id)).created_at = time.time() - 8 * 86400
    await host.im.store.cleanup(conn.id, host.im.worker)
    command = await host.conversations.session_access.get_start_command(
        approval["run_id"], host.contexts.for_user(user.user_id)
    )
    await host.im.notifications.observe(command, user.user_id, host.im.worker)
    await host.im.tick()
    assert len(links()) == 1
    await host.conversations.decide_approval(
        approval["run_id"],
        user_id=user.user_id,
        decision="approve_once",
        payload={},
        expected=approval["expected"],
    )
    second = await wait_for_approval(host, user.user_id)
    assert (
        second["expected"]["interaction_id"] != approval["expected"]["interaction_id"]
    )
    for _ in range(3):
        await host.im.tick()
    assert len(links()) == 2
