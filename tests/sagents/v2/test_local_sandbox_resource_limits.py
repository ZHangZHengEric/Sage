from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    InMemorySandboxProvider,
    LocalWorkspaceSandboxProvider,
    OperationIntent,
    ProcessPolicy,
    ProcessRequest,
    ResolvedSandboxSpec,
    ResourceLimits,
    SandboxGrantIssuer,
    SandboxState,
)
from sagents.v2.runtime.execution.sandbox.local_support.resources import (
    LocalResourceBoundary,
)

CONTEXT = RequestContext(
    actor=ActorRef(principal_id="test", principal_type=PrincipalType.USER)
)


def spec(root, **limits):
    return ResolvedSandboxSpec(
        spec_hash="sha256:resource-test",
        policy_hash="sha256:resource-policy",
        architecture="native",
        metadata={"host_workspace": str(root)},
        resources=ResourceLimits(require_hard_limits=False, **limits),
        filesystem=FileSystemPolicy(allowed_operations=frozenset(FileOperation)),
        process=ProcessPolicy(
            enabled=True,
            allow_shell=True,
            allowed_executables=("python", "bash"),
            allowed_env_names=("EXAMPLE",),
            max_wall_time_seconds=3,
        ),
    )


async def local(root, **limits):
    issuer = SandboxGrantIssuer()
    provider = LocalWorkspaceSandboxProvider(issuer.verification_key)
    handle = await provider.provision(
        spec(root, **limits), CONTEXT, run_id="resource-run"
    )
    return provider, issuer, handle


def authorize(issuer, handle, request):
    intent = OperationIntent(
        operation="process.run",
        run_id=handle.ref.owner_run_id,
        tool_call_id="resource-call",
        sandbox_id=handle.ref.sandbox_id,
        path=request.cwd,
        executable=request.argv[0],
        argv=request.argv,
        metadata={"process_request_digest": request.digest()},
    )
    return dict(
        intent=intent,
        grant=issuer.issue(
            ref=handle.ref, intent=intent, allowed_operations=frozenset({"process.run"})
        ),
    )


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan"), True])
def test_invalid_resource_values_are_rejected(value):
    with pytest.raises(ValidationError):
        ResourceLimits(memory_mb=value)


@pytest.mark.asyncio
async def test_simulation_does_not_claim_default_hard_limits(tmp_path):
    issuer = SandboxGrantIssuer()
    provider = InMemorySandboxProvider(issuer.verification_key)
    resolved = spec(tmp_path).model_copy(update={"resources": ResourceLimits()})
    with pytest.raises(SageV2Error, match="Required sandbox limits"):
        await provider.provision(resolved, CONTEXT, run_id="refuse")
    assert not provider._rows


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="macOS admission")
async def test_macos_refuses_hard_limits_before_creating_resources(tmp_path):
    provider = LocalWorkspaceSandboxProvider(SandboxGrantIssuer().verification_key)
    resolved = spec(tmp_path).model_copy(update={"resources": ResourceLimits()})
    with pytest.raises(SageV2Error, match="Required sandbox limits"):
        await provider.provision(resolved, CONTEXT, run_id="refuse")
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="native Seatbelt")
@pytest.mark.parametrize(
    "change",
    [
        {"env": {"EXAMPLE": "changed"}},
        {"stdin": b"changed"},
        {"timeout_seconds": 10},
    ],
)
async def test_grant_cannot_be_reused_with_changed_execution_inputs(tmp_path, change):
    _, issuer, handle = await local(tmp_path)
    request = ProcessRequest(argv=("python", "-c", "print('allowed')"))
    with pytest.raises(PermissionError, match="signed intent"):
        await handle.process.run(
            request.model_copy(update=change), **authorize(issuer, handle, request)
        )


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="native Seatbelt")
async def test_shell_cannot_read_or_write_outside_workspace_or_open_network(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = tmp_path / "outside.txt"
    sentinel.write_text("private")
    _, issuer, handle = await local(workspace)
    code = f"""
import pathlib, socket, os
for operation in [lambda: pathlib.Path({str(sentinel)!r}).read_text(),
                  lambda: pathlib.Path({str(sentinel)!r}).write_text('changed'),
                  lambda: pathlib.Path({"/System/Volumes/Data" + str(sentinel)!r}).read_text(),
                  lambda: os.link({str(sentinel)!r}, 'hardlink-escape'),
                  lambda: socket.create_connection(('127.0.0.1', 9), timeout=0.2)]:
    try:
        operation()
        print('ESCAPED')
    except PermissionError:
        print('denied')
pathlib.Path('inside.txt').write_text('allowed')
"""
    request = ProcessRequest(argv=("python", "-c", code))
    result = await handle.process.run(request, **authorize(issuer, handle, request))
    assert result.exit_code == 0, result.stderr
    assert result.stdout.splitlines() == [b"denied"] * 5
    assert sentinel.read_text() == "private"
    assert (workspace / "inside.txt").read_text() == "allowed"


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform != "darwin", reason="native macOS resource supervision"
)
async def test_memory_overage_kills_execution_and_fences_sandbox(tmp_path):
    _, issuer, handle = await local(tmp_path, memory_mb=64)
    request = ProcessRequest(
        argv=(
            "python",
            "-c",
            "import time; data=bytearray(128*1024*1024); time.sleep(2)",
        )
    )
    result = await handle.process.run(request, **authorize(issuer, handle, request))
    assert result.exit_code != 0
    assert (await handle.status()).state == SandboxState.LOST


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="native macOS CPU supervision")
async def test_macos_cpu_limit_throttles_a_busy_process(tmp_path):
    _, issuer, handle = await local(tmp_path, cpu_percent=20)
    request = ProcessRequest(
        argv=(
            "python",
            "-c",
            "import time\nstart=time.process_time(); until=time.monotonic()+1.2\nwhile time.monotonic()<until: pass\nprint(time.process_time()-start)",
        )
    )
    result = await handle.process.run(request, **authorize(issuer, handle, request))
    assert result.exit_code == 0, result.stderr
    # Allow startup/measurement bursts; this verifies actual throttling, not a hard guarantee.
    assert float(result.stdout) < 0.7


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform != "darwin", reason="native macOS resource supervision"
)
async def test_multiple_files_cannot_silently_exceed_standard_disk_limit(tmp_path):
    _, issuer, handle = await local(tmp_path, disk_mb=1)
    request = ProcessRequest(
        argv=(
            "python",
            "-c",
            "from pathlib import Path; [Path(str(i)).write_bytes(b'x'*700000) for i in range(2)]",
        )
    )
    with pytest.raises(RuntimeError, match="disk_mb"):
        await handle.process.run(request, **authorize(issuer, handle, request))
    assert (await handle.status()).state == SandboxState.LOST


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="native process lifecycle")
async def test_timeout_covers_blocked_stdin_and_terminate_rejects_queued_jobs(tmp_path):
    provider, issuer, handle = await local(tmp_path)
    request = ProcessRequest(
        argv=("python", "-c", "import time; time.sleep(2)"),
        stdin=b"x" * 2_000_000,
        timeout_seconds=0.15,
    )
    result = await handle.process.run(request, **authorize(issuer, handle, request))
    assert result.timed_out
    request = ProcessRequest(argv=("python", "-c", "import time; time.sleep(2)"))
    first = asyncio.create_task(
        handle.process.run(request, **authorize(issuer, handle, request))
    )
    await asyncio.sleep(0.1)
    second = asyncio.create_task(
        handle.process.run(request, **authorize(issuer, handle, request))
    )
    await asyncio.sleep(0)
    await handle.destroy()
    results = await asyncio.gather(first, second, return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError)
    assert isinstance(results[1], PermissionError)
    assert not provider._rows[handle.ref.sandbox_id].active_tasks


def test_descriptor_io_rejects_symlinks_and_hardlinks_without_modifying_target(
    tmp_path,
):
    from sagents.v2.runtime.execution.sandbox.local_support import files as local_files

    root = tmp_path / "work"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.write_bytes(b"keep")
    (root / "symlink").symlink_to(outside)
    os.link(outside, root / "hardlink")
    for name in ("symlink", "hardlink"):
        with pytest.raises((PermissionError, OSError)):
            local_files.write(root, Path(name), b"bad", create=False)
        with pytest.raises((PermissionError, OSError)):
            local_files.read(root, Path(name), 100)
    assert outside.read_bytes() == b"keep"


def test_resource_changes_are_bound_to_desktop_policy_hash(tmp_path):
    from app.desktop_v2.backend.bindings import DesktopExecutionBindingProvider

    first = DesktopExecutionBindingProvider(tmp_path).sandbox_spec()
    second = DesktopExecutionBindingProvider(
        tmp_path,
        resources=ResourceLimits(
            cpu_percent=50, memory_mb=512, disk_mb=512, require_hard_limits=False
        ),
    ).sandbox_spec()
    assert first.policy_hash != second.policy_hash
    assert first.spec_hash != second.spec_hash
    assert second.resources.disk_mb == 512


def test_workspace_cannot_supply_an_unsandboxed_launch_utility(tmp_path, monkeypatch):
    from sagents.v2.runtime.execution.sandbox.local_support import resources

    impostor = tmp_path / "bwrap"
    impostor.write_text("untrusted")
    monkeypatch.setattr(resources.shutil, "which", lambda name: str(impostor))
    with pytest.raises(PermissionError, match="outside the writable workspace"):
        resources._trusted_utility("bwrap", tmp_path)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="native Seatbelt")
async def test_preexisting_hard_link_is_rejected_before_execution(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = tmp_path / "secret"
    sentinel.write_bytes(b"keep")
    os.link(sentinel, workspace / "alias")
    with pytest.raises(PermissionError, match="hard link"):
        await local(workspace)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="native Seatbelt")
async def test_readable_runtime_file_cannot_be_hardlinked_for_writing(
    tmp_path, monkeypatch
):
    import json

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sentinel = tmp_path / "runtime-file"
    sentinel.write_text("keep")
    provider, issuer, handle = await local(workspace)
    boundary = provider._rows[handle.ref.sandbox_id].boundary
    original = boundary.command

    def with_readable_runtime(*args):
        command, job, fds = original(*args)
        profile_index = command.index("-p") + 1
        command[profile_index] += (
            f"\n(allow file-read* (literal {json.dumps(str(sentinel))}))"
        )
        return command, job, fds

    monkeypatch.setattr(boundary, "command", with_readable_runtime)
    code = f"import pathlib, os\nprint(pathlib.Path({str(sentinel)!r}).read_text())\ntry: os.link({str(sentinel)!r}, 'alias')\nexcept PermissionError: print('denied')"
    request = ProcessRequest(argv=("python", "-c", code))
    result = await handle.process.run(request, **authorize(issuer, handle, request))
    assert result.stdout.splitlines() == [b"keep", b"denied"]


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "darwin", reason="native Seatbelt")
async def test_sandbox_cannot_signal_an_unrelated_host_process(tmp_path):
    protected = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(10)"
    )
    try:
        _, issuer, handle = await local(tmp_path)
        code = f"import os, signal\ntry: os.kill({protected.pid}, signal.SIGTERM)\nexcept PermissionError: print('denied')"
        request = ProcessRequest(argv=("python", "-c", code))
        result = await handle.process.run(request, **authorize(issuer, handle, request))
        assert result.stdout.strip() == b"denied"
        assert protected.returncode is None
    finally:
        if protected.returncode is None:
            protected.terminate()
        await protected.wait()


def test_linux_launch_pins_mounts_cgroups_and_loader_environment(tmp_path, monkeypatch):
    import sagents.v2.runtime.execution.sandbox.local_support.resources as module

    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module, "_trusted_utility", lambda name, root: "/usr/bin/bwrap")
    monkeypatch.setattr(
        module, "_seccomp_filter", lambda: os.open(os.devnull, os.O_RDONLY)
    )
    row = SimpleNamespace(
        root=tmp_path,
        spec=spec(tmp_path),
        ref=SimpleNamespace(sandbox_id="sandbox-test"),
    )
    boundary = LocalResourceBoundary(row)
    boundary.cgroup = tmp_path / "cgroup"
    boundary.cgroup.mkdir()
    boundary.scratch.mkdir()
    environment = {"LD_PRELOAD": "/workspace/injection.so"}
    command, job, fds = boundary.command(
        "/usr/bin/python", ("-c", "pass"), tmp_path, environment
    )
    try:
        assert str(job) == command[4]
        assert command[2] == "-c"  # No mutable workspace helper before isolation.
        assert "--unshare-all" in command and "--cap-drop" in command
        assert "--disable-userns" in command
        assert "--seccomp" in command
        assert command.count("--bind-fd") == 3
        assert len(fds) == 4 and len(set(fds)) == 4
        assert command.count("--remount-ro") == 3
        assert "LD_PRELOAD" not in environment
        assert command.index("LD_PRELOAD") > command.index("--setenv")
    finally:
        for fd in fds:
            os.close(fd)


@pytest.mark.asyncio
@pytest.mark.skipif(
    sys.platform != "linux" or not os.getenv("SAGE_TEST_CGROUP_ROOT"),
    reason="requires dedicated Linux cgroup v2 and XFS project-quota workspace",
)
async def test_linux_kernel_limits_and_escaped_descendant_cleanup():
    root = Path(os.environ["SAGE_TEST_QUOTA_WORKSPACE"])
    issuer = SandboxGrantIssuer()
    provider = LocalWorkspaceSandboxProvider(
        issuer.verification_key,
        linux_cgroup_root=os.environ["SAGE_TEST_CGROUP_ROOT"],
        linux_quota_mount=os.environ["SAGE_TEST_QUOTA_MOUNT"],
        linux_execution_uid=int(os.environ["SAGE_TEST_EXECUTION_UID"]),
        linux_execution_gid=int(os.environ["SAGE_TEST_EXECUTION_GID"]),
    )
    resolved = spec(root).model_copy(
        update={"resources": ResourceLimits(cpu_percent=25, memory_mb=64, disk_mb=8)}
    )
    handle = await provider.provision(resolved, CONTEXT, run_id="kernel-test")
    row = provider._rows[handle.ref.sandbox_id]
    try:
        assert (row.boundary.cgroup / "cpu.max").read_text().strip() == "25000 100000"
        assert (row.boundary.cgroup / "memory.max").read_text().strip() == str(
            64 * 1024**2
        )
        request = ProcessRequest(
            argv=(
                "python",
                "-c",
                "import os, stat\n"
                "for entry in os.listdir('/proc/self/fd'):\n"
                " try: mode=os.fstat(int(entry)).st_mode\n"
                " except OSError: continue\n"
                " assert not stat.S_ISDIR(mode), 'inherited directory FD'\n"
                "print('closed')",
            )
        )
        descriptor_result = await handle.process.run(
            request, **authorize(issuer, handle, request)
        )
        assert descriptor_result.stdout.strip() == b"closed"
        request = ProcessRequest(argv=("python", "-c", "data=bytearray(256*1024*1024)"))
        result = await handle.process.run(request, **authorize(issuer, handle, request))
        assert result.exit_code != 0
        request = ProcessRequest(
            argv=(
                "python",
                "-c",
                "import time; until=time.monotonic()+1.5\nwhile time.monotonic()<until: pass",
            )
        )
        await handle.process.run(request, **authorize(issuer, handle, request))
        stats = dict(
            line.split()
            for line in (row.boundary.cgroup / "cpu.stat").read_text().splitlines()
        )
        assert int(stats["nr_throttled"]) > 0
        request = ProcessRequest(
            argv=(
                "python",
                "-c",
                "from pathlib import Path; [Path(str(i)).write_bytes(b'x'*3000000) for i in range(4)]",
            )
        )
        disk_result = await handle.process.run(
            request, **authorize(issuer, handle, request)
        )
        assert disk_result.exit_code != 0
        for index in range(4):
            (root / str(index)).unlink(missing_ok=True)
        request = ProcessRequest(argv=("bash", "-c", "unshare -Ur true"))
        namespace_result = await handle.process.run(
            request, **authorize(issuer, handle, request)
        )
        assert namespace_result.exit_code != 0
        request = ProcessRequest(
            argv=(
                "python",
                "-c",
                "import os, fcntl, struct\nfd=os.open('/workspace', os.O_RDONLY)\ndata=bytearray(fcntl.ioctl(fd, 0x801c581f, bytes(28)))\nstruct.pack_into('=I', data, 0, struct.unpack_from('=I', data)[0] & ~0x200)\ntry: fcntl.ioctl(fd, 0x401c5820, data)\nexcept PermissionError: print('denied')",
            )
        )
        inheritance_result = await handle.process.run(
            request, **authorize(issuer, handle, request)
        )
        assert inheritance_result.stdout.strip() == b"denied"
        request = ProcessRequest(
            argv=(
                "python",
                "-c",
                "import socket\ntry: socket.socket(socket.AF_UNIX)\nexcept PermissionError: print('denied')",
            )
        )
        socket_result = await handle.process.run(
            request, **authorize(issuer, handle, request)
        )
        assert socket_result.stdout.strip() == b"denied"
        request = ProcessRequest(
            argv=(
                "bash",
                "-c",
                "setsid sh -c 'touch /workspace/started; sleep 1; touch /workspace/escaped' >/dev/null 2>&1 & while [ ! -f /workspace/started ]; do sleep 0.01; done",
            )
        )
        await handle.process.run(request, **authorize(issuer, handle, request))
        assert (root / "started").exists()
        await asyncio.sleep(1.2)
        assert not (root / "escaped").exists()
    finally:
        await handle.destroy()
        await provider.purge_terminated(handle.ref)
