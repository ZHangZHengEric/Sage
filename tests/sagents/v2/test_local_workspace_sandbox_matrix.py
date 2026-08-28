from __future__ import annotations

from pathlib import Path

import pytest

from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    LocalWorkspaceSandboxProvider,
    OperationIntent,
    ProcessPolicy,
    ProcessRequest,
    ResolvedSandboxSpec,
    SandboxGrantIssuer,
)


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


async def provision(
    root: Path,
    *,
    max_total_bytes: int = 2048,
    allowed_roots: tuple[str, ...] = ("/workspace",),
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
                max_file_bytes=1024,
                max_total_bytes=max_total_bytes,
            ),
            process=ProcessPolicy(
                enabled=True,
                allowed_executables=("python",),
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
