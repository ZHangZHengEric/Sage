import asyncio
from dataclasses import replace
import gc
from io import BytesIO
import os
from pathlib import Path
import threading
import weakref
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
import anyio

from app.v2.server.skills import agent_guidance, files, workspaces
from app.v2.server.skills.repository import MemorySkillStore
from app.v2.server.skills.service import SkillCatalogService
from app.v2.server.storage.paths import prepare_server_v2_storage


def _markdown(name):
    return f"---\nname: {name}\ndescription: Guide\n---\n# Guide\n"


def _zip(name, suffix=""):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", _markdown(name) + suffix)
    return buffer.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["publish_zip", "publish_directory", "read_content", "list_files"])
async def test_skill_file_operations_leave_the_event_loop(tmp_path, monkeypatch, operation):
    """Publishing and reading real artifacts must not perform disk/ZIP work on the loop."""
    service = SkillCatalogService(MemorySkillStore(), tmp_path)
    record = await service.publish_markdown(
        name="guide", content=_markdown("guide"), user_id="owner", role="user"
    )
    source = record.absolute_path(tmp_path)
    payload = _zip("guide")
    loop_thread = threading.get_ident()
    worker_threads = []
    if operation == "publish_zip":
        original = files.zipfile.ZipFile

        def observe_zip(*args, **kwargs):
            worker_threads.append(threading.get_ident())
            return original(*args, **kwargs)

        monkeypatch.setattr(files.zipfile, "ZipFile", observe_zip)
        await service.publish_zip(payload, filename="guide.zip", user_id="owner", role="user")
    elif operation == "read_content":
        original = Path.read_text

        def observe_read(path, *args, **kwargs):
            if path == source / "SKILL.md":
                worker_threads.append(threading.get_ident())
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", observe_read)
        assert await service.read_content(record.skill_id, user_id="owner", role="user") == _markdown("guide")
    else:
        original = Path.rglob

        def observe_scan(path, *args, **kwargs):
            if path == source:
                worker_threads.append(threading.get_ident())
            yield from original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "rglob", observe_scan)
        if operation == "publish_directory":
            assert (await service.publish_directory(source, user_id="owner", role="user")).skill_id == record.skill_id
        else:
            assert await service.list_files(record.skill_id, user_id="owner", role="user") == [
                {"path": "SKILL.md", "size": len(_markdown("guide").encode())}
            ]
    assert worker_threads, "The real file/ZIP operation was not exercised"
    assert all(thread != loop_thread for thread in worker_threads)


class _Catalog:
    def __init__(self, skill_catalog, agent_ids=("agent-a",)):
        self.skill_catalog = skill_catalog
        self.agents = {
            agent_id: {"id": agent_id, "instructions": "Original", "skills": []}
            for agent_id in agent_ids
        }

    async def get_agent(self, owner_id, agent_id):
        return dict(self.agents[agent_id], skills=list(self.agents[agent_id]["skills"]))

    async def get(self, owner_id):
        return SimpleNamespace(agents=[SimpleNamespace(**agent) for agent in self.agents.values()])

    async def update_agent_instructions(self, owner_id, agent_id, prompt):
        self.agents[agent_id]["instructions"] = prompt

    async def bind_agent_skills(self, owner_id, agent_id, names):
        await self.skill_catalog.bind_agent_skills(owner_user_id=owner_id, agent_id=agent_id, names=names)
        self.agents[agent_id]["skills"] = names


def _host(tmp_path, agent_ids=("agent-a",)):
    paths = prepare_server_v2_storage(tmp_path)
    skill_catalog = SkillCatalogService(MemorySkillStore(), paths.data_root)
    return SimpleNamespace(paths=paths, skill_catalog=skill_catalog, catalog=_Catalog(skill_catalog, agent_ids))


@pytest.mark.asyncio
async def test_guidance_decompresses_each_zip_once_in_a_worker(tmp_path, monkeypatch):
    host = _host(tmp_path)
    payload = _zip("guide")
    original = files.zipfile.ZipFile
    threads = []

    def observe_zip(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(files.zipfile, "ZipFile", observe_zip)
    result = await agent_guidance.sync_agent_guidance(
        host, owner_id="owner", agent_id="agent-a", prompt="Updated", files=[("guide.zip", payload)]
    )
    assert result["success_count"] == 1, result
    assert len(threads) == 1
    assert threads[0] != threading.get_ident()
    assert host.catalog.agents["agent-a"]["skills"] == ["guide"]


@pytest.mark.asyncio
async def test_guidance_releases_each_decoded_package_before_decoding_the_next(tmp_path, monkeypatch):
    host = _host(tmp_path)
    original = agent_guidance.inspect_skill_zip
    decoded_files = []

    class TrackedFiles(dict):
        pass

    def observe_decoding(*args, **kwargs):
        gc.collect()
        assert all(reference() is None for reference in decoded_files), "retained decoded packages grow with batch size"
        package = original(*args, **kwargs)
        tracked = TrackedFiles(package.files)
        decoded_files.append(weakref.ref(tracked))
        return replace(package, files=tracked)

    monkeypatch.setattr(agent_guidance, "inspect_skill_zip", observe_decoding)
    result = await agent_guidance.sync_agent_guidance(
        host, owner_id="owner", agent_id="agent-a", prompt="Original",
        files=[(f"{name}.zip", _zip(name)) for name in ("first", "second", "third")],
    )
    assert result["success_count"] == 3, result
    assert len(decoded_files) == 3


@pytest.mark.asyncio
async def test_guidance_same_name_uploads_report_each_sequential_result(tmp_path):
    host = _host(tmp_path)
    workspace = host.paths.workspace_dir("tenant", "agent-a")
    first, revised = _zip("guide"), _zip("guide", "Revised\n")
    result = await agent_guidance.sync_agent_guidance(
        host, owner_id="owner", agent_id="agent-a", prompt="Original",
        files=[("first.zip", first), ("same.zip", first), ("revised.zip", revised)],
    )
    assert result["success_count"] == 3, result
    assert [(item["filename"], item["changed"], item["workspaces"]) for item in result["results"]] == [
        ("first.zip", True, 1), ("same.zip", False, 1), ("revised.zip", True, 1)
    ]
    assert (workspace / "skills" / "guide" / "SKILL.md").read_text() == _markdown("guide") + "Revised\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["upload", "bound"])
async def test_guidance_batch_scans_tenants_once_and_keeps_individual_results(tmp_path, monkeypatch, mode):
    host = _host(tmp_path)
    records = []
    for name in ("current", "stale", "broken"):
        records.append(await host.skill_catalog.publish_markdown(
            name=name, content=_markdown(name), user_id="owner", role="user"
        ))
    await host.catalog.bind_agent_skills("owner", "agent-a", [record.name for record in records])
    for tenant in ("tenant-a", "tenant-b"):
        workspace = host.paths.workspace_dir(tenant, "agent-a")
        for name in ("current", "stale"):
            directory = workspace / "skills" / name
            directory.mkdir(parents=True)
            (directory / "SKILL.md").write_text(_markdown(name) if name == "current" else "old")
    if mode == "bound":
        (records[2].absolute_path(tmp_path) / "SKILL.md").unlink()
    tenants_identity = host.paths.tenants_root.stat()
    scans = []
    original = os.listdir

    def observe_listdir(path):
        if isinstance(path, int):
            info = os.fstat(path)
            if (info.st_dev, info.st_ino) == (tenants_identity.st_dev, tenants_identity.st_ino):
                scans.append(threading.get_ident())
        return original(path)

    monkeypatch.setattr(os, "listdir", observe_listdir)
    if mode == "bound":
        result = await agent_guidance.sync_bound_agent_skills(host, owner_id="owner", agent_id="agent-a")
    else:
        result = await agent_guidance.sync_agent_guidance(
            host, owner_id="owner", agent_id="agent-a", prompt="Original",
            files=[("current.zip", _zip("current")), ("broken.zip", b"not a ZIP"), ("stale.zip", _zip("stale"))],
        )
    assert result["success_count"] == 2 and result["failed_count"] == 1, result
    by_name = {item["name"]: item for item in result["results"] if item["success"]}
    assert {name: (item["changed"], item["workspaces"]) for name, item in by_name.items()} == {
        "current": (False, 2), "stale": (True, 2)
    }
    for tenant in ("tenant-a", "tenant-b"):
        for name in ("current", "stale"):
            assert (host.paths.workspace_path(tenant, "agent-a") / "skills" / name / "SKILL.md").read_text() == _markdown(name)
    assert len(scans) == 1
    assert scans[0] != threading.get_ident()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["upload", "bound"])
async def test_guidance_workspace_failure_does_not_prevent_other_skills(tmp_path, mode):
    host = _host(tmp_path)
    for name in ("broken", "good"):
        await host.skill_catalog.publish_markdown(
            name=name, content=_markdown(name), user_id="owner", role="user"
        )
    await host.catalog.bind_agent_skills("owner", "agent-a", ["broken", "good"])
    workspace = host.paths.workspace_dir("tenant", "agent-a")
    broken = workspace / "skills" / "broken"
    broken.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("must remain untouched")
    (broken / "SKILL.md").symlink_to(outside)

    if mode == "bound":
        result = await agent_guidance.sync_bound_agent_skills(host, owner_id="owner", agent_id="agent-a")
    else:
        result = await agent_guidance.sync_agent_guidance(
            host, owner_id="owner", agent_id="agent-a", prompt="Original",
            files=[(f"{name}.zip", _zip(name)) for name in ("broken", "good")],
        )

    assert result["success_count"] == 1 and result["failed_count"] == 1, result
    good = next(item for item in result["results"] if item["success"])
    assert (good["name"], good["changed"], good["workspaces"]) == ("good", True, 1)
    assert (workspace / "skills" / "good" / "SKILL.md").read_text() == _markdown("good")
    assert outside.read_text() == "must remain untouched"
    assert (broken / "SKILL.md").is_symlink()


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("same_agent", [False, True], ids=["different-agents", "same-agent"])
async def test_guidance_serializes_only_the_same_agent(tmp_path, monkeypatch, same_agent):
    host = _host(tmp_path, ("agent-a", "agent-b"))
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()
    release_first = asyncio.Event()
    original = host.catalog.get_agent
    calls = 0

    async def controlled_get(owner_id, agent_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_entered.set()
            await release_first.wait()
        else:
            second_entered.set()
        return await original(owner_id, agent_id)

    monkeypatch.setattr(host.catalog, "get_agent", controlled_get)
    first = asyncio.create_task(agent_guidance.sync_bound_agent_skills(host, owner_id="owner", agent_id="agent-a"))
    await asyncio.wait_for(first_entered.wait(), 1)
    second_attempted = asyncio.Event()

    async def second_sync():
        second_attempted.set()
        return await agent_guidance.sync_bound_agent_skills(
            host, owner_id="owner", agent_id="agent-a" if same_agent else "agent-b"
        )

    second = asyncio.create_task(second_sync())
    try:
        await asyncio.wait_for(second_attempted.wait(), 1)
        if same_agent:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(second_entered.wait(), 0.05)
        else:
            await asyncio.wait_for(second_entered.wait(), 1)
    finally:
        release_first.set()
        await asyncio.gather(first, second)
    assert second_entered.is_set()


@pytest.mark.asyncio
async def test_different_agents_cannot_concurrently_claim_the_same_skill(tmp_path, monkeypatch):
    host = _host(tmp_path, ("agent-a", "agent-b"))
    publishing, release = asyncio.Event(), asyncio.Event()
    attempting, checked = asyncio.Event(), asyncio.Event()
    original_publish = host.skill_catalog.publish_package
    original_get = host.catalog.get
    calls = 0

    async def paused_publish(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            publishing.set()
            await release.wait()
        return await original_publish(*args, **kwargs)

    async def observe_catalog(*args):
        if publishing.is_set():
            checked.set()
        return await original_get(*args)

    monkeypatch.setattr(host.skill_catalog, "publish_package", paused_publish)
    monkeypatch.setattr(host.catalog, "get", observe_catalog)

    async def sync(agent_id):
        return await agent_guidance.sync_agent_guidance(
            host, owner_id="owner", agent_id=agent_id, prompt="Original", files=[("guide.zip", _zip("guide"))]
        )

    first = asyncio.create_task(sync("agent-a"))
    await asyncio.wait_for(publishing.wait(), 2)

    async def compete():
        attempting.set()
        return await sync("agent-b")

    second = asyncio.create_task(compete())
    try:
        await asyncio.wait_for(attempting.wait(), 2)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(checked.wait(), 0.1)
        release.set()
        results = await asyncio.gather(first, second)
        assert sorted(result["success_count"] for result in results) == [0, 1]
        assert host.catalog.agents["agent-a"]["skills"] == ["guide"]
        assert host.catalog.agents["agent-b"]["skills"] == []
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancellation", ["asyncio-repeated", "anyio-scope"])
async def test_cancelled_skill_sync_keeps_agent_locked_until_file_write_finishes(tmp_path, monkeypatch, cancellation):
    host = _host(tmp_path)
    await host.skill_catalog.publish_markdown(
        name="guide", content=_markdown("guide"), user_id="owner", role="user"
    )
    await host.catalog.bind_agent_skills("owner", "agent-a", ["guide"])
    host.paths.workspace_dir("tenant", "agent-a")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    cancelled, attempting, admitted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_write = workspaces._write_package
    original_get = host.catalog.get_agent

    def controlled_write(*args):
        entered.set()
        try:
            assert release.wait(3)
            return original_write(*args)
        finally:
            finished.set()

    async def observe_admission(*args):
        if entered.is_set():
            admitted.set()
            assert finished.is_set(), "same Agent admitted while a cancelled file worker was still running"
        return await original_get(*args)

    monkeypatch.setattr(workspaces, "_write_package", controlled_write)
    monkeypatch.setattr(host.catalog, "get_agent", observe_admission)

    async def sync():
        return await agent_guidance.sync_bound_agent_skills(host, owner_id="owner", agent_id="agent-a")

    async def cancelled_scope():
        async with anyio.create_task_group() as group:
            group.start_soon(sync)
            assert await asyncio.to_thread(entered.wait, 2)
            cancelled.set()
            group.cancel_scope.cancel()

    async def competing_sync():
        attempting.set()
        return await sync()

    first = asyncio.create_task(cancelled_scope() if cancellation == "anyio-scope" else sync())
    second = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        if cancellation == "asyncio-repeated":
            first.cancel()
            asyncio.get_running_loop().call_soon(first.cancel)
        else:
            await asyncio.wait_for(cancelled.wait(), 2)
        second = asyncio.create_task(competing_sync())
        await asyncio.wait_for(attempting.wait(), 2)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(admitted.wait(), 0.03)
        release.set()
        if cancellation == "asyncio-repeated":
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            await first
        result = await second
        assert result["success_count"] == 1 and result["results"][0]["changed"] is False
        assert admitted.is_set() and finished.is_set()
    finally:
        release.set()
        await asyncio.gather(first, *([second] if second else []), return_exceptions=True)
        assert await asyncio.to_thread(finished.wait, 2)
