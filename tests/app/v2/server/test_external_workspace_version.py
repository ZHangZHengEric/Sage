"""Content versions must avoid ZIPs without weakening exact-Run file isolation."""

from dataclasses import replace
import os
import re
import threading

import pytest
from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from app.v2.server.routers import conversations
from app.v2.server.storage import downloads
from tests.app.v2.server.test_external_chat import make_host, setup_agent
from tests.app.v2.server.test_external_run_routes import _headers, _run


def _version(root, value="project", **kwargs):
    return downloads.workspace_version(root, value, **kwargs)


def test_workspace_version_uses_content_not_timestamps_and_never_builds_zip(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    page = project / "index.html"
    page.write_bytes(b"first")

    def forbidden_archive(*args, **kwargs):
        pytest.fail("A content version must not create a ZIP or temporary download")

    monkeypatch.setattr(downloads, "ZipFile", forbidden_archive)
    monkeypatch.setattr(downloads, "SpooledTemporaryFile", forbidden_archive)
    initial = _version(tmp_path)
    assert re.fullmatch(r"[0-9a-f]{64}", initial["version"])
    assert initial["files"] == 1
    assert initial["bytes"] == 5

    info = page.stat()
    os.utime(page, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    assert _version(tmp_path) == initial

    page.write_bytes(b"other")
    os.utime(page, ns=(info.st_atime_ns, info.st_mtime_ns))
    changed = _version(tmp_path)
    assert changed["version"] != initial["version"]
    assert changed["files"] == 1
    assert changed["bytes"] == 5


def test_workspace_version_is_sorted_path_sensitive_and_excludes_only_root_entry(tmp_path):
    project = tmp_path / "project"
    (project / "src" / "user-uploads").mkdir(parents=True)
    (project / "user-uploads").mkdir()
    (project / "z.txt").write_bytes(b"last")
    (project / "a.txt").write_bytes(b"first")
    nested = project / "src" / "user-uploads" / "needed.txt"
    nested.write_bytes(b"nested")
    excluded = project / "user-uploads" / "large.bin"
    excluded.write_bytes(b"ignored")
    version = _version(tmp_path, exclude_root_entry="user-uploads")
    assert version["files"] == 3
    assert version["bytes"] == 15
    excluded.write_bytes(b"different ignored contents")
    assert _version(tmp_path, exclude_root_entry="user-uploads") == version
    nested.write_bytes(b"change")
    assert _version(tmp_path, exclude_root_entry="user-uploads")["version"] != version["version"]
    nested.write_bytes(b"nested")

    # Recreate in a different directory-entry order. Relative paths and bytes match.
    copy = tmp_path / "copy"
    (copy / "src" / "user-uploads").mkdir(parents=True)
    (copy / "a.txt").write_bytes(b"first")
    (copy / "z.txt").write_bytes(b"last")
    (copy / "src" / "user-uploads" / "needed.txt").write_bytes(b"nested")
    assert _version(tmp_path, "copy") == version
    (copy / "a.txt").rename(copy / "b.txt")
    assert _version(tmp_path, "copy")["version"] != version["version"]


def test_workspace_version_skips_symlinks_and_refuses_symlink_traversal(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "index.html").write_bytes(b"safe")
    baseline = _version(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"private")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"private")
    (project / "secret-link").symlink_to(secret)
    (project / "directory-link").symlink_to(outside, target_is_directory=True)
    assert _version(tmp_path) == baseline
    with pytest.raises(OSError):
        _version(tmp_path, "project/directory-link")
    with pytest.raises(ValueError):
        _version(tmp_path, "../outside")


@pytest.mark.parametrize("limits", [{"max_bytes": 3}, {"max_entries": 1}])
def test_workspace_version_enforces_download_quotas(tmp_path, limits):
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "index.html").write_bytes(b"large")
    with pytest.raises(OverflowError):
        _version(tmp_path, **limits)


@pytest.mark.parametrize("mutation", ["truncate", "grow", "rewrite"])
def test_workspace_version_rejects_content_mutation_during_read(tmp_path, monkeypatch, mutation):
    (tmp_path / "project").mkdir()
    page = tmp_path / "project" / "large.bin"
    page.write_bytes(b"x" * (2 * 1024 * 1024))
    original_open = downloads.os.fdopen

    class MutatingReader:
        def __init__(self, fd, *args, **kwargs):
            self.inner = original_open(fd, *args, **kwargs)
            self.mutated = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

        def read(self, size=-1):
            content = self.inner.read(size)
            if not self.mutated:
                self.mutated = True
                info = page.stat()
                if mutation == "truncate":
                    page.write_bytes(b"")
                elif mutation == "grow":
                    with page.open("ab") as target:
                        target.write(b"new")
                else:
                    with page.open("r+b") as target:
                        target.write(b"changed")
                    os.utime(page, ns=(info.st_atime_ns, info.st_mtime_ns))
            return content

    monkeypatch.setattr(downloads.os, "fdopen", MutatingReader)
    with pytest.raises(downloads.SnapshotChangedError):
        _version(tmp_path)


@pytest.mark.timeout(20)
def test_run_content_version_preserves_authorization_exclusions_and_latest_run_fence(tmp_path):
    host = make_host(tmp_path)
    host.settings = replace(host.settings, log_directory=str(tmp_path / "logs"))
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        assert _run(client, agent).status_code == 200
        project = host.paths.workspace_path("tenant-a", agent) / "projects" / "site"
        project.mkdir(parents=True, exist_ok=True)
        (project / "index.html").write_bytes(b"hello")
        (project / "user-uploads").mkdir()
        (project / "user-uploads" / "photo.jpg").write_bytes(b"photo")
        endpoint = f"/api/agents/{agent}/runs/thread-a/run-a/files/version"
        response = client.get(endpoint, headers=_headers(), params={"exclude": "user-uploads"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["code"] == 0
        assert body["data"] == _version(project.parent, "site", exclude_root_entry="user-uploads")
        assert body["data"]["files"] == 1
        assert body["data"]["bytes"] == 5
        assert client.get(endpoint, headers=_headers("tenant-b")).status_code == 404
        assert client.get(endpoint.replace("run-a/", "missing/"), headers=_headers()).status_code == 404
        assert client.get(endpoint.replace("thread-a/", "missing/"), headers=_headers()).status_code == 404
        for invalid in ("../escape", "nested/uploads", ".sage", ""):
            assert client.get(endpoint, headers=_headers(), params={"exclude": invalid}).status_code == 422
        assert _run(client, agent, run_id="run-b").status_code == 200
        assert client.get(endpoint, headers=_headers()).status_code == 409


@pytest.mark.timeout(20)
def test_run_content_version_hashes_in_worker_thread_and_fences_after_scan(tmp_path, monkeypatch):
    host = make_host(tmp_path)
    host.settings = replace(host.settings, log_directory=str(tmp_path / "logs"))
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        assert _run(client, agent).status_code == 200
        project = host.paths.workspace_path("tenant-a", agent) / "projects" / "site"
        project.mkdir(parents=True, exist_ok=True)
        (project / "index.html").write_bytes(b"hello")
        threads = {}
        checks = []
        original_check = conversations.access.current_run_workspace
        original_version = getattr(conversations, "workspace_version")

        async def capture_access(*args, **kwargs):
            threads["event_loop"] = threading.get_ident()
            checks.append(kwargs)
            if len(checks) == 2:
                from fastapi import HTTPException
                raise HTTPException(409, "a newer run owns this workspace")
            return await original_check(*args, **kwargs)

        def capture_hash(*args, **kwargs):
            threads["hash"] = threading.get_ident()
            return original_version(*args, **kwargs)

        monkeypatch.setattr(conversations.access, "current_run_workspace", capture_access)
        monkeypatch.setattr(conversations, "workspace_version", capture_hash)
        response = client.get(f"/api/agents/{agent}/runs/thread-a/run-a/files/version", headers=_headers())
        assert response.status_code == 409, response.text
        assert threads["hash"] != threads["event_loop"]
        assert len(checks) == 2
        assert all(check["tenant_id"] == "tenant-a" and check["agent_id"] == agent
                   and check["thread_id"] == "thread-a" and check["run_id"] == "run-a"
                   for check in checks)


@pytest.mark.timeout(20)
def test_run_content_version_rejects_unsupported_backend_without_zip_fallback(tmp_path):
    host = make_host(tmp_path)
    host.settings = replace(host.settings, log_directory=str(tmp_path / "logs"))
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        assert _run(client, agent).status_code == 200

        class DownloadOnlyStorage:
            def prepare_download(self, *args, **kwargs):
                pytest.fail("Unsupported backends must not silently download a ZIP for versioning")

        previous = host.workspace_storage
        host.workspace_storage = DownloadOnlyStorage()
        try:
            response = client.get(f"/api/agents/{agent}/runs/thread-a/run-a/files/version", headers=_headers())
            assert response.status_code == 501, response.text
        finally:
            host.workspace_storage = previous


def test_cube_workspace_version_matches_local_bytes_without_downloading_zip(tmp_path, monkeypatch):
    import base64
    from types import SimpleNamespace
    from app.v2.server.storage import cube_workspaces
    from app.v2.server.storage.cube_workspaces import CubeWorkspaceStorage
    from sagents.v2.runtime.execution.sandbox.plugins.cube import cube_volume_name
    from tests.sagents.v2.cube_fakes import FakeCubeClient

    client = FakeCubeClient(tmp_path / "external-cube")
    host = SimpleNamespace(execution=SimpleNamespace(sandbox_provider=SimpleNamespace(client=client)))
    backend = CubeWorkspaceStorage(host)
    backend.import_files("tenant-a", "agent", "project", {
        "z.bin": base64.b64encode(b"\0\xffbinary").decode(),
        "nested/a.txt": base64.b64encode(b"hello").decode(),
        "user-uploads/skip": base64.b64encode(b"ignored").decode(),
        "nested/user-uploads/keep": base64.b64encode(b"needed").decode(),
    })
    root = client.root / cube_volume_name("tenant-a", "agent")
    expected = _version(root, exclude_root_entry="user-uploads")

    def forbidden_archive(*args, **kwargs):
        pytest.fail("Cube versioning must hash in the sandbox without a ZIP/download buffer")

    monkeypatch.setattr(cube_workspaces, "ZipFile", forbidden_archive)
    monkeypatch.setattr(cube_workspaces, "SpooledTemporaryFile", forbidden_archive)
    actual = backend.workspace_version("tenant-a", "agent", "project", exclude_root_entry="user-uploads")
    assert actual == expected
    assert actual["files"] == 3
    assert actual["bytes"] == 19
    page = root / "project" / "nested" / "a.txt"
    info = page.stat()
    os.utime(page, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    assert backend.workspace_version("tenant-a", "agent", "project", exclude_root_entry="user-uploads") == actual
    page.write_bytes(b"other")
    os.utime(page, ns=(info.st_atime_ns, info.st_mtime_ns))
    changed = backend.workspace_version("tenant-a", "agent", "project", exclude_root_entry="user-uploads")
    assert changed == _version(root, exclude_root_entry="user-uploads")
    assert changed["version"] != actual["version"]
    assert all(sandbox.killed for sandbox in client.created)
    with pytest.raises(FileNotFoundError):
        backend.workspace_version("tenant-b", "agent", "project")


def test_cube_workspace_version_preserves_quotas_and_symlink_boundary(tmp_path):
    from types import SimpleNamespace
    from app.v2.server.storage.cube_workspaces import CubeWorkspaceStorage
    from sagents.v2.runtime.execution.sandbox.plugins.cube import cube_volume_name
    from tests.sagents.v2.cube_fakes import FakeCubeClient

    client = FakeCubeClient(tmp_path / "external-cube")
    host = SimpleNamespace(execution=SimpleNamespace(sandbox_provider=SimpleNamespace(client=client)))
    backend = CubeWorkspaceStorage(host)
    backend.import_files("tenant-a", "agent", "project", {"index.html": "aGVsbG8="})
    root = client.root / cube_volume_name("tenant-a", "agent")
    baseline = backend.workspace_version("tenant-a", "agent", "project")
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"private")
    (root / "project" / "secret-link").symlink_to(outside)
    assert backend.workspace_version("tenant-a", "agent", "project") == baseline
    with pytest.raises(OSError):
        backend.workspace_version("tenant-a", "agent", "project/secret-link")
    for limits in ({"max_bytes": 4}, {"max_entries": 1}):
        with pytest.raises(OverflowError):
            backend.workspace_version("tenant-a", "agent", "project", **limits)
    assert all(sandbox.killed for sandbox in client.created)


@pytest.mark.parametrize("mutation", ["rewrite_previous", "add_file"])
def test_workspace_version_rejects_tree_changes_after_an_earlier_file_was_hashed(tmp_path, monkeypatch, mutation):
    project = tmp_path / "project"
    project.mkdir()
    earlier = project / "a.txt"
    earlier.write_bytes(b"first")
    (project / "z.txt").write_bytes(b"last")
    original_open = downloads.os.fdopen
    opened = []

    class MutatingReader:
        def __init__(self, fd, *args, **kwargs):
            self.inner = original_open(fd, *args, **kwargs)
            opened.append(self)
            self.ordinal = len(opened)
            self.mutated = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

        def read(self, size=-1):
            content = self.inner.read(size)
            if self.ordinal == 2 and not self.mutated:
                self.mutated = True
                if mutation == "add_file":
                    (project / "added.txt").write_bytes(b"new")
                else:
                    earlier.write_bytes(b"other")
            return content

    monkeypatch.setattr(downloads.os, "fdopen", MutatingReader)
    with pytest.raises(downloads.SnapshotChangedError):
        _version(tmp_path)


@pytest.mark.timeout(20)
def test_run_content_version_does_not_read_run_results_or_scan_run_history(tmp_path, monkeypatch):
    from copy import copy
    from app.v2.server.routers.deps import get_conversations

    host = make_host(tmp_path)
    host.settings = replace(host.settings, log_directory=str(tmp_path / "logs"))
    app = create_app(host)
    with TestClient(app) as client:
        setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        assert _run(client, agent).status_code == 200
        project = host.paths.workspace_path("tenant-a", agent) / "projects" / "site"
        project.mkdir(parents=True, exist_ok=True)
        (project / "index.html").write_bytes(b"hello")
        # Guard only the route's facade. Background Run completion keeps its
        # original access object and can finish independently of this request.
        service = copy(host.conversations)
        service.session_access = copy(service.session_access)

        async def forbidden_result_or_history(*args, **kwargs):
            raise AssertionError("Version authorization must use exact indexed Run metadata without final results/history")

        monkeypatch.setattr(service, "_result_with_native_run", forbidden_result_or_history)
        monkeypatch.setattr(service.session_access, "list_session_runs", forbidden_result_or_history)
        monkeypatch.setattr(service.session_access, "get_run_result", forbidden_result_or_history)
        app.dependency_overrides[get_conversations] = lambda: service
        response = client.get(f"/api/agents/{agent}/runs/thread-a/run-a/files/version", headers=_headers())
        assert response.status_code == 200, response.text
        assert response.json()["data"]["files"] == 1
        assert response.json()["data"]["bytes"] == 5


@pytest.mark.parametrize("backend", ["memory", "filesystem", "filesystem_reopened"])
async def test_latest_workspace_command_is_scoped_authorized_and_survives_restart(tmp_path, monkeypatch, backend):
    from sagents.v2.contracts.commands import StartRun
    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
    from sagents.v2.contracts.run_state import SessionConcurrencyMode
    from sagents.v2.runtime.session.access import AuthorizedSessionAccess
    from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
    from sagents.v2.runtime.session.state import SessionStoreCoordinator

    durable = backend != "memory"
    root = tmp_path / "session-state"
    store = FilesystemSessionStore(root) if durable else SessionStoreCoordinator()
    owner = RequestContext(actor=ActorRef(principal_id="owner", principal_type=PrincipalType.USER,
                                         tenant_id="tenant-a"))

    def command(key, session_id="project-session"):
        return StartRun(agent_id="agent", session_id=session_id, input=(),
                        resolved_spec_hash="sha256:version-test", idempotency_key=key,
                        session_concurrency_mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED)

    try:
        earlier = command("first")
        expected = command("latest")
        await store.create_run(earlier, owner)
        await store.create_run(expected, owner)
        await store.create_run(command("unrelated-newest", "other-session"), owner)
        if backend == "filesystem_reopened":
            await store.close()
            store = FilesystemSessionStore(root)

        async def forbidden_history(*args, **kwargs):
            raise AssertionError("Latest command lookup must not read complete Run history/results")

        def forbidden_snapshot(*args, **kwargs):
            raise AssertionError("Latest command lookup must not construct historical Run snapshots")

        monkeypatch.setattr(store, "list_session_runs", forbidden_history)
        monkeypatch.setattr(store, "get_run_result", forbidden_history)
        monkeypatch.setattr(store, "_run_snapshot", forbidden_snapshot)
        access = AuthorizedSessionAccess(store)
        assert await access.latest_session_start_command("project-session", owner) == expected
        for actor in (owner.actor.model_copy(update={"tenant_id": "tenant-b"}),
                      owner.actor.model_copy(update={"principal_type": PrincipalType.SERVICE})):
            wrong = owner.model_copy(update={"actor": actor})
            with pytest.raises(SageV2Error) as denied:
                await access.latest_session_start_command("project-session", wrong)
            assert denied.value.info.code == "session.actor_not_authorized"
        with pytest.raises(SageV2Error):
            await access.latest_session_start_command("missing-session", owner)
    finally:
        if durable:
            await store.close()


@pytest.mark.parametrize("backend", ["memory", "filesystem", "filesystem_reopened"])
async def test_latest_workspace_command_follows_admission_revision_when_clock_moves_backwards(tmp_path, monkeypatch, backend):
    from datetime import datetime, timedelta, timezone
    from sagents.v2.contracts.commands import StartRun
    from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
    from sagents.v2.contracts.run_state import SessionConcurrencyMode
    from sagents.v2.runtime.session.plugins.filesystem import FilesystemSessionStore
    from sagents.v2.runtime.session.state import SessionStoreCoordinator

    durable = backend != "memory"
    root = tmp_path / "session-state"
    now = [datetime(2026, 11, 8, 1, tzinfo=timezone.utc)]
    store = FilesystemSessionStore(root) if durable else SessionStoreCoordinator()
    monkeypatch.setattr(store, "_clock", lambda: now[0])
    owner = RequestContext(actor=ActorRef(principal_id="owner", principal_type=PrincipalType.USER,
                                         tenant_id="tenant-a"))

    def command(key):
        return StartRun(agent_id="agent", session_id="project-session", input=(),
                        resolved_spec_hash="sha256:version-test", idempotency_key=key,
                        session_concurrency_mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED)

    try:
        first = await store.create_run(command("first"), owner)
        now[0] -= timedelta(hours=1)
        expected = command("second-admission")
        second = await store.create_run(expected, owner)
        earlier = await store.get_run(first.handle.run_id)
        later = await store.get_run(second.handle.run_id)
        assert later.created_at < earlier.created_at
        assert later.accepted_session_revision > earlier.accepted_session_revision
        if backend == "filesystem_reopened":
            await store.close()
            store = FilesystemSessionStore(root)
        assert await store.latest_authorized_session_command("project-session", owner) == expected
    finally:
        if durable:
            await store.close()


@pytest.mark.timeout(20)
def test_version_route_rejects_old_run_even_when_new_admission_timestamp_is_earlier(tmp_path, monkeypatch):
    from datetime import timedelta

    host = make_host(tmp_path)
    host.settings = replace(host.settings, log_directory=str(tmp_path / "logs"))
    with TestClient(create_app(host)) as client:
        setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        assert _run(client, agent).status_code == 200
        project = host.paths.workspace_path("tenant-a", agent) / "projects" / "site"
        project.mkdir(parents=True, exist_ok=True)
        (project / "index.html").write_bytes(b"hello")
        store = host.conversations.session_access._session_store
        earlier = store._clock() - timedelta(hours=1)
        monkeypatch.setattr(store, "_clock", lambda: earlier)
        assert _run(client, agent, run_id="run-b").status_code == 200
        base = f"/api/agents/{agent}/runs/thread-a"
        stale = client.get(base + "/run-a/files/version", headers=_headers())
        assert stale.status_code == 409, stale.text
        current = client.get(base + "/run-b/files/version", headers=_headers())
        assert current.status_code == 200, current.text
        assert current.json()["data"]["files"] == 1


async def test_mysql_latest_command_query_orders_admission_before_clock_and_run_identity(monkeypatch):
    from contextlib import asynccontextmanager
    import json
    from unittest.mock import AsyncMock
    from sagents.v2.runtime.session.plugins.mysql.state import _MysqlSessionState
    from tests.sagents.v2.test_mysql_session_store_matrix import command, CONTEXT

    store = _MysqlSessionState("mysql://unused/test")
    cursor = AsyncMock()
    expected = command("latest-admission")
    cursor.fetchone.return_value = (json.dumps(expected.model_dump(mode="json")),)

    @asynccontextmanager
    async def selected_session(session_id, context):
        assert session_id == "project-session"
        assert context == CONTEXT
        yield cursor, None

    monkeypatch.setattr(store, "_history_query", selected_session)
    actual = await store.latest_authorized_session_command("project-session", CONTEXT)
    assert actual == expected
    statement, params = cursor.execute.await_args.args
    normalized = " ".join(statement.split()).lower()
    revisions = re.findall(r"(\w+) bigint path '\$\.accepted_session_revision'", normalized)
    assert len(revisions) == 2 and revisions[0] == revisions[1]
    assert f"order by {revisions[0]} desc, created_at desc, run_id desc limit 1" in normalized
    assert params == ("project-session", "project-session")
