"""Session plugin owns attachment authorization, persistence, and lifecycle."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.session.state import SessionStoreCoordinator

import base64
from copy import deepcopy
import json

import pytest

from sagents.v2.contracts.commands import StartRun, InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode
from sagents.v2.runtime.session import EphemeralSessionStore, FilesystemSessionStore

CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="owner", principal_type=PrincipalType.USER, tenant_id="tenant"
    )
)


async def content(value=b"image snapshot"):
    yield value


async def create(
    store, key, *, session_id=None, mode=SessionConcurrencyMode.SERIAL, context=CONTEXT
):
    return await store.create_run(
        StartRun(
            session_id=session_id,
            agent_id="agent",
            input=(InputItem(role="user", content=(TextBlock(text="inspect"),)),),
            session_concurrency_mode=mode,
            resolved_spec_hash="sha256:spec",
            idempotency_key=key,
        ),
        context,
    )


async def cancel(store, created, *, context=CONTEXT):
    run = await store.get_run(created.handle.run_id)
    await store.commit_run(
        run_id=run.run_id,
        expected_revision=run.revision,
        expected_states={run.state},
        new_state=RunState.CANCELLED,
        drafts=(),
        context=context,
        idempotency_key="cancel:" + run.run_id,
    )


@pytest.fixture(params=["memory", "filesystem"])
async def store(request, tmp_path):
    instance = (
        EphemeralSessionStore()
        if request.param == "memory"
        else FilesystemSessionStore(tmp_path / "store")
    )
    yield instance
    await instance.close()


@pytest.mark.asyncio
async def test_session_attachment_is_immutable_and_authorized(store):
    created = await create(store, "source")
    sid = created.handle.session_id
    first = await store.put_attachment(
        sid,
        artifact_id="image",
        media_type="image/jpeg",
        content=content(),
        context=CONTEXT,
    )
    assert (
        await store.put_attachment(
            sid,
            artifact_id="image",
            media_type="image/jpeg",
            content=content(),
            context=CONTEXT,
        )
        == first
    )
    with pytest.raises(SageV2Error) as conflict:
        await store.put_attachment(
            sid,
            artifact_id="image",
            media_type="image/jpeg",
            content=content(b"different"),
            context=CONTEXT,
        )
    assert conflict.value.info.code == "artifact.id_conflict"
    intruder = CONTEXT.model_copy(
        update={"actor": CONTEXT.actor.model_copy(update={"principal_id": "other"})}
    )
    with pytest.raises(SageV2Error):
        await store.get_attachment(sid, "image", context=intruder)
    _, data = await store.get_attachment(sid, "image", context=CONTEXT)
    assert b"".join([chunk async for chunk in data]) == b"image snapshot"


@pytest.mark.asyncio
async def test_copy_reference_survives_source_deletion_and_target_is_reclaimed(store):
    source, target = await create(store, "source"), await create(store, "target")
    a, b = source.handle.session_id, target.handle.session_id
    await store.put_attachment(
        a,
        artifact_id="image",
        media_type="image/jpeg",
        content=content(),
        context=CONTEXT,
    )
    await store.copy_attachment(a, b, "image", context=CONTEXT)
    await cancel(store, source)
    await store.delete_session(a)
    _, data = await store.get_attachment(b, "image", context=CONTEXT)
    assert b"".join([chunk async for chunk in data]) == b"image snapshot"
    await cancel(store, target)
    await store.delete_session(b)
    assert not store._attachment_payloads
    if isinstance(store, FilesystemSessionStore):
        assert not list(store.sessions_root.rglob("*.artifact"))


@pytest.mark.asyncio
async def test_fork_inherits_attachments_and_cascade_deletion_cleans_both(store):
    parent = await create(store, "parent")
    sid = parent.handle.session_id
    await store.put_attachment(
        sid,
        artifact_id="image",
        media_type="image/jpeg",
        content=content(),
        context=CONTEXT,
    )
    await cancel(store, parent)
    child = await create(
        store, "child", session_id=sid, mode=SessionConcurrencyMode.FORK
    )
    _, data = await store.get_attachment(
        child.handle.session_id, "image", context=CONTEXT
    )
    assert b"".join([chunk async for chunk in data]) == b"image snapshot"
    await cancel(store, child)
    await store.delete_session(sid)
    assert not store._attachment_payloads
    if isinstance(store, FilesystemSessionStore):
        assert not list(store.sessions_root.rglob("*.artifact"))


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "filesystem"])
async def test_portable_backup_restores_session_and_binary_attachments(
    store, tmp_path, backend
):
    created = await create(store, "backup")
    sid = created.handle.session_id
    await store.put_attachment(
        sid,
        artifact_id="image",
        media_type="image/jpeg",
        content=content(),
        context=CONTEXT,
    )
    await cancel(store, created)
    backup = json.loads(
        json.dumps(await store.export_session_backup(sid, context=CONTEXT))
    )
    assert "content_base64" not in json.dumps(store._dump_session_state_locked(sid))
    target = (
        EphemeralSessionStore()
        if backend == "memory"
        else FilesystemSessionStore(tmp_path / "restore")
    )
    try:
        await target.restore_session_backup(backup, context=CONTEXT)
        _, data = await target.get_attachment(sid, "image", context=CONTEXT)
        assert b"".join([chunk async for chunk in data]) == b"image snapshot"
        if backend == "filesystem":
            await target.close()
            target = FilesystemSessionStore(tmp_path / "restore")
            _, data = await target.get_attachment(sid, "image", context=CONTEXT)
            assert b"".join([chunk async for chunk in data]) == b"image snapshot"
    finally:
        await target.close()


@pytest.mark.asyncio
async def test_corrupt_backup_is_rejected_before_destination_changes(store):
    created = await create(store, "corrupt")
    sid = created.handle.session_id
    await store.put_attachment(
        sid,
        artifact_id="image",
        media_type="image/jpeg",
        content=content(),
        context=CONTEXT,
    )
    backup = deepcopy(await store.export_session_backup(sid, context=CONTEXT))
    backup["attachments"][0]["content_base64"] = base64.b64encode(b"wrong").decode()
    target = EphemeralSessionStore()
    with pytest.raises(SageV2Error):
        await target.restore_session_backup(backup, context=CONTEXT)
    assert not target._sessions and not target._attachment_payloads


@pytest.mark.asyncio
async def test_attachment_commit_failure_rolls_back_manifest_and_can_retry(
    store, monkeypatch
):
    created = await create(store, "rollback")
    sid = created.handle.session_id
    before = await store.get_session(sid)
    # Enable the coordinator rollback guard for injected memory I/O failure.
    store._persistence_can_fail = True
    original_commit = store._commit_storage_locked

    async def fail(session_id):
        raise OSError("injected storage failure")

    monkeypatch.setattr(store, "_commit_storage_locked", fail)
    with pytest.raises(OSError, match="injected storage failure"):
        await store.put_attachment(
            sid,
            artifact_id="image",
            media_type="image/jpeg",
            content=content(),
            context=CONTEXT,
        )
    assert await store.get_session(sid) == before
    assert "image" not in store._sessions[sid].attachments
    assert (sid, "image") not in store._attachment_payloads
    monkeypatch.setattr(store, "_commit_storage_locked", original_commit)
    await store.put_attachment(
        sid,
        artifact_id="image",
        media_type="image/jpeg",
        content=content(),
        context=CONTEXT,
    )
    _, data = await store.get_attachment(sid, "image", context=CONTEXT)
    assert b"".join([chunk async for chunk in data]) == b"image snapshot"


@pytest.mark.asyncio
async def test_backup_cannot_overwrite_another_session_run_identity(store):
    original = await create(store, "original")
    other = await create(store, "other")
    backup = await store.export_session_backup(
        original.handle.session_id, context=CONTEXT
    )
    backup["state"] = json.loads(
        json.dumps(backup["state"]).replace(original.handle.run_id, other.handle.run_id)
    )
    target = EphemeralSessionStore()
    await target.load_state(store._dump_session_state_locked(other.handle.session_id))
    before = await target.export_state()
    with pytest.raises(SageV2Error) as caught:
        await target.restore_session_backup(backup, context=CONTEXT)
    assert caught.value.info.code == "session.backup_conflict"
    assert await target.export_state() == before


@pytest.mark.asyncio
async def test_custom_session_plugin_without_attachments_fails_with_clear_error():
    from sagents.v2.runtime.artifact import SessionArtifactStore

    with pytest.raises(SageV2Error) as caught:
        await SessionArtifactStore(object(), "run").get("image")
    assert caught.value.info.code == "session.attachments_unsupported"


@pytest.mark.asyncio
async def test_tree_backup_restores_fork_and_is_resumable_after_partial_storage_failure(
    store, tmp_path, monkeypatch
):
    parent = await create(store, "tree-parent")
    sid = parent.handle.session_id
    await store.put_attachment(
        sid,
        artifact_id="image",
        media_type="image/jpeg",
        content=content(),
        context=CONTEXT,
    )
    await cancel(store, parent)
    child = await create(
        store, "tree-child", session_id=sid, mode=SessionConcurrencyMode.FORK
    )
    await cancel(store, child)
    backup = await store.export_session_backup(sid, context=CONTEXT)
    assert len(backup["descendants"]) == 1
    target = FilesystemSessionStore(tmp_path / "tree-restore")
    original = target._commit_storage_locked

    async def interrupted(owner):
        if owner == child.handle.session_id:
            raise OSError("injected child write failure")
        await original(owner)

    monkeypatch.setattr(target, "_commit_storage_locked", interrupted)
    with pytest.raises(OSError, match="injected child write failure"):
        await target.restore_session_backup(backup, context=CONTEXT)
    assert (await target.get_session(sid)).session_id == sid
    await target.close()
    target = FilesystemSessionStore(tmp_path / "tree-restore")
    await target.restore_session_backup(backup, context=CONTEXT)
    # Restoring again must also be safe after a process restart.
    await target.restore_session_backup(backup, context=CONTEXT)
    children = await target.list_descendant_sessions(sid)
    assert [row.session_id for row in children] == [child.handle.session_id]
    for owner in (sid, child.handle.session_id):
        _, data = await target.get_attachment(owner, "image", context=CONTEXT)
        assert b"".join([chunk async for chunk in data]) == b"image snapshot"
    await target.delete_session(sid)
    assert not list(target.sessions_root.rglob("*.artifact"))
    await target.close()


@pytest.mark.asyncio
async def test_corrupt_descendant_backup_does_not_restore_parent(store):
    parent = await create(store, "invalid-tree")
    sid = parent.handle.session_id
    await store.put_attachment(
        sid,
        artifact_id="image",
        media_type="image/jpeg",
        content=content(),
        context=CONTEXT,
    )
    await cancel(store, parent)
    await create(
        store, "invalid-tree-child", session_id=sid, mode=SessionConcurrencyMode.FORK
    )
    backup = await store.export_session_backup(sid, context=CONTEXT)
    backup["descendants"][0]["attachments"] = []
    target = EphemeralSessionStore()
    with pytest.raises(SageV2Error):
        await target.restore_session_backup(backup, context=CONTEXT)
    assert not target._sessions


@pytest.mark.asyncio
async def test_read_only_history_contains_attachment_bytes_without_changing_source(
    tmp_path,
):
    from sagents.v2.runtime.session.plugins.filesystem import read_session_history

    root = tmp_path / "historical"
    source = FilesystemSessionStore(root)
    created = await create(source, "history")
    sid = created.handle.session_id
    await source.put_attachment(
        sid,
        artifact_id="image",
        media_type="image/jpeg",
        content=content(),
        context=CONTEXT,
    )
    await source.close()
    files = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    view = await read_session_history(root, sid, CONTEXT)
    _, data = await cast('SessionStoreCoordinator', view).get_attachment(sid, "image", context=CONTEXT)
    assert b"".join([chunk async for chunk in data]) == b"image snapshot"
    assert {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    } == files


@pytest.mark.asyncio
@pytest.mark.parametrize('fail_commit', [False, True])
async def test_sql_attachment_blob_and_manifest_share_transaction(fail_commit, monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock
    from sagents.v2.runtime.session.plugins.mysql import _MysqlSessionState
    source = EphemeralSessionStore()
    created = await create(source, 'sql')
    sid = created.handle.session_id
    store = _MysqlSessionState('mysql://unused/unused')
    await store.load_state(await source.export_state())
    pending, durable, statements = ({}, {}, [])

    class Connection:
        rowcount = 1

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def cursor(self):
            return self

        async def execute(self, query, *values):
            statements.append(query)
            params = values[0]
            if 'INSERT INTO' in query and 'attachments' in query:
                assert 'UNHEX(%s)' in query
                assert isinstance(params[2], str)
                pending[params[1]] = bytes.fromhex(params[2])
            return 'UPDATE 1'


        async def commit(self):
            assert 'image' in store._sessions[sid].attachments
            assert pending == {'image': b'image snapshot'}
            if fail_commit:
                raise OSError('transaction commit failed')
            durable.update(pending)
            pending.clear()

        async def rollback(self):
            pending.clear()

    connection = Connection()

    @asynccontextmanager
    async def writer():
        yield connection
    monkeypatch.setattr(store, '_ensure_ready', AsyncMock())
    monkeypatch.setattr(store, '_ensure_session_loaded', AsyncMock())
    monkeypatch.setattr(store, '_writer_connection', writer)
    monkeypatch.setattr(store, '_persist_events', AsyncMock(return_value={}))
    monkeypatch.setattr(store, '_reload_session_from_storage_locked', AsyncMock())
    monkeypatch.setattr(store, '_sync_locations', AsyncMock())
    monkeypatch.setattr(store, '_sync_start_idempotency', AsyncMock())
    if fail_commit:
        with pytest.raises(OSError, match='transaction commit failed'):
            await store.put_attachment(sid, artifact_id='image', media_type='image/jpeg', content=content(), context=CONTEXT)
        assert durable == {} and pending == {}
        assert 'image' not in store._sessions[sid].attachments
    else:
        await store.put_attachment(sid, artifact_id='image', media_type='image/jpeg', content=content(), context=CONTEXT)
        assert durable == {'image': b'image snapshot'}
        assert not store._attachment_payloads
        assert any(('sessions' in query and 'INSERT INTO' in query for query in statements))


@pytest.mark.asyncio
async def test_live_sql_attachment_restart_copy_backup_and_delete():
    import os
    import uuid
    from sagents.v2.runtime.session.plugins.mysql import MysqlSessionStore
    dsn = os.environ.get("SAGE_V2_TEST_MYSQL_DSN", '').strip()
    if not dsn:
        pytest.skip('Live database DSN is not configured')
    prefix = 'attachments_' + uuid.uuid4().hex[:12]

    def opened():
        return MysqlSessionStore(dsn, table_prefix=prefix)
    source = opened()
    try:
        a, b = (await create(source, 'live-a'), await create(source, 'live-b'))
        await source.put_attachment(a.handle.session_id, artifact_id='image', media_type='image/jpeg', content=content(), context=CONTEXT)
        await source.copy_attachment(a.handle.session_id, b.handle.session_id, 'image', context=CONTEXT)
        await cancel(source, a)
        await cancel(source, b)
        await source.close()
        source = opened()
        await source.delete_session(a.handle.session_id)
        _, stream = await source.get_attachment(b.handle.session_id, 'image', context=CONTEXT)
        assert b''.join([chunk async for chunk in stream]) == b'image snapshot'
        backup = await source.export_session_backup(b.handle.session_id, context=CONTEXT)
        await source.delete_session(b.handle.session_id)
        await source.restore_session_backup(backup, context=CONTEXT)
        await source.close()
        source = opened()
        _, stream = await source.get_attachment(b.handle.session_id, 'image', context=CONTEXT)
        assert b''.join([chunk async for chunk in stream]) == b'image snapshot'
        await source.delete_session(b.handle.session_id)
    finally:
        await source.close()


def _plan_hosted_video_upload(config, prefix, videos, required, resources):
    from sagents.v2.runtime.artifact.video_storage import _VideoCopy

    return None, {uri: _VideoCopy(prefix + "clip.mp4", mime, b"clip") for uri, mime in videos.items()}


@pytest.mark.asyncio
async def test_hosted_video_deletion_is_scoped_durable_and_retryable(tmp_path, monkeypatch):
    import sys

    from sagents.v2.runtime.artifact import SessionArtifactStore
    from sagents.v2.runtime.artifact import video_storage
    from sagents.v2.runtime.session.access import AuthorizedSessionAccess

    objects = {}
    reject_delete = True

    def upload(client, config, copies, required):
        for copy in copies.values():
            objects[copy.key] = {"version-1", "delete-marker"}
        return {
            uri: "https://bucket.example.test/" + copy.key + "?signature=test"
            for uri, copy in copies.items()
        }

    class Bucket:
        def close(self):
            pass

        def list_object_versions(self, *, Bucket, Prefix, MaxKeys):
            keys = [key for key in objects if key.startswith(Prefix)]
            return {
                "Versions": [
                    {"Key": key, "VersionId": version}
                    for key in keys for version in objects[key] if version != "delete-marker"
                ],
                "DeleteMarkers": [
                    {"Key": key, "VersionId": "delete-marker"}
                    for key in keys if "delete-marker" in objects[key]
                ],
            }

        def list_objects_v2(self, *, Bucket, Prefix, MaxKeys):
            return {"Contents": [{"Key": key} for key in objects if key.startswith(Prefix)]}

        def delete_objects(self, *, Bucket, Delete):
            if reject_delete:
                return {"Errors": [{"Code": "AccessDenied"}]}
            for item in Delete["Objects"]:
                key = item["Key"]
                objects[key].remove(item["VersionId"])
                if not objects[key]:
                    del objects[key]
            return {}

    monkeypatch.setitem(sys.modules, "boto3", object())
    monkeypatch.setattr(video_storage, "_prepare_upload", _plan_hosted_video_upload)
    monkeypatch.setattr(video_storage, "_upload_and_sign", upload)
    monkeypatch.setattr(video_storage, "_client", lambda config: Bucket())
    config = video_storage.S3VideoStorageConfig(bucket="private-videos")
    uri = "data:video/mp4;base64,Y2xpcA=="

    other_tenant = CONTEXT.model_copy(
        update={"actor": CONTEXT.actor.model_copy(update={"tenant_id": "other"})}
    )
    root = tmp_path / "video-sessions"
    original = FilesystemSessionStore(root)
    try:
        source = await create(original, "source-video")
        other = await create(original, "other-video", context=other_tenant)
        access = AuthorizedSessionAccess(original)

        async def host_video(created):
            run_id = created.handle.run_id
            with video_storage.bind_video_copy_owner(
                run_id, SessionArtifactStore(original, run_id),
                lambda upload: original.run_with_hosted_video_copy(run_id, upload),
            ):
                signed = await video_storage.publish_videos(config, {uri: "video/mp4"}, required={uri})
            return signed[uri].partition("?")[0].removeprefix("https://bucket.example.test/")

        source_key = await host_video(source)
        other_key = await host_video(other)
        assert source_key != other_key
        with pytest.raises(SageV2Error) as active:
            await access.delete_session(source.handle.session_id, CONTEXT)
        assert active.value.info.code == "session.active_run"
        assert set(objects) == {source_key, other_key}
        await cancel(original, source)
        await cancel(original, other, context=other_tenant)
        backup = await original.export_session_backup(source.handle.session_id, context=CONTEXT)
        assert backup["attachments"] == []
        assert backup["state"]["sessions"][0]["attachments"] == {}
    finally:
        await original.close()

    reopened = FilesystemSessionStore(root)
    try:
        access = AuthorizedSessionAccess(reopened)
        with pytest.raises(SageV2Error) as failure:
            await access.delete_session(source.handle.session_id, CONTEXT, require_derived_cleanup=True)
        assert failure.value.info.code == "session.video_cleanup_failed"
        assert failure.value.info.retryable
        assert (await reopened.get_session(source.handle.session_id)).session_id == source.handle.session_id
        assert set(objects) == {source_key, other_key}

        reject_delete = False
        await access.delete_session(source.handle.session_id, CONTEXT, require_derived_cleanup=True)
        with pytest.raises(SageV2Error) as missing:
            await reopened.get_session(source.handle.session_id)
        assert missing.value.info.code == "session.not_found"
        assert set(objects) == {other_key}
        with pytest.raises(SageV2Error):
            await access.delete_session(other.handle.session_id, CONTEXT)
        assert set(objects) == {other_key}
        await access.delete_session(other.handle.session_id, other_tenant)
        assert objects == {}
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_hosted_video_upload_requires_a_durable_receipt(monkeypatch):
    import sys

    from sagents.v2.runtime.artifact import video_storage

    class UnavailableStore:
        async def put(self, **kwargs):
            raise OSError("storage unavailable")

    def upload(*args):
        pytest.fail("S3 must not be called before its cleanup receipt is durable")

    monkeypatch.setitem(sys.modules, "boto3", object())
    monkeypatch.setattr(video_storage, "_prepare_upload", _plan_hosted_video_upload)
    monkeypatch.setattr(video_storage, "_upload_and_sign", upload)
    config = video_storage.S3VideoStorageConfig(bucket="private-videos")
    uri = "data:video/mp4;base64,Y2xpcA=="
    with pytest.raises(SageV2Error, match="Session-owned"):
        await video_storage.publish_videos(config, {uri: "video/mp4"}, required={uri})
    with video_storage.bind_video_copy_owner("run", UnavailableStore(), lambda upload: upload()):
        with pytest.raises(SageV2Error, match="record ownership"):
            await video_storage.publish_videos(config, {uri: "video/mp4"}, required={uri})


@pytest.mark.asyncio
async def test_cancelling_hosted_video_request_waits_for_the_s3_write(monkeypatch):
    import asyncio
    import sys
    import threading

    from sagents.v2.runtime.artifact import SessionArtifactStore, video_storage

    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    unblock = threading.Event()

    def upload(*args):
        loop.call_soon_threadsafe(started.set)
        assert unblock.wait(timeout=5)
        return {}

    monkeypatch.setitem(sys.modules, "boto3", object())
    monkeypatch.setattr(video_storage, "_prepare_upload", _plan_hosted_video_upload)
    monkeypatch.setattr(video_storage, "_upload_and_sign", upload)
    config = video_storage.S3VideoStorageConfig(bucket="private-videos")
    store = EphemeralSessionStore()
    created = await create(store, "video-cancel")
    run_id = created.handle.run_id
    try:
        with video_storage.bind_video_copy_owner(
            run_id, SessionArtifactStore(store, run_id),
            lambda operation: store.run_with_hosted_video_copy(run_id, operation),
        ):
            task = asyncio.create_task(
                video_storage.publish_videos(config, {"data:video/mp4;base64,Y2xpcA==": "video/mp4"})
            )
            try:
                await asyncio.wait_for(started.wait(), timeout=3)
                cancel_run = asyncio.create_task(cancel(store, created))
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
                assert not cancel_run.done()
            finally:
                unblock.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            await cancel_run
        assert (await store.get_run(run_id)).state == RunState.CANCELLED
    finally:
        await store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["credentials", "list-denied", "put-timeout"])
async def test_video_upload_registers_cleanup_only_after_read_only_checks(failure, monkeypatch):
    pytest.importorskip("boto3")
    from botocore.exceptions import ClientError, NoCredentialsError, ReadTimeoutError

    from sagents.v2.runtime.artifact import SessionArtifactStore, video_storage
    from sagents.v2.runtime.session.access import AuthorizedSessionAccess

    objects = set()
    client_calls = 0
    put_calls = 0
    deny_cleanup = False

    def http_error(code, status, operation):
        return ClientError({
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }, operation)

    class Bucket:
        def close(self):
            pass

        def head_object(self, **kwargs):
            raise http_error("NotFound", 404, "HeadObject")

        def list_object_versions(self, *, Prefix, **kwargs):
            if failure == "list-denied" or deny_cleanup:
                raise http_error("AccessDenied", 403, "ListObjectVersions")
            return {"Versions": [
                {"Key": key, "VersionId": "null"} for key in objects if key.startswith(Prefix)
            ]}

        def list_objects_v2(self, *, Prefix, **kwargs):
            return {"Contents": [{"Key": key} for key in objects if key.startswith(Prefix)]}

        def put_object(self, *, Key, **kwargs):
            nonlocal put_calls
            put_calls += 1
            objects.add(Key)
            raise ReadTimeoutError(endpoint_url="https://fixture.invalid")

        def delete_objects(self, *, Delete, **kwargs):
            for item in Delete["Objects"]:
                objects.remove(item["Key"])
            return {}

    def client(config):
        nonlocal client_calls
        client_calls += 1
        if failure == "credentials":
            raise NoCredentialsError()
        return Bucket()

    monkeypatch.setattr(video_storage, "_client", client)
    store = EphemeralSessionStore()
    try:
        run = await create(store, "video-preflight")
        run_id, session_id = run.handle.run_id, run.handle.session_id
        config = video_storage.S3VideoStorageConfig(bucket="test-video")
        uri = "data:video/mp4;base64,Y2xpcA=="
        with video_storage.bind_video_copy_owner(
            run_id, SessionArtifactStore(store, run_id),
            lambda operation: store.run_with_hosted_video_copy(run_id, operation),
        ):
            with pytest.raises(SageV2Error) as failed:
                await video_storage.publish_videos(config, {uri: "video/mp4"}, required={uri})
        assert failed.value.info.code == "model.video_storage_failed"
        await cancel(store, run)
        access = AuthorizedSessionAccess(store)
        if failure == "put-timeout":
            assert put_calls == 1 and objects
            deny_cleanup = True
            with pytest.raises(SageV2Error) as failed:
                await access.delete_session(session_id, CONTEXT)
            assert failed.value.info.code == "session.video_cleanup_failed"
            assert (await store.get_session(session_id)).session_id == session_id
            deny_cleanup = False
        else:
            assert put_calls == 0
        await access.delete_session(session_id, CONTEXT)
        assert not objects
        assert client_calls == (3 if failure == "put-timeout" else 1)
        with pytest.raises(SageV2Error) as missing:
            await store.get_session(session_id)
        assert missing.value.info.code == "session.not_found"
    finally:
        await store.close()
