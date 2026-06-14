import asyncio

import pytest

from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.sandbox.providers.local.local import LocalSandboxProvider


def test_local_provider_rejects_file_write_outside_workspace(tmp_path):
    workspace = tmp_path / "agents" / "user_1" / "agent_1"
    workspace.mkdir(parents=True)
    outside = tmp_path / "agents" / "user_1" / "reports" / "out.md"

    provider = LocalSandboxProvider(
        sandbox_id="test",
        sandbox_agent_workspace=str(workspace),
        volume_mounts=[VolumeMount(str(workspace), str(workspace))],
        macos_isolation_mode="subprocess",
        linux_isolation_mode="subprocess",
    )

    with pytest.raises(PermissionError, match="outside sandbox workspace"):
        asyncio.run(provider.write_file(str(outside), "nope"))

    assert not outside.exists()


def test_local_provider_allows_workspace_and_explicit_mount(tmp_path):
    workspace = tmp_path / "agents" / "user_1" / "agent_1"
    external = tmp_path / "external"
    workspace.mkdir(parents=True)
    external.mkdir()

    provider = LocalSandboxProvider(
        sandbox_id="test",
        sandbox_agent_workspace=str(workspace),
        volume_mounts=[
            VolumeMount(str(workspace), str(workspace)),
            VolumeMount(str(external), str(external)),
        ],
        macos_isolation_mode="subprocess",
        linux_isolation_mode="subprocess",
    )

    workspace_file = workspace / "data" / "ok.md"
    external_file = external / "ok.md"

    asyncio.run(provider.write_file(str(workspace_file), "workspace"))
    asyncio.run(provider.write_file(str(external_file), "external"))

    assert workspace_file.read_text() == "workspace"
    assert external_file.read_text() == "external"


def test_local_provider_allows_dynamic_mount_after_initialize(tmp_path):
    workspace = tmp_path / "workspace"
    external = tmp_path / "external"
    workspace.mkdir()
    external.mkdir()

    provider = LocalSandboxProvider(
        sandbox_id="test",
        sandbox_agent_workspace=str(workspace),
        volume_mounts=[VolumeMount(str(workspace), str(workspace))],
        macos_isolation_mode="subprocess",
        linux_isolation_mode="subprocess",
    )

    asyncio.run(provider.initialize())
    provider.add_mount(str(external), str(external))

    mounted_file = external / "ok.md"
    asyncio.run(provider.write_file(str(mounted_file), "mounted"))

    assert mounted_file.read_text() == "mounted"


def test_local_provider_rejects_write_to_read_only_mount(tmp_path):
    workspace = tmp_path / "workspace"
    readonly = workspace / "readonly"
    workspace.mkdir()
    readonly.mkdir()

    provider = LocalSandboxProvider(
        sandbox_id="test",
        sandbox_agent_workspace=str(workspace),
        volume_mounts=[
            VolumeMount(str(workspace), str(workspace)),
            VolumeMount(str(readonly), str(readonly), read_only=True),
        ],
        macos_isolation_mode="subprocess",
        linux_isolation_mode="subprocess",
    )

    with pytest.raises(PermissionError, match="read-only"):
        asyncio.run(provider.write_file(str(readonly / "blocked.md"), "blocked"))
