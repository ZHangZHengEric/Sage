from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    LifecyclePolicy,
    LocalWorkspaceSandboxProvider,
    OperationIntent,
    ProcessPolicy,
    ProcessRequest,
    ResolvedSandboxSpec,
    SandboxDurability,
    SandboxGrantIssuer,
    SandboxReleaseDisposition,
    SandboxReleaseRequest,
    SandboxState,
)


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


async def provision(
    root: Path,
    *,
    max_total_bytes: int = 2048,
    allowed_roots: tuple[str, ...] = ("/workspace",),
    process_read_only: bool = False,
    allowed_executables: tuple[str, ...] = ("python",),
    protected_paths: tuple[str, ...] = (),
    allow_symlinks: bool = False,
):
    issuer = SandboxGrantIssuer(b"local-provider-test-key-32-bytes!!")
    provider = LocalWorkspaceSandboxProvider(issuer.verification_key)
    handle = await provider.provision(
        ResolvedSandboxSpec(
            spec_hash="sha256:spec",
            architecture="native",
            filesystem=FileSystemPolicy(
                allowed_operations=frozenset(FileOperation),
                allowed_roots=allowed_roots,
                protected_paths=protected_paths,
                max_file_bytes=1024,
                max_total_bytes=max_total_bytes,
                allow_symlinks=allow_symlinks,
            ),
            process=ProcessPolicy(
                enabled=True,
                read_only=process_read_only,
                allowed_executables=allowed_executables,
                max_wall_time_seconds=2,
                max_output_bytes=32,
            ),
            policy_hash="sha256:policy",
            metadata={"host_workspace": str(root)},
        ),
        CONTEXT,
        run_id="run_1",
    )
    return issuer, handle


def authorization(issuer, handle, operation, **fields):
    intent = OperationIntent(
        operation=operation,
        run_id="run_1",
        tool_call_id="call_1",
        sandbox_id=handle.ref.sandbox_id,
        **fields,
    )
    grant = issuer.issue(
        ref=handle.ref,
        intent=intent,
        allowed_operations=frozenset({operation}),
    )
    return intent, grant


@pytest.mark.asyncio
async def test_protected_paths_guard_file_api_without_claiming_process_isolation(tmp_path):
    issuer, handle = await provision(
        tmp_path, protected_paths=(".git/config",), allowed_executables=("sh",)
    )
    caps = await handle.provider.capabilities()
    assert caps.isolation_level.value == "none"
    (tmp_path / ".git").mkdir()
    target = tmp_path / ".git/config"
    target.write_text("original")
    intent, grant = authorization(issuer, handle, "write", path=".git/config")
    with pytest.raises(SageV2Error) as denied:
        await handle.filesystem.write_bytes(".git/config", b"changed", intent=intent, grant=grant)
    assert denied.value.info.code == "sandbox.protected_path"
    assert target.read_text() == "original"
    # Explicitly granted host processes have no OS filesystem isolation.
    argv = ("sh", "-c", "printf process > .git/config")
    intent, grant = authorization(
        issuer, handle, "process.run", executable="sh", argv=argv, path="/workspace"
    )
    result = await handle.process.run(
        ProcessRequest(argv=argv, cwd="/workspace"), intent=intent, grant=grant
    )
    assert result.exit_code == 0
    assert target.read_text() == "process"
    await handle.destroy()


@pytest.mark.asyncio
async def test_local_workspace_reads_and_writes_only_with_matching_signed_grants(
    tmp_path: Path,
):
    issuer, handle = await provision(tmp_path)
    intent, grant = authorization(issuer, handle, "create", path="note.txt")
    stat = await handle.filesystem.write_bytes(
        "note.txt", b"hello", intent=intent, grant=grant, overwrite=False
    )
    read_intent, read_grant = authorization(
        issuer, handle, "read", path="/workspace/note.txt"
    )

    assert stat.path == "/workspace/note.txt"
    assert (
        await handle.filesystem.read_bytes(
            "/workspace/note.txt", intent=read_intent, grant=read_grant
        )
        == b"hello"
    )
    assert (tmp_path / "note.txt").read_bytes() == b"hello"


@pytest.mark.asyncio
async def test_local_workspace_retention_removes_only_kernel_metadata(tmp_path: Path):
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def clock():
        return now

    issuer = SandboxGrantIssuer(b"local-provider-test-key-32-bytes!!", clock=clock)
    provider = LocalWorkspaceSandboxProvider(
        issuer.verification_key,
        clock=clock,
        terminal_ttl_seconds=10,
        max_retained_terminal_items=1,
    )
    resolved = ResolvedSandboxSpec(
        spec_hash="sha256:retention",
        architecture="native",
        filesystem=FileSystemPolicy(
            allowed_operations=frozenset(FileOperation),
            max_file_bytes=1024,
            max_total_bytes=2048,
        ),
        process=ProcessPolicy(enabled=False),
        policy_hash="sha256:retention-policy",
        metadata={"host_workspace": str(tmp_path)},
    )
    handle = await provider.provision(resolved, CONTEXT, run_id="run-retention")
    host_file = tmp_path / "host-owned.txt"
    host_file.write_text("keep", encoding="utf-8")
    await handle.destroy()
    now += timedelta(seconds=11)
    await provider.provision(resolved, CONTEXT, run_id="run-trigger")

    with pytest.raises(ValueError, match="unknown"):
        await provider.inspect(handle.ref)
    assert host_file.read_text(encoding="utf-8") == "keep"
    caps = await provider.capabilities()
    assert caps.supports_automatic_terminal_retention is True


@pytest.mark.asyncio
async def test_active_workspace_release_reprovisions_without_losing_host_files(
    tmp_path: Path,
):
    issuer = SandboxGrantIssuer(b"local-provider-test-key-32-bytes!!")
    provider = LocalWorkspaceSandboxProvider(issuer.verification_key)
    resolved = ResolvedSandboxSpec(
        spec_hash="sha256:active-workspace",
        architecture="native",
        filesystem=FileSystemPolicy(
            allowed_operations=frozenset(FileOperation),
        ),
        lifecycle=LifecyclePolicy(
            durability=SandboxDurability.DURABLE_EXTERNAL,
            safe_pause_behavior=SandboxReleaseDisposition.TERMINATE,
        ),
        policy_hash="sha256:active-workspace-policy",
        metadata={"host_workspace": str(tmp_path)},
    )
    handle = await provider.provision(resolved, CONTEXT, run_id="run_1")
    (tmp_path / "durable.txt").write_text("kept", encoding="utf-8")
    status = await handle.status()

    receipt = await provider.release(
        SandboxReleaseRequest(
            ref=handle.ref,
            disposition=SandboxReleaseDisposition.TERMINATE,
            reason="approval_required",
            expected_revision=status.revision,
            idempotency_key="release-active-workspace",
        ),
        CONTEXT,
    )
    recreated = await provider.provision(resolved, CONTEXT, run_id="run_1")

    assert receipt.compute_released is True
    assert receipt.state == SandboxState.TERMINATED
    assert recreated.ref.sandbox_id != handle.ref.sandbox_id
    assert (tmp_path / "durable.txt").read_text(encoding="utf-8") == "kept"


@pytest.mark.asyncio
async def test_local_workspace_maps_host_paths_at_the_sandbox_boundary(
    tmp_path: Path,
):
    _, handle = await provision(tmp_path)
    inside = tmp_path / "nested" / "note.txt"
    assert handle.filesystem.normalize_path(str(inside)) == (
        "/workspace/nested/note.txt"
    )
    with pytest.raises(PermissionError, match="outside"):
        handle.filesystem.normalize_path(str(tmp_path.parent / "outside.txt"))


@pytest.mark.asyncio
async def test_local_workspace_denies_traversal_and_grant_replay(tmp_path: Path):
    issuer, handle = await provision(tmp_path)
    intent, grant = authorization(issuer, handle, "create", path="../escape.txt")
    with pytest.raises(PermissionError, match="outside"):
        await handle.filesystem.write_bytes(
            "../escape.txt", b"bad", intent=intent, grant=grant
        )

    valid_intent, valid_grant = authorization(
        issuer, handle, "create", path="inside.txt"
    )
    await handle.filesystem.write_bytes(
        "inside.txt", b"ok", intent=valid_intent, grant=valid_grant
    )
    with pytest.raises(PermissionError, match="already used"):
        await handle.filesystem.write_bytes(
            "inside.txt", b"again", intent=valid_intent, grant=valid_grant
        )


@pytest.mark.asyncio
async def test_local_workspace_binds_file_grant_to_the_requested_path(tmp_path: Path):
    issuer, handle = await provision(tmp_path)
    intent, grant = authorization(issuer, handle, "create", path="allowed.txt")

    with pytest.raises(PermissionError, match="signed intent"):
        await handle.filesystem.write_bytes(
            "different.txt", b"blocked", intent=intent, grant=grant
        )

    assert not (tmp_path / "different.txt").exists()


@pytest.mark.asyncio
async def test_local_workspace_enforces_total_workspace_bytes(tmp_path: Path):
    issuer, handle = await provision(tmp_path, max_total_bytes=6)
    first_intent, first_grant = authorization(
        issuer, handle, "create", path="first.txt"
    )
    await handle.filesystem.write_bytes(
        "first.txt", b"1234", intent=first_intent, grant=first_grant
    )
    second_intent, second_grant = authorization(
        issuer, handle, "create", path="second.txt"
    )

    with pytest.raises(ValueError, match="max_total_bytes"):
        await handle.filesystem.write_bytes(
            "second.txt", b"789", intent=second_intent, grant=second_grant
        )


@pytest.mark.asyncio
async def test_local_workspace_enforces_configured_subdirectory_roots(tmp_path: Path):
    (tmp_path / "allowed").mkdir()
    issuer, handle = await provision(tmp_path, allowed_roots=("/workspace/allowed",))
    intent, grant = authorization(issuer, handle, "create", path="outside.txt")

    with pytest.raises(PermissionError, match="allowed filesystem roots"):
        await handle.filesystem.write_bytes(
            "outside.txt", b"blocked", intent=intent, grant=grant
        )


@pytest.mark.asyncio
async def test_local_process_is_argv_only_allowlisted_and_output_bounded(
    tmp_path: Path,
):
    issuer, handle = await provision(tmp_path)
    request = ProcessRequest(
        argv=("python", "-c", "print('x' * 100)"), cwd="/workspace"
    )
    intent, grant = authorization(
        issuer,
        handle,
        "process.run",
        path=request.cwd,
        executable="python",
        argv=request.argv,
    )

    result = await handle.process.run(request, intent=intent, grant=grant)

    assert result.exit_code == 0
    assert result.truncated is True
    assert len(result.stdout) <= 32


@pytest.mark.asyncio
@pytest.mark.timeout(8)
@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
async def test_local_process_cancellation_reaps_descendants_and_releases_slot(
    tmp_path: Path,
):
    issuer, handle = await provision(tmp_path, allowed_executables=("bash",))
    running_request = ProcessRequest(
        argv=(
            "bash",
            "-c",
            "trap '' TERM; (sleep 3; touch leaked-after-kill.txt) & wait",
        ),
        cwd="/workspace",
    )
    running_intent, running_grant = authorization(
        issuer,
        handle,
        "process.run",
        path=running_request.cwd,
        executable="bash",
        argv=running_request.argv,
    )
    running = asyncio.create_task(
        handle.process.run(running_request, intent=running_intent, grant=running_grant)
    )
    await asyncio.sleep(0.2)

    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(running, timeout=4)

    echo_request = ProcessRequest(argv=("bash", "-c", "echo alive"), cwd="/workspace")
    echo_intent, echo_grant = authorization(
        issuer,
        handle,
        "process.run",
        path=echo_request.cwd,
        executable="bash",
        argv=echo_request.argv,
    )
    echoed = await asyncio.wait_for(
        handle.process.run(echo_request, intent=echo_intent, grant=echo_grant),
        timeout=2,
    )
    assert echoed.stdout.strip() == b"alive"

    # The child would create this file after its direct parent was killed if
    # cancellation failed to terminate the complete process group.
    await asyncio.sleep(1.1)
    assert not (tmp_path / "leaked-after-kill.txt").exists()


@pytest.mark.asyncio
async def test_local_process_denies_unlisted_executable(tmp_path: Path):
    issuer, handle = await provision(tmp_path)
    request = ProcessRequest(argv=("sh", "-c", "echo unsafe"), cwd="/workspace")
    intent, grant = authorization(
        issuer,
        handle,
        "process.run",
        path=request.cwd,
        executable="sh",
        argv=request.argv,
    )
    with pytest.raises(PermissionError, match="not allowed"):
        await handle.process.run(request, intent=intent, grant=grant)


@pytest.mark.asyncio
async def test_read_only_process_fails_closed_without_os_isolation(tmp_path: Path):
    (tmp_path / "note.txt").write_text("needle\n", encoding="utf-8")
    issuer, handle = await provision(
        tmp_path,
        process_read_only=True,
        allowed_executables=("bash",),
    )
    request = ProcessRequest(
        argv=("bash", "-c", "cat note.txt | head -n 1"), cwd="/workspace"
    )
    intent, grant = authorization(
        issuer,
        handle,
        "process.run",
        path=request.cwd,
        executable="bash",
        argv=request.argv,
    )

    with pytest.raises(PermissionError, match="requires an isolated sandbox"):
        await handle.process.run(request, intent=intent, grant=grant)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    (
        "touch changed.txt",
        "echo changed > note.txt",
        'python -c \'open("changed.txt", "w").write("x")\'',
        "find . -delete",
        "git diff --output=changed.patch",
    ),
)
async def test_read_only_process_rejects_mutating_shell_commands(
    tmp_path: Path, command: str
):
    issuer, handle = await provision(
        tmp_path,
        process_read_only=True,
        allowed_executables=("bash",),
    )
    request = ProcessRequest(argv=("bash", "-c", command), cwd="/workspace")
    intent, grant = authorization(
        issuer,
        handle,
        "process.run",
        path=request.cwd,
        executable="bash",
        argv=request.argv,
    )

    with pytest.raises(PermissionError, match="requires an isolated sandbox"):
        await handle.process.run(request, intent=intent, grant=grant)

    assert not (tmp_path / "changed.txt").exists()
    assert not (tmp_path / "changed.patch").exists()


@pytest.mark.asyncio
async def test_local_process_binds_grant_to_argv_and_does_not_inherit_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("SAGE_TEST_HOST_SECRET", "must-not-leak")
    issuer, handle = await provision(tmp_path)
    approved = ProcessRequest(
        argv=("python", "-c", "print('approved')"), cwd="/workspace"
    )
    intent, grant = authorization(
        issuer,
        handle,
        "process.run",
        path=approved.cwd,
        executable=approved.argv[0],
        argv=approved.argv,
    )
    changed = ProcessRequest(
        argv=(
            "python",
            "-c",
            "import os; print(os.environ.get('SAGE_TEST_HOST_SECRET', 'absent'))",
        ),
        cwd="/workspace",
    )

    with pytest.raises(PermissionError, match="signed intent"):
        await handle.process.run(changed, intent=intent, grant=grant)

    clean_intent, clean_grant = authorization(
        issuer,
        handle,
        "process.run",
        path=changed.cwd,
        executable=changed.argv[0],
        argv=changed.argv,
    )
    result = await handle.process.run(changed, intent=clean_intent, grant=clean_grant)
    assert result.stdout.strip() == b"absent"


# ---------- FileSystemPolicy.protected_paths（本地 provider） ----------


def _seed_git_dir(root: Path) -> tuple[Path, Path]:
    hooks = root / ".git" / "hooks"
    hooks.mkdir(parents=True)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    config = root / ".git" / "config"
    config.write_text("[core]\n", encoding="utf-8")
    return hook, config


@pytest.mark.asyncio
async def test_local_workspace_denies_every_mutating_spelling_of_protected_paths(
    tmp_path: Path,
):
    hook, config = _seed_git_dir(tmp_path)
    issuer, handle = await provision(
        tmp_path, protected_paths=(".git/hooks", ".git/config")
    )

    attempts = (
        ("create", ".git/hooks/post-commit"),
        ("write", ".git/hooks/pre-commit"),
        ("write", "/workspace/.git/config"),
        ("write", str(config)),  # 宿主绝对路径写法
        ("create", ".GIT/HOOKS/post-commit"),  # 大小写变体
        ("create", "src/../.git/hooks/post-commit"),
        ("create", ".git//hooks//post-commit"),
        ("create", ".git/config:stream"),  # Windows ADS 写法
        ("create", ".git/hooks/nested/deeper"),
    )
    for operation, path in attempts:
        intent, grant = authorization(issuer, handle, operation, path=path)
        with pytest.raises(SageV2Error) as denied:
            await handle.filesystem.write_bytes(
                path, b"evil", intent=intent, grant=grant
            )
        assert denied.value.info.code == "sandbox.protected_path", path
        assert denied.value.info.category == ErrorCategory.POLICY_DENIED
        assert denied.value.info.safe_to_resume is True
        assert denied.value.info.metadata["side_effect_state"] == "not_applied"
        assert denied.value.info.metadata["protected_path"] in {
            ".git/hooks",
            ".git/config",
        }
    delete_intent, delete_grant = authorization(
        issuer, handle, "delete", path=".git/hooks/pre-commit"
    )
    with pytest.raises(SageV2Error) as denied:
        await handle.filesystem.delete(
            ".git/hooks/pre-commit", intent=delete_intent, grant=delete_grant
        )
    assert denied.value.info.code == "sandbox.protected_path"

    assert hook.read_text(encoding="utf-8") == "#!/bin/sh\n"
    assert config.read_text(encoding="utf-8") == "[core]\n"
    assert sorted(value.name for value in (tmp_path / ".git").iterdir()) == [
        "config",
        "hooks",
    ]
    assert [value.name for value in (tmp_path / ".git" / "hooks").iterdir()] == [
        "pre-commit"
    ]
    assert not (tmp_path / ".GIT").exists() or (tmp_path / ".GIT").samefile(
        tmp_path / ".git"
    )


@pytest.mark.asyncio
async def test_local_workspace_protected_paths_stay_readable_and_siblings_writable(
    tmp_path: Path,
):
    hook, _config = _seed_git_dir(tmp_path)
    issuer, handle = await provision(tmp_path, protected_paths=(".git",))

    read_intent, read_grant = authorization(
        issuer, handle, "read", path=".git/hooks/pre-commit"
    )
    assert (
        await handle.filesystem.read_bytes(
            ".git/hooks/pre-commit", intent=read_intent, grant=read_grant
        )
        == b"#!/bin/sh\n"
    )
    stat_intent, stat_grant = authorization(issuer, handle, "read", path=".git/config")
    assert (
        await handle.filesystem.stat(".git/config", intent=stat_intent, grant=stat_grant)
    ).is_file is True
    list_intent, list_grant = authorization(issuer, handle, "list", path=".git/hooks")
    listed = await handle.filesystem.list_paths(
        ".git/hooks", intent=list_intent, grant=list_grant
    )
    assert [value.path for value in listed] == ["/workspace/.git/hooks/pre-commit"]

    # ".git" 受保护不能误伤 ".gitignore" 这类同前缀兄弟路径。
    for path in (".gitignore", "src/main.py", ".github/workflows/ci.yml"):
        intent, grant = authorization(issuer, handle, "create", path=path)
        await handle.filesystem.write_bytes(path, b"ok", intent=intent, grant=grant)
        assert (tmp_path / path).read_bytes() == b"ok"


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges")
@pytest.mark.asyncio
async def test_local_workspace_protects_paths_reached_through_symlinks(
    tmp_path: Path,
):
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (tmp_path / "link").symlink_to(hooks, target_is_directory=True)
    issuer, handle = await provision(
        tmp_path, protected_paths=(".git/hooks",), allow_symlinks=True
    )
    intent, grant = authorization(issuer, handle, "create", path="link/pre-commit")

    with pytest.raises(SageV2Error) as denied:
        await handle.filesystem.write_bytes(
            "link/pre-commit", b"evil", intent=intent, grant=grant
        )

    assert denied.value.info.code == "sandbox.protected_path"
    assert not (hooks / "pre-commit").exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges")
@pytest.mark.asyncio
async def test_local_workspace_protects_a_symlinked_protected_entry_itself(
    tmp_path: Path,
):
    real_hooks = tmp_path / "real_git" / "hooks"
    real_hooks.mkdir(parents=True)
    (tmp_path / ".git").symlink_to(tmp_path / "real_git", target_is_directory=True)
    issuer, handle = await provision(
        tmp_path, protected_paths=(".git/hooks",), allow_symlinks=True
    )
    intent, grant = authorization(
        issuer, handle, "create", path=".git/hooks/pre-commit"
    )

    # 解析后的真实路径是 real_git/hooks/pre-commit，不在策略里；
    # 但模型请求的字面路径命中 ".git/hooks"，仍须拒绝。
    with pytest.raises(SageV2Error) as denied:
        await handle.filesystem.write_bytes(
            ".git/hooks/pre-commit", b"evil", intent=intent, grant=grant
        )

    assert denied.value.info.code == "sandbox.protected_path"
    assert not (real_hooks / "pre-commit").exists()


@pytest.mark.asyncio
async def test_local_workspace_without_protected_paths_keeps_git_writable(
    tmp_path: Path,
):
    hook, _config = _seed_git_dir(tmp_path)
    issuer, handle = await provision(tmp_path)
    intent, grant = authorization(issuer, handle, "write", path=".git/hooks/pre-commit")

    await handle.filesystem.write_bytes(
        ".git/hooks/pre-commit", b"#!/bin/sh\necho ok\n", intent=intent, grant=grant
    )

    assert hook.read_text(encoding="utf-8") == "#!/bin/sh\necho ok\n"
