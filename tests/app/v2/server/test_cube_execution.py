from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.v2.server.bootstrap import ServerHost
from app.v2.server.database import Database, DatabaseSettings
from app.v2.server.main import create_app
from tests.app.v2.server.conftest import (
    CompletingJudgeModel,
    make_settings,
    scripted_hello,
)
from tests.app.v2.server.test_external_chat import setup_agent
from tests.app.v2.server.test_external_run_routes import _headers, _run
from tests.sagents.v2.cube_fakes import FakeCubeClient


def cube_host(path, provider=None):
    return ServerHost(
        make_settings(
            path,
            sandbox_plugin="sage.sandbox.cube-volume",
            cube_api_url="http://cube",
            cube_template_id="python",
            cube_proxy_node_ip="cube",
            log_level="warning",
        ),
        model_provider=CompletingJudgeModel(
            provider if provider is not None else scripted_hello(8)
        ),
        database=Database(DatabaseSettings(url=f"sqlite+aiosqlite:///{path}/host.db")),
    )


def test_cube_external_chat_files_and_new_run_after_server_restart(
    tmp_path, monkeypatch
):
    remote = FakeCubeClient(tmp_path / "cube")
    monkeypatch.setattr(
        "sagents.v2.runtime.execution.sandbox.plugins.cube.CubeVolumeClient",
        lambda **kwargs: remote,
    )
    data = tmp_path / "sage"
    with TestClient(create_app(cube_host(data))) as client:
        token = setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        base = f"/api/agents/{agent}"
        credentials = dict(client.headers)
        response = client.put(
            base + "/workspace/files",
            headers=_headers(),
            json={
                "directory": "projects/site",
                "files": {"index.html": "PGgxPkN1YmU8L2gxPg=="},
            },
        )
        assert response.status_code == 200, response.text
        binary = b"\x00\xffvideo" * 12000
        for _ in range(2):
            uploaded = client.put(
                base + "/workspace/file",
                headers=_headers(),
                params={"path": "projects/site/uploads/clip.bin"},
                content=binary,
            )
            assert uploaded.status_code == 200, uploaded.text
        conflict = client.put(
            base + "/workspace/file",
            headers=_headers(),
            params={"path": "projects/site/uploads/clip.bin"},
            content=b"different",
        )
        assert conflict.status_code == 409, conflict.text
        response = _run(client, agent)
        assert response.status_code == 200, response.text
        state = client.get(base + "/runs/thread-a/run-a", headers=_headers()).json()[
            "data"
        ]
        assert state["state"] == "completed", state
        assert not (data / "tenants" / "tenant-a" / agent / "workspace").exists()
        response = client.get(
            "/api/workspace/files",
            params={"thread_id": "thread-a", "path": "projects/site"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert {entry["name"] for entry in response.json()["data"]} == {
            "index.html",
            "uploads",
        }
        response = client.get(base + "/runs/thread-a/run-a/files", headers=_headers())
        assert response.status_code == 200, response.text
        with ZipFile(BytesIO(response.content)) as archive:
            assert archive.read("site/index.html") == b"<h1>Cube</h1>"
            assert archive.read("site/uploads/clip.bin") == binary
        response = client.get(
            base + "/runs/thread-a/run-a/files",
            headers=_headers(),
            params={"exclude": "uploads"},
        )
        assert response.status_code == 200, response.text
        with ZipFile(BytesIO(response.content)) as archive:
            assert archive.read("site/index.html") == b"<h1>Cube</h1>"
            assert "site/uploads/clip.bin" not in archive.namelist()
        assert (
            client.get(
                base + "/runs/thread-a/run-a/files", headers=_headers("other")
            ).status_code
            == 404
        )
    assert all(sandbox.killed for sandbox in remote.created)
    with TestClient(create_app(cube_host(data))) as client:
        client.headers.update(credentials)
        replay = _run(client, agent, run_id="run-a")
        assert replay.status_code == 200, replay.text
        conflict = client.post(
            base + "/runs",
            params={"workspace_path": "projects/site"},
            headers=_headers(),
            json={
                "threadId": "thread-a",
                "runId": "run-a",
                "messages": [{"id": "run-a", "role": "user", "content": "changed"}],
            },
        )
        assert conflict.status_code == 409, conflict.text
        response = _run(client, agent, run_id="run-b")
        assert response.status_code == 200, response.text
        state = client.get(base + "/runs/thread-a/run-b", headers=_headers()).json()[
            "data"
        ]
        assert state["state"] == "completed", state
        response = client.get(base + "/runs/thread-a/run-b/files", headers=_headers())
        assert response.status_code == 200, response.text
        with ZipFile(BytesIO(response.content)) as archive:
            assert archive.read("site/index.html") == b"<h1>Cube</h1>"
    assert all(sandbox.killed for sandbox in remote.created)


def test_cube_standard_shell_executes_in_the_remote_volume(tmp_path, monkeypatch):
    from sagents.v2.agent.policy.tool_policy import ApprovalStrategy
    from sagents.v2.agent.policy.plugins.tool_policy import DefaultToolPolicy
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.app.v2.server.test_a2a_resume import _step

    remote = FakeCubeClient(tmp_path / "cube")
    monkeypatch.setattr(
        "sagents.v2.runtime.execution.sandbox.plugins.cube.CubeVolumeClient",
        lambda **kwargs: remote,
    )
    monkeypatch.setattr(
        "app.v2.server.packages.tool_policy.server_tool_policy",
        lambda *args, **kwargs: DefaultToolPolicy(
            approval_strategy=ApprovalStrategy.AUTO_APPROVE
        ),
    )
    provider = ScriptedModelProvider(
        (
            _step(
                1,
                "execute",
                "execute_shell_command",
                {
                    "command": "printf remote > executed.txt",
                    "workdir": "/workspace/projects/site",
                },
            ),
            _step(2, "done"),
        )
    )
    data = tmp_path / "sage"
    with TestClient(create_app(cube_host(data, provider))) as client:
        token = setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        base = f"/api/agents/{agent}"
        response = client.put(
            base + "/workspace/files",
            headers=_headers(),
            json={"directory": "projects/site", "files": {}},
        )
        assert response.status_code == 200, response.text
        response = _run(client, agent)
        assert response.status_code == 200, response.text
        state = client.get(base + "/runs/thread-a/run-a", headers=_headers()).json()[
            "data"
        ]
        assert state["state"] == "completed", state
        response = client.get(
            "/api/workspace/download",
            params={"thread_id": "thread-a", "path": "projects/site/executed.txt"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert response.content == b"remote"
        assert not (data / "tenants" / "tenant-a" / agent / "workspace").exists()
    assert all(sandbox.killed for sandbox in remote.created)
