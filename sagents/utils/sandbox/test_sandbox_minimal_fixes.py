import os

from sagents.utils.sandbox import SandboxConfig, SandboxProviderFactory, SandboxType
from sagents.utils.sandbox.providers.local.filesystem import SandboxFileSystem
from sagents.utils.sandbox.providers.passthrough.passthrough import PassthroughSandboxProvider


def test_local_filesystem_extra_mount_mapping(tmp_path):
    workspace = tmp_path / "workspace"
    extra = tmp_path / "extra"
    workspace.mkdir()
    extra.mkdir()

    fs = SandboxFileSystem(str(workspace), "/sage-workspace")
    fs.add_mapping("/external", str(extra))

    assert fs.to_host_path("/sage-workspace/a.txt") == os.path.join(str(workspace), "a.txt")
    assert fs.to_host_path("/external/b.txt") == os.path.join(str(extra), "b.txt")
    assert fs.to_virtual_path(os.path.join(str(extra), "b.txt")) == "/external/b.txt"


def test_passthrough_workspace_path_is_virtual(tmp_path):
    provider = PassthroughSandboxProvider(
        sandbox_id="sid",
        workspace=str(tmp_path),
        virtual_workspace="/sage-workspace",
    )

    assert provider.workspace_path == "/sage-workspace"
    assert provider.host_workspace_path == str(tmp_path)
    assert provider.to_host_path("/sage-workspace/file.txt") == os.path.join(str(tmp_path), "file.txt")
    assert provider.to_virtual_path(os.path.join(str(tmp_path), "file.txt")) == "/sage-workspace/file.txt"


def test_factory_can_create_builtin_remote_provider_without_manual_registration():
    config = SandboxConfig(
        sandbox_id="sid",
        mode=SandboxType.REMOTE,
        remote_provider="opensandbox",
        remote_server_url="http://example.com",
    )

    provider = SandboxProviderFactory.create(config)
    assert provider.__class__.__name__ == "OpenSandboxProvider"


def test_sandbox_config_prefers_platform_isolation_defaults():
    config = SandboxConfig(sandbox_id="sid")

    assert config.linux_isolation_mode == "bwrap"
    assert config.macos_isolation_mode == "seatbelt"
