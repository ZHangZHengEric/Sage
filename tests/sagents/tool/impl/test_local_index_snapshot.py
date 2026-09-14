import os
from dataclasses import asdict

import pytest
from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider
from sagents.utils.sandbox.providers.local import local as local_module
from sagents.tool.impl.memory_index import MemoryIndex


class SeparateCalls(LocalSandboxProvider):
    """Retains the original generic stat-then-list scan path."""


@pytest.mark.asyncio
async def test_directory_snapshot_matches_incremental_index_and_search(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for i in range(8):
        folder = workspace / f"dir{i}"
        folder.mkdir()
        (folder / "note.md").write_text(f"UniqueTermOmega item {i}")
    providers = [
        cls(
            sandbox_id="index",
            sandbox_agent_workspace=str(workspace),
            volume_mounts=[VolumeMount(str(workspace), str(workspace))],
            macos_isolation_mode="subprocess",
            linux_isolation_mode="subprocess",
        )
        for cls in [SeparateCalls, LocalSandboxProvider]
    ]
    indexes = [
        MemoryIndex(p, str(workspace), str(tmp_path / f"index{i}.pkl"))
        for i, p in enumerate(providers)
    ]
    calls = []
    original = local_module.diagnostic_to_thread

    async def counted(name, fn, *args, **kwargs):
        calls.append(name)
        return await original(name, fn, *args, **kwargs)

    monkeypatch.setattr(local_module, "diagnostic_to_thread", counted)

    async def compare():
        stats = [await idx.update_index() for idx in indexes]
        for key in ["added", "updated", "removed", "unchanged", "errors"]:
            assert stats[0][key] == stats[1][key]
        assert indexes[0]._file_metadata == indexes[1]._file_metadata
        assert [asdict(r) for r in indexes[0].search("UniqueTermOmega", top_k=20)] == [
            asdict(r) for r in indexes[1].search("UniqueTermOmega", top_k=20)
        ]

    await compare()
    assert calls.count("local.get_mtime") == 9
    assert calls.count("local.list_directory") == 9
    assert calls.count("local.directory_snapshot") == 9
    calls.clear()
    await compare()  # unchanged directories are not listed
    assert "local.list_directory" not in calls
    (workspace / "new.md").write_text("UniqueTermOmega newly added")
    os.utime(workspace, (workspace.stat().st_atime, workspace.stat().st_mtime + 2))
    await compare()
    (workspace / "new.md").unlink()
    os.utime(workspace, (workspace.stat().st_atime, workspace.stat().st_mtime + 4))
    await compare()


@pytest.mark.asyncio
async def test_snapshot_defers_listing_error_and_does_not_access_escape(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = LocalSandboxProvider(
        sandbox_id="snapshot-error",
        sandbox_agent_workspace=str(workspace),
        volume_mounts=[VolumeMount(str(workspace), str(workspace))],
        macos_isolation_mode="subprocess",
        linux_isolation_mode="subprocess",
    )

    def fail(*args):
        raise OSError("listing failed")

    monkeypatch.setattr(provider, "_list_directory_sync", fail)
    mtime, entries, error = await provider.get_directory_snapshot(str(workspace), 0)
    assert mtime == workspace.stat().st_mtime and entries is None
    assert isinstance(error, OSError)
    assert await provider.get_directory_snapshot(str(workspace), mtime) == (
        mtime,
        None,
        None,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    assert await provider.get_directory_snapshot(str(workspace / "escape"), 0) == (
        0,
        None,
        None,
    )


@pytest.mark.asyncio
async def test_index_splitting_shares_existing_fts_worker_and_matches_search(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from sagents.tool.impl import memory_index as module
    loop_thread = threading.get_ident()
    content = 'uniqueOmega first\n' + '中文 repeated line\n' * 1000
    provider = SimpleNamespace(read_file=AsyncMock(return_value=content))
    idx = MemoryIndex(sandbox=provider, workspace_path='/workspace', index_path=str(tmp_path/'new.pkl'))
    baseline = MemoryIndex(sandbox=None, workspace_path='/workspace', index_path=str(tmp_path/'old.pkl'))
    calls, split_threads = [], []
    delegate = module.diagnostic_to_thread
    split = idx._split_into_chunks
    async def counted(name, fn, *args, **kwargs):
        calls.append(name)
        return await delegate(name, fn, *args, **kwargs)
    def observed(text):
        split_threads.append(threading.get_ident())
        return split(text)
    monkeypatch.setattr(module, 'diagnostic_to_thread', counted)
    monkeypatch.setattr(idx, '_split_into_chunks', observed)
    entry = SimpleNamespace(path='/workspace/file.md', modified_time=1.0, size=len(content.encode()))
    stats = dict(added=0,updated=0,unchanged=0,errors=0)
    await idx._process_file(entry, stats)
    assert stats == dict(added=1,updated=0,unchanged=0,errors=0)
    assert calls == ['index.fts_sync']
    assert split_threads and all(t != loop_thread for t in split_threads)
    baseline._replace_file_documents(entry.path, content, entry.modified_time, entry.size)
    baseline._sync_file_to_fts(entry.path)
    assert idx._file_metadata == baseline._file_metadata
    assert [asdict(r) for r in idx.search('uniqueOmega')] == [asdict(r) for r in baseline.search('uniqueOmega')]
    calls.clear()
    await idx._process_file(entry, stats)
    assert calls == [] and stats['unchanged'] == 1
