from __future__ import annotations

from typing import cast

import base64
import subprocess
from types import SimpleNamespace

import pytest

from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.execution.sandbox import (
    FileOperation, FileSystemPolicy, LifecyclePolicy, OperationIntent, ResolvedSandboxSpec,
    ResourceLimits, SandboxGrantIssuer,
)
from sagents.v2.runtime.execution.sandbox.contracts import (
    SandboxDurability, SandboxReleaseDisposition,
)
from sagents.v2.runtime.execution.sandbox.plugins.cube import (
    CubeVolumeClient, CubeVolumeSandboxProvider, cube_volume_name,
)
from sagents.v2.runtime.execution.sandbox.plugins.cube.files import cube_file_call


class LocalCommandSandbox:
    def __init__(self):
        self.commands = self

    def run(self, command, *, cwd, timeout):
        result = subprocess.run(command, shell=True, cwd=cwd, timeout=timeout,
                                text=True, capture_output=True, check=False)
        return SimpleNamespace(exit_code=result.returncode, stdout=result.stdout,
                               stderr=result.stderr)


def test_cube_file_bridge_preserves_binary_data_and_rejects_symlinks(tmp_path):
    sandbox = LocalCommandSandbox()
    content = b"\x00\xff\n\x80"
    root = str(tmp_path)
    cube_file_call(sandbox, "write", "nested/data.bin", root=root,
                   data=base64.b64encode(content).decode(), max_bytes=1024,
                   overwrite=False)
    response = cube_file_call(sandbox, "read", "nested/data.bin",
                              root=root, max_bytes=1024)
    assert base64.b64decode(response["data"]) == content
    assert cube_file_call(sandbox, "list", "nested", root=root)[0]["path"] == "nested/data.bin"
    (tmp_path / "nested" / "link").symlink_to(tmp_path / "nested" / "data.bin")
    with pytest.raises(PermissionError):
        cube_file_call(sandbox, "read", "nested/link", root=root, max_bytes=1024)
    with pytest.raises(PermissionError):
        cube_file_call(sandbox, "stat", "../nested/data.bin", root=root)


class FakeCubeSandbox:
    sandbox_id = "cube_1"

    def __init__(self):
        self.killed = False

    def kill(self):
        self.killed = True


class FakeClient:
    def __init__(self):
        self.names = []
        self.sandbox = FakeCubeSandbox()

    def create_sandbox(self, name, *, timeout=None):
        self.names.append(name)
        return self.sandbox


@pytest.mark.asyncio
async def test_cube_provider_provisions_scoped_volume_and_verifies_grants(monkeypatch):
    issuer = SandboxGrantIssuer(b"test-key-32-bytes-minimum-length!!")
    client = FakeClient()
    provider = CubeVolumeSandboxProvider(issuer.verification_key, client=cast('CubeVolumeClient | None', client))
    context = RequestContext(actor=ActorRef(
        principal_id="user_1", principal_type=PrincipalType.USER, tenant_id="user_1"
    ))
    name = cube_volume_name("user_1", "agent_1")
    spec = ResolvedSandboxSpec(
        spec_hash="sha256:cube-spec", policy_hash="sha256:cube-policy",
        architecture="native", resources=ResourceLimits(require_hard_limits=False),
        filesystem=FileSystemPolicy(
            allowed_operations=frozenset({FileOperation.READ, FileOperation.CREATE}),
            max_file_bytes=1024,
        ),
        lifecycle=LifecyclePolicy(
            durability=SandboxDurability.DURABLE_EXTERNAL,
            safe_pause_behavior=SandboxReleaseDisposition.TERMINATE,
        ),
        metadata={"cube_agent_id": "agent_1", "cube_volume_name": name},
    )
    handle = await provider.provision(spec, context, run_id="run_1")
    assert client.names == [name]
    forged = spec.model_copy(update={"metadata": {
        "cube_agent_id": "agent_1",
        "cube_volume_name": cube_volume_name("other_user", "agent_1"),
    }})
    with pytest.raises(PermissionError):
        await provider.provision(forged, context, run_id="run_2")
    assert client.names == [name]
    assert name != cube_volume_name("user_1", "agent_2")
    assert name != cube_volume_name("user_2", "agent_1")
    assert name != cube_volume_name("user_1", "agent_1", private_run_id="child_1")

    def remote_file(_sandbox, operation, path, **kwargs):
        if operation == "stat":
            raise FileNotFoundError(path)
        if operation == "write":
            return {"path": "note.txt", "size": 4, "is_file": True, "is_directory": False}
        raise AssertionError(operation)

    monkeypatch.setattr("sagents.v2.runtime.execution.sandbox.plugins.cube.cube_file_call", remote_file)
    intent = OperationIntent(operation="create", run_id="run_1", tool_call_id="tool_1",
                             sandbox_id=handle.ref.sandbox_id, path="note.txt")
    grant = issuer.issue(ref=handle.ref, intent=intent,
                         allowed_operations=frozenset({"create"}))
    stat = await handle.filesystem.write_bytes("note.txt", b"note", intent=intent, grant=grant)
    assert stat.path == "/workspace/note.txt"
    with pytest.raises(PermissionError):
        await handle.filesystem.write_bytes("note.txt", b"note", intent=intent, grant=grant)
    await handle.destroy()
    await provider.purge_terminated(handle.ref)
    assert client.sandbox.killed
    assert client.names == [name]


def test_cube_client_creates_missing_volume_and_mounts_it_without_egress():
    class Missing(Exception):
        pass

    class Volume:
        current = None

        @classmethod
        def connect(cls, name, *, config):
            if cls.current is None:
                raise Missing(name)
            return cls.current

        @classmethod
        def create(cls, name, *, driver, config):
            cls.current = SimpleNamespace(volume_id=name)
            return cls.current

    calls = []

    class Sandbox:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs)
            return FakeCubeSandbox()

    client = object.__new__(CubeVolumeClient)
    client.config = object()
    client.sandbox_class = Sandbox
    client.volume_class = Volume
    client.volume_not_found = Missing
    client.template_id = "python-template"
    client.volume_driver = "cos"
    name = cube_volume_name("user", "agent")
    client.create_sandbox(name, timeout=120)
    assert calls[0]["volume_mounts"] == {"/workspace": Volume.current}
    assert calls[0]["network"] == {"deny_out": ["0.0.0.0/0"]}
    assert calls[0]["allow_internet_access"] is False
    assert calls[0]["timeout"] == 120
