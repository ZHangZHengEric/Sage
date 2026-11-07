"""Binary imports stay bounded, isolated and atomic on failure or retry."""
import asyncio
from io import BytesIO
import os
from threading import get_ident
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi import HTTPException

from app.v2.server.conversations.runs import RunService
from app.v2.server.routers import conversations
from app.v2.server.storage import external_workspaces as storage
from app.v2.server.storage.downloads import prepare_download
from app.v2.server.storage.paths import prepare_server_v2_storage


@pytest.mark.parametrize('path', ['', '../outside', '/tmp/outside', 'a//b', '.sage/key', 'a/../b'])
def test_binary_upload_rejects_invalid_paths(tmp_path, path):
    paths = prepare_server_v2_storage(tmp_path)
    with pytest.raises(ValueError):
        storage.import_workspace_file(paths, 'tenant', 'agent', path, BytesIO(b'data'))
    assert not paths.workspace_path('tenant', 'agent').exists()


@pytest.mark.parametrize('kind', ['parent-link', 'leaf-link', 'directory', 'fifo'])
def test_binary_upload_rejects_links_and_special_files(tmp_path, kind):
    paths = prepare_server_v2_storage(tmp_path)
    root = paths.workspace_dir('tenant', 'agent')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep').write_bytes(b'data')
    name = 'target'
    if kind == 'parent-link':
        (root / name).symlink_to(outside, target_is_directory=True)
        name += '/new'
    elif kind == 'leaf-link':
        (root / name).symlink_to(outside / 'keep')
    elif kind == 'directory':
        (root / name).mkdir()
    else:
        os.mkfifo(root / name)
    with pytest.raises(OSError):
        storage.import_workspace_file(paths, 'tenant', 'agent', name, BytesIO(b'data'))
    assert list(outside.iterdir()) == [outside / 'keep']
    assert (outside / 'keep').read_bytes() == b'data'
    assert not list(root.glob('.import-*'))


def test_binary_upload_quota_failure_cleans_up_and_retries_are_isolated(tmp_path, monkeypatch):
    paths = prepare_server_v2_storage(tmp_path)
    monkeypatch.setattr(storage, 'MAX_BINARY_BYTES', 4)
    for content in (b'', b'12345'):
        with pytest.raises(ValueError):
            storage.import_workspace_file(paths, 'tenant', 'agent', 'clip', BytesIO(content))
        assert not list(paths.workspace_path('tenant', 'agent').iterdir())
    for _ in range(2):
        storage.import_workspace_file(paths, 'tenant', 'agent', 'clip', BytesIO(b'1234'))
    with pytest.raises(FileExistsError):
        storage.import_workspace_file(paths, 'tenant', 'agent', 'clip', BytesIO(b'5678'))
    assert (paths.workspace_path('tenant', 'agent') / 'clip').read_bytes() == b'1234'
    assert not paths.workspace_path('other', 'agent').exists()
    assert not paths.workspace_path('tenant', 'other').exists()
    assert not list(paths.workspace_path('tenant', 'agent').glob('.import-*'))


def test_binary_retry_rejects_file_changed_during_comparison(tmp_path, monkeypatch):
    paths = prepare_server_v2_storage(tmp_path)
    target = paths.workspace_dir('tenant', 'agent') / 'clip'
    target.write_bytes(b'data')
    original = storage.os.fdopen

    class MutatingReader:
        def __init__(self, fd, mode):
            self.inner = original(fd, mode)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.inner.__exit__(*args)
        def __getattr__(self, name):
            return getattr(self.inner, name)
        def read(self, size):
            data = self.inner.read(size)
            with target.open('ab') as output:
                output.write(b'changed')
            return data

    monkeypatch.setattr(storage.os, 'fdopen',
                        lambda fd, mode: MutatingReader(fd, mode) if mode == 'rb' else original(fd, mode))
    with pytest.raises(FileExistsError):
        storage.import_workspace_file(paths, 'tenant', 'agent', 'clip', BytesIO(b'data'))
    assert not list(target.parent.glob('.import-*'))


def test_archive_excludes_only_root_entry_before_applying_limits(tmp_path):
    (tmp_path / 'uploads').mkdir()
    (tmp_path / 'uploads/large').write_bytes(b'x' * 100)
    (tmp_path / 'nested/uploads').mkdir(parents=True)
    (tmp_path / 'nested/uploads/keep').write_bytes(b'ok')
    with pytest.raises(OverflowError):
        prepare_download(tmp_path, '.', max_bytes=2)
    stream, _ = prepare_download(tmp_path, '.', max_bytes=2, exclude_root_entry='uploads')
    with stream, ZipFile(stream) as archive:
        assert archive.read('workspace/nested/uploads/keep') == b'ok'
        assert not any(name.startswith('workspace/uploads/') for name in archive.namelist())


@pytest.mark.parametrize('mode', ['success', 'oversize', 'disconnect'])
async def test_upload_spooling_uses_worker_and_closes_on_failure(tmp_path, monkeypatch, mode):
    paths = prepare_server_v2_storage(tmp_path)
    loop_thread = get_ident()
    writes = []
    spools = []
    original = conversations.SpooledTemporaryFile

    class Spool:
        def __init__(self, **kwargs):
            self.inner = original(**kwargs)
            spools.append(self.inner)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.inner.__exit__(*args)
        def __getattr__(self, name):
            return getattr(self.inner, name)
        def write(self, chunk):
            writes.append(get_ident())
            return self.inner.write(chunk)

    class Request:
        async def stream(self):
            yield b'data'
            if mode == 'oversize':
                yield b'!'
            elif mode == 'disconnect':
                raise asyncio.CancelledError

    monkeypatch.setattr(conversations, 'SpooledTemporaryFile', Spool)
    monkeypatch.setattr(conversations, 'MAX_BINARY_BYTES', 4)
    service = SimpleNamespace(runs=RunService(application=None, session_access=None, execution=None))
    args = (Request(), SimpleNamespace(tenant_id='tenant', agent_id='agent'),
            SimpleNamespace(paths=paths), service)
    if mode == 'success':
        await conversations.put_workspace_file(*args, path='clip')
        assert (paths.workspace_path('tenant', 'agent') / 'clip').read_bytes() == b'data'
    else:
        with pytest.raises(HTTPException if mode == 'oversize' else asyncio.CancelledError) as error:
            await conversations.put_workspace_file(*args, path='clip')
        if mode == 'oversize':
            assert error.value.status_code == 413
        assert not paths.workspace_path('tenant', 'agent').exists()
    assert writes and all(thread != loop_thread for thread in writes)
    assert all(stream.closed for stream in spools)
