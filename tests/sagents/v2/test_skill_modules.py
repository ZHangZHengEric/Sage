"""Management plugins and the three stable-path workspace policies."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.execution.sandbox.contracts import FileSystemMode

from sagents.v2.package.manifest.runtime import CapabilitySelection

import asyncio
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from pydantic import ValidationError

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    InMemorySandboxProvider,
    LocalWorkspaceSandboxProvider,
    NetworkPolicy,
    ProcessPolicy,
    ResolvedSandboxSpec,
    ResourceLimits,
    SandboxGrantIssuer,
)
from sagents.v2.skill import (
    InMemorySkillActivationRepository,
    SkillBundle,
    SkillDescriptor,
    SkillLoader,
)
from sagents.v2.skill.bundles import files_digest
from sagents.v2.skill.plugins.repository import (
    MemorySkillRepository,
    SqliteSkillRepository,
)
from sagents.v2.skill.plugins.workspace import (
    AutoSyncSkillWorkspace,
    FixedCopySkillWorkspace,
    ReadonlyMountSkillWorkspace,
)
from tests.sagents.v2.test_standard_execution_configuration import CONTEXT


def bundle(body="v1", *, files=None):
    values = files or {
        "SKILL.md": body.encode(),
        "references/guide.md": b"Reference content",
    }
    return SkillBundle(
        descriptor=SkillDescriptor(name="demo", description="Demo", source_id="test"),
        files=values,
        content_hash=files_digest(values),
    )


def loader(source, workspace):
    return SkillLoader(
        catalog=source,
        source=source,
        workspace=workspace,
        activations=InMemorySkillActivationRepository(),
    )


@pytest_asyncio.fixture
async def targets(tmp_path):
    items, handles = [], []
    issuer = SandboxGrantIssuer()
    local = LocalWorkspaceSandboxProvider(issuer.verification_key)
    memory = InMemorySandboxProvider(issuer.verification_key)

    async def make(
        kind=AutoSyncSkillWorkspace, *, run_id="run1", disk=False, operations=None
    ):
        spec = ResolvedSandboxSpec(
            spec_hash="sha256:test",
            policy_hash="sha256:policy",
            architecture="native" if disk else "portable",
            filesystem_mode=cast('FileSystemMode', "workspace"),
            filesystem=FileSystemPolicy(
                allowed_operations=operations or frozenset(FileOperation)
            ),
            process=ProcessPolicy(enabled=False),
            network=NetworkPolicy(),
            resources=ResourceLimits(require_hard_limits=False),
            metadata={"host_workspace": str(tmp_path)} if disk else {},
        )
        handle = await (local if disk else memory).provision(
            spec, CONTEXT, run_id=run_id
        )
        handles.append(handle)
        item = kind(handle, issuer)
        items.append(item)
        return item

    yield make
    for item in items:
        await item.close()
    for handle in handles:
        await handle.destroy()


@pytest.mark.asyncio
async def test_default_filesystem_and_stable_reference_path(tmp_path, targets):
    from sagents.v2.composition.defaults import default_runtime
    from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider

    for name in ("skill.management", "skill.provider"):
        selected = default_runtime(tmp_path).capabilities[name]
        assert cast(CapabilitySelection, selected).plugin == "sage.skill.filesystem"
        assert cast(CapabilitySelection, selected).config == {"roots": [str(tmp_path / "skills")]}
    root = tmp_path / "source/demo"
    (root / "references").mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo\n---\nRead references/guide.md"
    )
    (root / "references/guide.md").write_text("Reference content")
    target = await targets()
    active = loader(FilesystemSkillProvider((root.parent,)), target)
    value = await active.load("demo", run_id="run1")
    assert value.workspace_path == "/workspace/skills/demo"
    assert (
        await target._read(value.workspace_path + "/references/guide.md", "run1")
        == b"Reference content"
    )
    assert "<workspace>/workspace/skills/demo</workspace>" in active._context_content(
        value
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_repository_versions_run_pins_and_publish_conflicts(tmp_path, persistent):
    manager = (
        SqliteSkillRepository(tmp_path / "skills.db")
        if persistent
        else MemorySkillRepository()
    )
    try:
        first = await manager.publish(bundle())
        await manager.list_skills(run_id="old")
        second = await manager.publish(bundle("v2"), expected_version=first.version)
        assert first.version != second.version
        assert (await manager.fetch("demo", run_id="old")).files["SKILL.md"] == b"v1"
        assert (await manager.fetch("demo", run_id="new")).files["SKILL.md"] == b"v2"
        with pytest.raises(SageV2Error) as caught:
            await manager.publish(bundle("v3"), expected_version=first.version)
        assert caught.value.info.code == "skill.publish_conflict"
        assert len(await manager.list_versions("demo")) == 2
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_repository_restart_and_independent_writers(tmp_path):
    path = tmp_path / "skills.db"
    first, second = SqliteSkillRepository(path), SqliteSkillRepository(path)
    try:
        base = await first.publish(bundle())
        await first.list_skills(run_id="old")
        results = await asyncio.gather(
            first.publish(bundle("left"), expected_version=base.version),
            second.publish(bundle("right"), expected_version=base.version),
            return_exceptions=True,
        )
        assert sum(isinstance(item, SageV2Error) for item in results) == 1
    finally:
        await first.close()
        await second.close()
    reopened = SqliteSkillRepository(path)
    try:
        assert (await reopened.fetch("demo", run_id="old")).files["SKILL.md"] == b"v1"
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_manager_changes_replace_and_delete_without_old_package_archives(targets):
    target = await targets()
    path = await target.materialize(
        bundle(), run_id="run1", destination="/workspace/skills/demo"
    )
    new = bundle(files={"SKILL.md": b"v2", "new.txt": b"new"})
    assert await target.materialize(new, run_id="run1", destination=path) == path
    actual, _ = await target._tree(path, "run1")
    assert actual == new.files
    catalog, _ = await target._tree("/workspace/skills/.catalog", "run1")
    assert set(catalog) == {"demo/state.json"}
    assert (await target._state(path, "run1"))["content_hash"] == new.content_hash


@pytest.mark.asyncio
async def test_agent_changes_are_archived_then_manager_version_is_restored(targets):
    target = await targets()
    path = await target.materialize(
        bundle(), run_id="run1", destination="/workspace/skills/demo"
    )
    await target._write(path + "/SKILL.md", b"Agent edited", "run1")
    await target._delete(path + "/references/guide.md", "run1")
    await target._write(path + "/agent.txt", b"Agent added", "run1")
    await target.materialize(bundle("manager-v2"), run_id="run1", destination=path)
    current, _ = await target._tree(path, "run1")
    assert current == bundle("manager-v2").files
    archived, _ = await target._tree(
        "/workspace/skills/.catalog/demo/agent-edits", "run1"
    )
    assert sum(name.endswith("record.json") for name in archived) == 1
    assert any(
        name.endswith("files/SKILL.md") and value == b"Agent edited"
        for name, value in archived.items()
    )
    assert any(
        name.endswith("files/agent.txt") and value == b"Agent added"
        for name, value in archived.items()
    )
    record = json.loads(
        next(value for name, value in archived.items() if name.endswith("record.json"))
    )
    assert record["reason"] == "agent_changes"
    assert "references/guide.md" not in record["files"]


@pytest.mark.asyncio
async def test_repeated_load_archives_edits_even_when_source_version_is_unchanged(
    targets,
):
    manager = MemorySkillRepository()
    try:
        await manager.publish(bundle())
        target = await targets()
        active = loader(manager, target)
        first = await active.load("demo", run_id="run1")
        await target._write(first.workspace_path + "/SKILL.md", b"local edit", "run1")
        again = await active.load("demo", run_id="run1")
        assert again.instructions == "v1"
        assert await target._read(again.workspace_path + "/SKILL.md", "run1") == b"v1"
        files, _ = await target._tree(
            "/workspace/skills/.catalog/demo/agent-edits", "run1"
        )
        assert any(value == b"local edit" for value in files.values())
        assert not any("/references/" in name for name in files)
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_untracked_local_contents_are_preserved_conservatively(targets):
    target = await targets()
    await target._write("/workspace/skills/demo/SKILL.md", b"untracked", "run1")
    await target.materialize(
        bundle(), run_id="run1", destination="/workspace/skills/demo"
    )
    archive, _ = await target._tree(
        "/workspace/skills/.catalog/demo/agent-edits", "run1"
    )
    assert any(value == b"untracked" for value in archive.values())


@pytest.mark.asyncio
async def test_fixed_copy_keeps_initial_version_and_agent_edits(targets):
    manager = MemorySkillRepository()
    try:
        await manager.publish(bundle())
        target = await targets(FixedCopySkillWorkspace)
        active = loader(manager, target)
        first = await active.load("demo", run_id="run1")
        await manager.publish(bundle("v2"))
        # New catalog selection sees v2, but this stable directory retains v1.
        copied = await active.load("demo", run_id="run1")
        assert copied.instructions == "v1"
        await target._write(first.workspace_path + "/SKILL.md", b"Customized", "run1")
        assert (await active.load("demo", run_id="run1")).instructions == "Customized"
        catalog, _ = await target._tree("/workspace/skills/.catalog", "run1")
        assert set(catalog) == {"demo/state.json"}
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_real_shared_workspaces_allow_same_version_and_block_live_replacement(
    targets,
):
    first, second = await targets(disk=True), await targets(disk=True, run_id="run2")
    path = "/workspace/skills/demo"
    await asyncio.gather(
        first.materialize(bundle(), run_id="run1", destination=path),
        second.materialize(bundle(), run_id="run2", destination=path),
    )
    with pytest.raises(SageV2Error) as caught:
        await second.materialize(bundle("v2"), run_id="run2", destination=path)
    assert caught.value.info.code == "skill.workspace_in_use"
    assert await first._read(path + "/SKILL.md", "run1") == b"v1"
    await first.close()
    await second.materialize(bundle("v2"), run_id="run2", destination=path)
    assert await second._read(path + "/SKILL.md", "run2") == b"v2"


@pytest.mark.asyncio
async def test_independent_sandboxes_do_not_share_workspace_leases(targets):
    first, second = await targets(), await targets(run_id="run2")
    await first.materialize(
        bundle(), run_id="run1", destination="/workspace/skills/demo"
    )
    await second.materialize(
        bundle("v2"), run_id="run2", destination="/workspace/skills/demo"
    )


@pytest.mark.asyncio
async def test_file_directory_transitions_remove_obsolete_directories(targets):
    target = await targets(disk=True)
    path = "/workspace/skills/demo"
    for version in (
        bundle(files={"SKILL.md": b"1", "a/b/c.txt": b"nested"}),
        bundle(files={"SKILL.md": b"2", "a": b"file"}),
        bundle(files={"SKILL.md": b"3", "a/d.txt": b"nested-again"}),
    ):
        await target.materialize(version, run_id="run1", destination=path)
        assert (await target._tree(path, "run1"))[0] == version.files
    assert set((await target._tree("/workspace/skills/.catalog", "run1"))[0]) == {
        "demo/state.json"
    }


@pytest.mark.asyncio
async def test_interrupted_sync_reconciles_manager_bytes_without_false_agent_archive(
    targets,
):
    target = await targets()
    path = "/workspace/skills/demo"
    await target.materialize(bundle(), run_id="run1", destination=path)
    original = target._write
    failed = False

    async def interrupt(name, content, run_id):
        nonlocal failed
        if name == path + "/added.txt" and not failed:
            failed = True
            raise OSError("interrupted")
        await original(name, content, run_id)

    target._write = interrupt
    updated = bundle(files={"SKILL.md": b"v2", "added.txt": b"new"})
    with pytest.raises(OSError):
        await target.materialize(updated, run_id="run1", destination=path)
    target._write = original
    await target.materialize(updated, run_id="run1", destination=path)
    assert (await target._tree(path, "run1"))[0] == updated.files
    assert set((await target._tree("/workspace/skills/.catalog", "run1"))[0]) == {
        "demo/state.json"
    }


@pytest.mark.asyncio
async def test_archive_failure_does_not_replace_agent_files(targets):
    target = await targets()
    path = "/workspace/skills/demo"
    await target.materialize(bundle(), run_id="run1", destination=path)
    await target._write(path + "/SKILL.md", b"Agent edits", "run1")
    original = target._write

    async def fail(name, content, run_id):
        if "/agent-edits/" in name:
            raise OSError("archive unavailable")
        await original(name, content, run_id)

    target._write = fail
    with pytest.raises(OSError):
        await target.materialize(bundle("v2"), run_id="run1", destination=path)
    assert await target._read(path + "/SKILL.md", "run1") == b"Agent edits"


@pytest.mark.asyncio
async def test_readonly_mount_requires_real_backend_and_passes_signed_request(targets):
    target = await targets(ReadonlyMountSkillWorkspace)
    with pytest.raises(SageV2Error) as caught:
        await target.materialize(
            bundle(), run_id="run1", destination="/workspace/skills/demo"
        )
    assert caught.value.info.code == "skill.readonly_mount_unsupported"
    assert (await target._tree("/workspace/skills", "run1"))[0] == {}
    calls = []

    async def mount(value, **kwargs):
        calls.append(kwargs)
        assert kwargs["grant"].operation_digest == kwargs["intent"].digest()
        assert kwargs["intent"].metadata["files_hash"] == files_digest(value.files)
        return kwargs["destination"]

    target.sandbox.skill_mounts = SimpleNamespace(mount_readonly=mount)
    assert (
        await target.materialize(
            bundle(), run_id="run1", destination="/workspace/skills/demo"
        )
        == "/workspace/skills/demo"
    )
    assert len(calls) == 1
    assert (await target._tree("/workspace/skills", "run1"))[0] == {}


@pytest.mark.asyncio
async def test_file_policy_is_not_bypassed(targets):
    target = await targets(
        operations=frozenset({FileOperation.READ, FileOperation.LIST})
    )
    with pytest.raises(SageV2Error) as caught:
        await target.materialize(
            bundle(), run_id="run1", destination="/workspace/skills/demo"
        )
    assert caught.value.info.code == "sandbox.permission_denied"


def test_grouped_config_has_auto_sync_default_and_canonical_serialization():
    assert "skills" not in RuntimeConfig().model_dump(mode="json")
    value = RuntimeConfig.model_validate(
        {"skills": {"management": {"plugin": "sage.skill.repository.memory"}}}
    )
    assert (
        cast(CapabilitySelection, value.capabilities["skill.workspace"]).plugin == "sage.skill.workspace.auto-sync"
    )
    assert RuntimeConfig.model_validate(value.model_dump()) == value
    with pytest.raises(ValidationError, match="both configure"):
        RuntimeConfig.model_validate(
            {"skills": {}, "capabilities": {"skill.workspace": {"plugin": "other"}}}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["auto-sync", "fixed-copy", "default"])
@pytest.mark.parametrize("repository", ["sqlite", "memory"])
async def test_standard_build_load_run_selects_real_workspace_policy(
    tmp_path, strategy, repository
):
    from sagents.v2.package.manifest import SageManifest
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.sagents.v2.test_standard_execution_configuration import (
        build,
        response,
        run,
        runtime,
    )

    settings = RuntimeConfig.model_validate(
        {
            **runtime(tmp_path).model_dump(mode="python"),
            "skills": {
                "management": {
                    "plugin": f"sage.skill.repository.{repository}",
                    "config": {"path": str(tmp_path / "skills.db")}
                    if repository == "sqlite"
                    else {},
                },
                "usage": {
                    "workspace": {
                        "plugin": f"sage.skill.workspace.{strategy if strategy != 'default' else 'auto-sync'}",
                        "scope": "run",
                    }
                },
            },
        }
    )
    if strategy == "default":
        settings = settings.model_copy(
            update={
                "capabilities": {
                    key: value
                    for key, value in settings.capabilities.items()
                    if key != "skill.workspace"
                }
            }
        )
    model = ScriptedModelProvider((response(), response()))
    app = await build(tmp_path, model, config=settings)
    try:
        manager = app.service("skill.management")
        await manager.publish(bundle())
        package = SageManifest.model_validate(
            {
                "schema_version": "sage/v2",
                "kind": "agent-package",
                "metadata": {
                    "id": "test.skill-modules",
                    "version": "1",
                    "name": "Skills",
                },
                "agents": {
                    "root": {
                        "name": "Root",
                        "models": {"primary": "primary"},
                        "instructions": {"inline": "Work"},
                        "skills": ["demo"],
                        "preload_skills": ["demo"],
                    }
                },
                "entrypoint": {"agent": "root"},
            }
        )
        agent = await app.load_agent(package)
        first, _ = await run(app, agent, "first")
        assert first.state.value == "completed", first
        assert "v1" in str(model.requests[0].messages)
        assert "/.catalog/" not in str(model.requests[0].messages)
        await manager.publish(bundle("v2"))
        second, _ = await run(app, agent, "second")
        assert second.state.value == "completed", second
        expected = "v1" if strategy == "fixed-copy" else "v2"
        assert expected in str(model.requests[1].messages)
        assert (tmp_path / "workspace/skills/demo/SKILL.md").read_text() == expected
        assert not list((tmp_path / "workspace/skills/.catalog").rglob("SKILL.md"))
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_auto_sync_reads_latest_manager_publication_within_same_run(targets):
    manager = MemorySkillRepository()
    try:
        await manager.publish(bundle())
        target = await targets()
        active = loader(manager, target)
        await active.load("demo", run_id="run1")
        await manager.publish(bundle("v2"))
        assert (await manager.fetch("demo", run_id="run1")).files["SKILL.md"] == b"v1"
        current = await active.load("demo", run_id="run1")
        assert current.instructions == "v2"
        assert (await target._tree(current.workspace_path, "run1"))[0] == bundle(
            "v2"
        ).files
        assert set((await target._tree("/workspace/skills/.catalog", "run1"))[0]) == {
            "demo/state.json"
        }
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_auto_sync_refuses_source_and_working_directory_overlap(
    tmp_path, targets
):
    from sagents.v2.skill.plugins.filesystem import FilesystemSkillProvider

    root = tmp_path / "skills/demo"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: demo\ndescription: Demo\n---\nOriginal")
    source = FilesystemSkillProvider((root.parent,))
    target = await targets(disk=True)
    with pytest.raises(SageV2Error) as caught:
        await loader(source, target).load("demo", run_id="run1")
    assert caught.value.info.code == "skill.source_overlaps_workspace"
    assert (root / "SKILL.md").read_text().endswith("Original")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [AutoSyncSkillWorkspace, FixedCopySkillWorkspace])
async def test_skill_restore_normalizes_instructions_but_preserves_bundle_hash(targets, kind):
    manager = MemorySkillRepository()
    try:
        original = bundle("\n  Read references/guide.md\n")
        await manager.publish(original)
        target = await targets(kind)
        active = loader(manager, target)
        loaded = await active.load("demo", run_id="run1")
        assert loaded.instructions == "Read references/guide.md"
        checkpoint = json.loads(json.dumps(await active.snapshot_run("run1")))

        # A newly composed loader must recover after a deferred model retry
        # even though the source SKILL.md has a conventional trailing newline.
        restored = loader(manager, target)
        await restored.restore_run("run1", checkpoint)
        assert await restored.snapshot_run("run1") == checkpoint
        assert await target._read("/workspace/skills/demo/SKILL.md", "run1") == original.files["SKILL.md"]

        # Whitespace-only source changes still invalidate the exact hash.
        if kind is AutoSyncSkillWorkspace:
            await manager.publish(bundle("\n  Read references/guide.md\n\n"))
            with pytest.raises(SageV2Error) as caught:
                await restored.restore_run("run1", checkpoint)
            assert caught.value.info.code == "skill.restore_version_changed"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_auto_sync_recovery_does_not_reinstall_old_manager_version(targets):
    manager = MemorySkillRepository()
    try:
        await manager.publish(bundle())
        target = await targets()
        active = loader(manager, target)
        await active.load("demo", run_id="run1")
        checkpoint = await active.snapshot_run("run1")
        await manager.publish(bundle("v2"))
        await active.load("demo", run_id="run1")
        with pytest.raises(SageV2Error) as caught:
            await active.restore_run("run1", checkpoint)
        assert caught.value.info.code == "skill.restore_version_changed"
        assert await target._read("/workspace/skills/demo/SKILL.md", "run1") == b"v2"
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_manager_pushed_current_contents_are_not_misarchived_as_agent_edits(
    targets,
):
    target = await targets()
    path = "/workspace/skills/demo"
    await target.materialize(bundle(), run_id="run1", destination=path)
    # A manager's explicit workspace sync can arrive before its tracking state.
    await target._write(path + "/SKILL.md", b"v2", "run1")
    await target.materialize(bundle("v2"), run_id="run1", destination=path)
    assert set((await target._tree("/workspace/skills/.catalog", "run1"))[0]) == {
        "demo/state.json"
    }
