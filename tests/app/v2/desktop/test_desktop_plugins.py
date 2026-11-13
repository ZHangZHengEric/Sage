import asyncio
import io
import json
import zipfile

import pytest

from app.v2.desktop.backend.catalog import SAGE_DEFAULT_SKILLS, default_agent_config
from app.v2.desktop.backend.desktop_plugin_api import _document
from app.v2.desktop.backend.desktop_plugins import (
    DesktopPluginStore,
    PluginConflict,
    plugin_contract_root,
    validate_package,
)
from app.v2.desktop.backend.schemas import DesktopRunRequest, RunMessage
from sagents.v2.model import ModelToolCall, ScriptedModelProvider
from tests.app.v2.desktop.sdk_fixture import desktop, execute, step


def archive(*, version="1.0.0", extra=None, include_logo=True):
    example = plugin_contract_root() / "example"
    manifest = json.loads((example / "manifest.json").read_bytes())
    manifest["version"] = version
    if not include_logo:
        del manifest["logo"]
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as output:
        output.writestr("manifest.json", json.dumps(manifest))
        for name in ("index.html", "todo.js", *(("logo.png",) if include_logo else ())):
            output.writestr(name, (example / name).read_bytes())
        if extra:
            output.writestr(*extra)
    return data.getvalue()


@pytest.mark.parametrize(
    "path",
    [
        "../index.html",
        "/outside.js",
        "foo\\bad.js",
        "index.HTML",
        "__sage/sdk.js",
        "AUX.js",
    ],
)
def test_package_rejects_unsafe_entries(path):
    with pytest.raises(ValueError):
        validate_package(archive(extra=(path, "bad")))


@pytest.mark.asyncio
async def test_registration_push_reconnect_upgrade_and_isolation(tmp_path):
    path = tmp_path / "plugins.db"
    store = DesktopPluginStore(path)
    stream = store.snapshots("owner", "window")
    assert (await anext(stream))["plugins"] == []
    notification = asyncio.create_task(anext(stream))
    package = validate_package(archive())
    first = await store.register("owner", "window", package)
    with pytest.raises(ValueError, match="manifest.logo"):
        await store.register(
            "owner", "window", validate_package(archive(version="1.1.0", include_logo=False))
        )
    event = await asyncio.wait_for(notification, timeout=2)
    opened = event["opens"][0]["request"]
    assert event["plugins"][0]["id"] == first["pluginId"]
    assert store.snapshot("owner", "other")["opens"] == []
    assert store.snapshot("other", "window")["plugins"] == []
    assert await store.register("owner", "window", package) == first
    assert store.snapshot("owner", "window") == event
    await stream.aclose()
    restarted = DesktopPluginStore(path)
    assert restarted.snapshot("owner", "window") == event
    await restarted.acknowledge("owner", "other", opened)
    assert restarted.snapshot("owner", "window")["opens"]
    await restarted.acknowledge("owner", "window", opened)
    assert restarted.snapshot("owner", "window")["opens"] == []
    plugin_id = first["pluginId"]
    await restarted.manage("owner", plugin_id, "pin")
    restarted.storage("owner", plugin_id, package.digest, "set", "items", ["one"])
    restarted.permission("owner", plugin_id, package.digest, "draft", grant=True)
    with pytest.raises(PluginConflict):
        await restarted.register(
            "owner", "window", validate_package(archive(extra=("more.js", "1")))
        )
    update = validate_package(archive(version="1.1.0"))
    await restarted.register("owner", "window", update)
    assert restarted.snapshot("owner", "window")["plugins"][0]["pin"] == 1
    assert restarted.storage(
        "owner", plugin_id, update.digest, "get", "items", None
    ) == ["one"]
    assert restarted.permission("owner", plugin_id, update.digest, "draft")[0]
    with pytest.raises(PluginConflict):
        restarted.package("owner", plugin_id, package.digest)
    with pytest.raises(FileNotFoundError):
        restarted.storage("other", plugin_id, update.digest, "get", "items", None)
    await restarted.manage("owner", plugin_id, "disable")
    assert restarted.snapshot("owner", "window")["opens"] == []
    assert restarted.installed_package("owner", plugin_id)[1] == update.archive
    with pytest.raises(FileNotFoundError):
        restarted.installed_package("other", plugin_id)
    with pytest.raises(PluginConflict):
        restarted.permission("owner", plugin_id, update.digest, "draft")
    await restarted.manage("owner", plugin_id, "uninstall")
    assert restarted.snapshot("owner", "window")["plugins"] == []
    assert "__sage/sdk.js" in _document(package)["assets"]


@pytest.mark.asyncio
async def test_real_desktop_agent_tool_publishes_before_run_completion(tmp_path):
    owner, client = "user_1", "desktop-test-window"
    snapshot_seen = asyncio.Event()

    class GatedModel(ScriptedModelProvider):
        async def _stream(self, request):
            if self.requests:
                await asyncio.wait_for(snapshot_seen.wait(), timeout=5)
            async for event in super()._stream(request):
                yield event

    model = GatedModel(
        (
            step(
                ModelToolCall(
                    tool_call_id="register",
                    name="register_desktop_plugin",
                    arguments={"package_path": "todo.zip"},
                )
            ),
            step(text="Registered"),
            step(
                ModelToolCall(
                    tool_call_id="list",
                    name="list_desktop_plugins",
                    arguments={},
                )
            ),
            step(
                ModelToolCall(
                    tool_call_id="download",
                    name="download_desktop_plugin",
                    arguments={
                        "plugin_id": "example.todo",
                        "destination_path": "installed-todo.zip",
                    },
                )
            ),
            step(text="Downloaded"),
        )
    )
    service, _, _ = desktop(tmp_path, model=model)
    agent = await service._agent("sage", owner)
    await service.catalog.save_agent(
        agent.model_copy(
            update={
                "config": {
                    "availableSkills": [],
                    "availableTools": ["load_skill"],
                },
            }
        )
    )
    assert {
        value["name"] for value in await service.list_skills("sage", owner)
    } == set(SAGE_DEFAULT_SKILLS)
    await service.initialize_agent_workspace()
    workspace = await service.workspace_root(None, "sage")
    archive_bytes = archive()
    (workspace / "todo.zip").write_bytes(archive_bytes)
    updates = service.desktop_plugins.snapshots(owner, client)
    assert (await anext(updates))["plugins"] == []
    run_task = asyncio.create_task(
        execute(
            service,
            user=owner,
            request=DesktopRunRequest(
                agent_id="sage",
                desktop_client_id=client,
                approval_mode="auto_approve",
                messages=[
                    RunMessage(role="user", text="Register and open this todo plugin")
                ],
            ),
        )
    )
    try:
        update_task = asyncio.create_task(anext(updates))
        done, _ = await asyncio.wait(
            {update_task, run_task}, timeout=8, return_when=asyncio.FIRST_COMPLETED
        )
        if run_task in done:
            _, _, frames = run_task.result()
            pytest.fail(str(frames)[-10000:])
        try:
            event = await asyncio.wait_for(update_task, timeout=1)
            assert event["plugins"][0]["id"] == "example.todo"
            assert event["opens"][0]["plugin"] == "example.todo"
        finally:
            snapshot_seen.set()
        run, _, frames = await asyncio.wait_for(run_task, timeout=8)
        assert run.state.value == "completed", frames
        tools = {tool.name for tool in model.requests[0].tools}
        assert "register_desktop_plugin" in tools
        assert {"list_desktop_plugins", "download_desktop_plugin"} <= tools
        (workspace / "todo.zip").unlink()
        downloaded_run, _, frames = await execute(service, user=owner)
        assert downloaded_run.session_id != run.session_id
        assert downloaded_run.state.value == "completed", frames
        assert (workspace / "installed-todo.zip").read_bytes() == archive_bytes
        assert "search_skills" in tools
        assert "sage-desktop-plugin-development" in str(model.requests[0].messages)
        assert "<skill_name>pdf</skill_name>" not in str(model.requests[0].messages)
        assert "validate_desktop_plugin" not in tools
    finally:
        if not run_task.done():
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        if "update_task" in locals() and not update_task.done():
            update_task.cancel()
            await asyncio.gather(update_task, return_exceptions=True)
        await updates.aclose()
        await service.close()


@pytest.mark.asyncio
async def test_authenticated_preview_and_bearer_permissions(tmp_path, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.v2.desktop.backend.app import create_app
    from app.v2.desktop.backend import desktop_plugin_api

    service, _, _ = desktop(tmp_path)
    app = create_app(service=service, auth_token="test-token")
    transport = ASGITransport(app=app)
    raw = archive()
    source = zipfile.ZipFile(io.BytesIO(raw))
    manifest = json.loads(source.read("manifest.json"))
    manifest["capabilities"].append("https")
    manifest["endpoints"] = {
        "data": {
            "url": "https://example.test/v1/data",
            "method": "POST",
            "auth": "bearer",
        }
    }
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as output:
        output.writestr("manifest.json", json.dumps(manifest))
        output.writestr("index.html", source.read("index.html"))
        output.writestr("logo.png", source.read("logo.png"))
    source.close()
    package = validate_package(payload.getvalue())
    calls = []

    def external(endpoint, body, bearer):
        calls.append((endpoint, body, bearer))
        return {"status": 200, "body": "{}"}

    monkeypatch.setattr(desktop_plugin_api, "_https", external)
    try:
        async with AsyncClient(
            transport=transport, base_url="http://sidecar"
        ) as client:
            path = "/api/v2/desktop-plugins"
            assert (
                await client.post(f"{path}/preview", content=payload.getvalue())
            ).status_code == 401
            client.headers["Authorization"] = "Bearer test-token"
            assert (
                await client.post(f"{path}/preview", content=payload.getvalue())
            ).status_code == 200
            assert (await client.get(path)).json()["data"]["plugins"] == []
            invalid = await client.post(
                f"{path}/upload?client=client", content=b"bad ZIP"
            )
            assert invalid.status_code == 400
            assert (await client.get(path)).json()["data"]["plugins"] == []
            uploaded = await client.post(
                f"{path}/upload?client=client", content=payload.getvalue()
            )
            assert uploaded.status_code == 200
            assert uploaded.json()["data"]["pluginId"] == "example.todo"
            snapshot = (await client.get(f"{path}?client=client")).json()["data"]
            assert snapshot["opens"][0]["plugin"] == "example.todo"
            base = f"{path}/example.todo/{package.digest}"
            assert (await client.get(f"{base}/logo")).content == package.assets["logo.png"]
            assert (await client.post(f"{base}/https/data", json={})).status_code == 403
            params = {"capability": "https", "endpoint": "data"}
            response = await client.post(
                f"{base}/permission?grant=true",
                json={**params, "bearer": "private-token"},
            )
            assert response.json()["data"]["needsBearer"] is False
            assert "private-token" not in response.text
            assert (await client.post(f"{base}/https/data", json={})).status_code == 200
            assert calls[0][2] == "private-token"
            assert (
                await client.post(f"{path}/example.todo/manage/revoke")
            ).status_code == 200
            assert (await client.post(f"{base}/https/data", json={})).status_code == 403
            assert len(calls) == 1
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_legacy_validation_grant_does_not_enable_registration(tmp_path):
    service, _, _ = desktop(tmp_path)
    try:
        owner = "user_1"
        agent = await service._agent("sage", owner)
        old_tools = [
            name
            for name in default_agent_config()["availableTools"]
            if name != "register_desktop_plugin"
        ]
        await service.catalog.save_agent(
            agent.model_copy(
                update={
                    "config": {
                        **agent.config,
                        "availableTools": [*old_tools, "validate_desktop_plugin"],
                    }
                }
            )
        )
        for _ in range(2):
            refreshed = await service._agent("sage", owner)
            assert refreshed.config["availableTools"] == old_tools
    finally:
        await service.close()
