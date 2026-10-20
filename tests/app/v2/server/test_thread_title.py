import pytest
from fastapi.testclient import TestClient

from app.v2.server.bootstrap import ServerHost
from app.v2.server.conversations.records import ThreadRecord, apply_thread_upsert
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.main import create_app
from tests.app.v2.server.conftest import (
    CompletingJudgeModel,
    make_settings,
    register_and_login,
    scripted_hello,
)


@pytest.mark.parametrize(
    ("existing_title", "incoming_title", "expected"),
    [
        (None, "首次提问", "首次提问"),
        ("", "首次提问", "首次提问"),
        ("首次提问", "后续追问", "首次提问"),
        ("首次提问", "", "首次提问"),
        ("", "", ""),
    ],
)
def test_thread_title_keeps_first_nonempty_input(existing_title, incoming_title, expected):
    existing = (
        None if existing_title is None else ThreadRecord(
            thread_id="thread-1", user_id="user-1", title=existing_title,
        )
    )
    updated = apply_thread_upsert(
        existing, thread_id="thread-1", user_id="user-1", title=incoming_title,
    )
    assert updated.title == expected


def test_agui_history_keeps_first_title_after_followup_and_restart(tmp_path):
    def host():
        return ServerHost(
            make_settings(tmp_path),
            model_provider=CompletingJudgeModel(scripted_hello(steps=2)),
            database=Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{tmp_path}/host.db")),
        )

    first_message = "首次对话内容" * 20
    with TestClient(create_app(host())) as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        timestamps = []
        for index, message in enumerate((first_message, "后续追问不能覆盖首次标题")):
            response = client.post(
                "/api/agent",
                headers=headers,
                json={
                    "threadId": "thread-title",
                    "runId": f"run-{index}",
                    "messages": [{"id": f"message-{index}", "role": "user", "content": message}],
                },
            )
            assert response.status_code == 200, response.text
            assert '"type":"RUN_FINISHED"' in response.text
            history = client.get("/api/threads", headers=headers)
            assert history.status_code == 200
            thread = history.json()["data"]["items"][0]
            assert thread["title"] == first_message[:80]
            timestamps.append(thread["updated_at"])
        assert timestamps[1] > timestamps[0]

    with TestClient(create_app(host())) as restarted:
        history = restarted.get("/api/threads", headers=headers)
        assert history.status_code == 200
        assert history.json()["data"]["items"][0]["title"] == first_message[:80]
