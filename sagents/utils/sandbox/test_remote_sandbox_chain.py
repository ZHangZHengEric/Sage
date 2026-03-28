import os

from sagents.utils.sandbox import SandboxConfig, SandboxProviderFactory, SandboxType
from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.sandbox.providers.remote.opensandbox import OpenSandboxProvider


def test_volume_mount_remote_compat_aliases(tmp_path):
    mount = VolumeMount(host_path=str(tmp_path), mount_path="data", read_only=True)

    assert mount.host_path == os.path.abspath(str(tmp_path))
    assert mount.mount_path == "/data"
    assert mount.sandbox_path == "/data"
    assert mount.read_only is True

    mount.sandbox_path = "/other"
    assert mount.mount_path == "/other"


def test_factory_creates_opensandbox_provider_with_virtual_workspace(tmp_path):
    extra = tmp_path / "extra"
    extra.mkdir()

    config = SandboxConfig(
        sandbox_id="sid",
        mode=SandboxType.REMOTE,
        sandbox_agent_workspace="/custom-workspace",
        volume_mounts=[VolumeMount(host_path=str(extra), mount_path="/data", read_only=True)],
        remote_provider="opensandbox",
        remote_server_url="http://example.com",
    )

    provider = SandboxProviderFactory.create(config)

    assert isinstance(provider, OpenSandboxProvider)
    assert provider.workspace_path == "/custom-workspace"
    assert provider.volume_mounts[0].sandbox_path == "/data"
    assert provider.volume_mounts[0].read_only is True


def test_remote_provider_path_conversion_supports_workspace_and_mounts(tmp_path):
    workspace = tmp_path / "workspace"
    extra = tmp_path / "extra"
    workspace.mkdir()
    extra.mkdir()

    provider = OpenSandboxProvider(
        sandbox_id="sid",
        server_url="http://example.com",
        workspace_mount=str(workspace),
        mount_paths=[VolumeMount(host_path=str(extra), mount_path="/mnt/data")],
        virtual_workspace="/custom-workspace",
    )

    assert provider.to_host_path("/custom-workspace/file.txt") == os.path.join(str(workspace), "file.txt")
    assert provider.to_host_path("/mnt/data/item.txt") == os.path.join(str(extra), "item.txt")
    assert provider.to_virtual_path(os.path.join(str(workspace), "file.txt")) == "/custom-workspace/file.txt"
    assert provider.to_virtual_path(os.path.join(str(extra), "item.txt")) == "/mnt/data/item.txt"
