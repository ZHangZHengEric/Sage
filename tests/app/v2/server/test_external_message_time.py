"""External chat preserves message time through legacy history, retries and restart."""
from fastapi.testclient import TestClient
import pytest

from app.v2.server.main import create_app
from app.v2.server.conversations.agui import mapping
from sagents.v2.context.message_time import FROZEN_TIME_KEY
from sagents.v2.contracts.items import TextBlock
from tests.app.v2.server.test_external_chat import make_host, setup_agent


@pytest.mark.parametrize("legacy", [False, True])
def test_external_message_times_survive_restart_and_idempotent_retries(tmp_path, monkeypatch, legacy):
    old_time = "2026-11-15T22:27:24.984660+08:00, Sunday"
    new_time = "2026-11-18T23:19:05.713491+08:00, Wednesday"
    text = "睡觉，明天还要带孩子去医院"
    first_body = {"threadId": "dated-chat", "runId": "sleep", "messages": [
        {"id": "sleep-message", "role": "user", "content": text}],
        "runtimeContext": {"current_time": old_time, "current_timezone": "Asia/Shanghai"}}
    host = make_host(tmp_path)
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        auth = client.headers["Authorization"]
        url = f"/api/agents/{agent}/runs"
        headers = {"SAGE-TENANT-ID": "dated-user"}
        with monkeypatch.context() as patch:
            if legacy:
                latest = mapping.latest_user_input
                patch.setattr(mapping, "latest_user_input", lambda request, **_: latest(request))
            response = client.post(url, headers=headers, json=first_body)
            assert "RUN_FINISHED" in response.text, response.text[-2000:]
        portal = client.portal
        assert portal is not None

        async def original():
            store = host.application.runtime.session_store
            run = (await store.list_session_runs("dated-chat"))[0]
            command = await store.get_start_command(run.run_id)
            assert command.input[0].content == (TextBlock(text=text),)
            if legacy:
                assert command.input[0].metadata == {}
            else:
                assert old_time in command.input[0].metadata[FROZEN_TIME_KEY]
                assert "Asia/Shanghai" in command.input[0].metadata[FROZEN_TIME_KEY]
            return command

        stored = portal.call(original)
        # Upgrading must replay both old unanchored and new anchored commands.
        assert "RUN_FINISHED" in client.post(url, headers=headers, json=first_body).text

    host = make_host(tmp_path)
    with TestClient(create_app(host)) as client:
        client.headers.update({"Authorization": auth, "SAGE-TENANT-ID": "dated-user"})
        assert "RUN_FINISHED" in client.post(url, json=first_body).text
        second_body = {"threadId": "dated-chat", "runId": "greeting", "messages": [
            {"id": "greeting-message", "role": "user", "content": "晚上好"}],
            "runtimeContext": {"current_time": new_time, "current_timezone": "Asia/Shanghai"}}
        response = client.post(url, json=second_body)
        assert "RUN_FINISHED" in response.text, response.text[-2000:]
        requests = host.execution.fallback_model.provider.requests
        request = requests[-1]
        users = [message for message in request.messages if message.role == "user"]
        old = next(message for message in users if text in str(message.content))
        current = users[-1]
        assert old_time in str(old.content) and new_time not in str(old.content)
        assert "Asia/Shanghai" in str(old.content)
        assert new_time in str(current.content)
        assert "Historical plans" in str(request.messages) and "original local date" in str(request.messages)
        assert client.post(url, json=second_body).status_code == 200
        for changed in (
            {**second_body, "messages": [{"id": "greeting-message", "role": "user", "content": "changed"}]},
            {**second_body, "runtimeContext": {"current_time": old_time, "current_timezone": "Asia/Shanghai"}},
        ):
            assert client.post(url, json=changed).status_code == 409

        async def persisted():
            store = host.application.runtime.session_store
            runs = await store.list_session_runs("dated-chat")
            assert len(runs) == 2
            assert await store.get_start_command(runs[0].run_id) == stored
            latest = await store.get_start_command(runs[1].run_id)
            assert latest.input[0].content == (TextBlock(text="晚上好"),)
            assert new_time in latest.input[0].metadata[FROZEN_TIME_KEY]
            events = await store.read_events(runs[1].run_id)
            user_items = [event.data.item.data for event in events
                          if event.type == "message.completed" and event.data.item.data.role == "user"]
            assert [item.content for item in user_items] == [(TextBlock(text="晚上好"),)]

        client.portal.call(persisted)


def test_external_retry_without_clock_reuses_the_original_acceptance_time(tmp_path):
    host = make_host(tmp_path)
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        body = {"threadId": "no-clock", "runId": "once", "messages": [
            {"id": "input", "role": "user", "content": "hello"}]}
        url = f"/api/agents/{client.headers['SAGE-AGENT-ID']}/runs"
        for _ in range(2):
            response = client.post(url, headers={"SAGE-TENANT-ID": "dated-user"}, json=body)
            assert "RUN_FINISHED" in response.text, response.text[-2000:]
        assert len(host.execution.fallback_model.provider.requests) == 1
