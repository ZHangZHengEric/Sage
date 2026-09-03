from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.runtime.execution.sandbox.contracts import (
    FileOperation,
    FileSystemMode,
    FileSystemPolicy,
    IsolationLevel,
    LifecyclePolicy,
    NetworkMode,
    NetworkPolicy,
    OperationIntent,
    ProcessPolicy,
    ResolvedSandboxSpec,
    SandboxDurability,
    SandboxReleaseDisposition,
    SandboxReleaseReceipt,
    SandboxReleaseRequest,
    SandboxState,
    TerminateMode,
)
from sagents.v2.runtime.execution.sandbox import (
    InMemorySandboxProvider,
    SandboxGrantIssuer,
)
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)


NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)
CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="user_1",
        principal_type=PrincipalType.USER,
        tenant_id="tenant_1",
    )
)


def spec(
    *,
    operations: frozenset[FileOperation] | None = None,
    max_file_bytes: int | None = 1024,
    max_total_bytes: int | None = 4096,
    process_enabled: bool = False,
    network_mode: NetworkMode = NetworkMode.NONE,
    protected_paths: tuple[str, ...] = (),
) -> ResolvedSandboxSpec:
    return ResolvedSandboxSpec(
        spec_hash="sha256:spec",
        architecture="portable",
        filesystem_mode=FileSystemMode.WORKSPACE,
        filesystem=FileSystemPolicy(
            allowed_operations=operations
            or frozenset(
                {
                    FileOperation.READ,
                    FileOperation.WRITE,
                    FileOperation.CREATE,
                    FileOperation.DELETE,
                    FileOperation.LIST,
                }
            ),
            protected_paths=protected_paths,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
        ),
        process=ProcessPolicy(enabled=process_enabled),
        network=NetworkPolicy(mode=network_mode),
        lifecycle=LifecyclePolicy(
            durability=SandboxDurability.SNAPSHOTABLE,
            pause_behavior="snapshot",
        ),
        policy_hash="sha256:policy",
    )


def provider_pair(*, now=NOW):
    def clock():
        return now

    issuer = SandboxGrantIssuer(b"test-key-32-bytes-minimum-length!!", clock=clock)
    provider = InMemorySandboxProvider(issuer.verification_key, clock=clock)
    return issuer, provider


class MutableClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def intent(ref, operation: FileOperation, path: str, *, run_id: str = "run_1"):
    return OperationIntent(
        operation=operation.value,
        run_id=run_id,
        tool_call_id=f"tool_{operation.value}",
        sandbox_id=ref.sandbox_id,
        path=path,
    )


def grant(issuer, ref, operation_intent, operation, *, ttl=timedelta(minutes=1)):
    return issuer.issue(
        ref=ref,
        intent=operation_intent,
        allowed_operations=frozenset({operation.value}),
        ttl=ttl,
    )


@pytest.mark.asyncio
async def test_capabilities_are_explicit_and_do_not_claim_security_or_processes():
    _, provider = provider_pair()
    capabilities = await provider.capabilities()

    assert capabilities.isolation_level == IsolationLevel.NONE
    assert capabilities.process.available is False
    assert capabilities.supports_background_jobs is False


@pytest.mark.asyncio
async def test_signed_grant_and_capability_sets_have_canonical_json_order():
    issuer, provider = provider_pair()
    handle = await provider.provision(spec(), CONTEXT, run_id="run_1")
    operation_intent = intent(handle.ref, FileOperation.READ, "/workspace/a.txt")
    signed = issuer.issue(
        ref=handle.ref,
        intent=operation_intent,
        allowed_operations=frozenset({"process.run", "read", "network.request"}),
    )
    capabilities = await provider.capabilities()

    assert signed.model_dump(mode="json")["allowed_operations"] == [
        "network.request",
        "process.run",
        "read",
    ]
    dumped = capabilities.model_dump(mode="json")
    assert dumped["filesystem_modes"] == sorted(dumped["filesystem_modes"])
    assert dumped["network_modes"] == sorted(dumped["network_modes"])
    assert dumped["supported_release_dispositions"] == sorted(
        dumped["supported_release_dispositions"]
    )
    assert capabilities.supports_snapshot is True
    assert capabilities.supports_terminal_purge is True
    assert capabilities.network_modes == frozenset({NetworkMode.NONE})


@pytest.mark.asyncio
async def test_terminated_sandbox_state_and_consumed_nonces_can_be_purged():
    issuer, provider = provider_pair()
    handle = await provider.provision(spec(), CONTEXT, run_id="run_1")
    create_intent = intent(handle.ref, FileOperation.CREATE, "temporary.txt")
    await handle.filesystem.write_bytes(
        "temporary.txt",
        b"temporary",
        intent=create_intent,
        grant=grant(issuer, handle.ref, create_intent, FileOperation.CREATE),
    )
    assert len(provider._used_nonces) == 1

    await handle.destroy()
    await provider.purge_terminated(handle.ref)

    assert provider._rows == {}
    assert provider._used_nonces == {}
    with pytest.raises(SageV2Error) as missing:
        await provider.inspect(handle.ref)
    assert missing.value.info.code == "sandbox.lost"


@pytest.mark.asyncio
async def test_automatic_sandbox_retention_preserves_attached_and_suspended_state():
    clock = MutableClock()
    provider = InMemorySandboxProvider(
        b"test-key-32-bytes-minimum-length!!",
        clock=clock,
        terminal_ttl_seconds=10,
        max_retained_terminal_items=1,
    )
    attached = await provider.provision(spec(), CONTEXT, run_id="run-attached")
    await provider.terminate(attached.ref, mode=TerminateMode.FORCE)
    clock.advance(11)
    trigger = await provider.provision(spec(), CONTEXT, run_id="run-trigger")
    assert (await provider.inspect(attached.ref)).state == SandboxState.TERMINATED

    await attached.close()
    with pytest.raises(SageV2Error) as expired:
        await provider.inspect(attached.ref)
    assert expired.value.info.code == "sandbox.lost"

    suspended = await provider.provision(spec(), CONTEXT, run_id="run-suspended")
    await suspended.suspend()
    await suspended.close()
    clock.advance(100)
    await trigger.destroy()
    assert (await provider.inspect(suspended.ref)).state == SandboxState.SUSPENDED

    caps = await provider.capabilities()
    assert caps.supports_automatic_terminal_retention is True
    assert caps.terminal_ttl_seconds == 10
    assert caps.max_retained_terminal_items == 1


@pytest.mark.asyncio
async def test_sandbox_terminal_count_cap_removes_oldest_detached_metadata():
    provider = InMemorySandboxProvider(
        b"test-key-32-bytes-minimum-length!!",
        max_retained_terminal_items=1,
    )
    first = await provider.provision(spec(), CONTEXT, run_id="run-first")
    await first.destroy()
    second = await provider.provision(spec(), CONTEXT, run_id="run-second")
    await second.destroy()

    with pytest.raises(SageV2Error):
        await provider.inspect(first.ref)
    assert (await provider.inspect(second.ref)).state == SandboxState.TERMINATED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_spec", "message"),
    [
        (spec(process_enabled=True), "process runtime"),
        (spec(network_mode=NetworkMode.UNRESTRICTED), "network mode"),
        (spec().model_copy(update={"architecture": "arm64"}), "architecture"),
    ],
)
async def test_provision_rejects_unsupported_capability_instead_of_downgrading(
    requested_spec, message
):
    _, provider = provider_pair()
    with pytest.raises(SageV2Error, match=message) as exc_info:
        await provider.provision(requested_spec, CONTEXT, run_id="run_1")
    assert exc_info.value.info.code == "sandbox.capability_unsupported"


@pytest.mark.asyncio
async def test_signed_single_use_grants_enforce_create_read_and_replay():
    issuer, provider = provider_pair()
    handle = await provider.provision(spec(), CONTEXT, run_id="run_1")
    create_intent = intent(handle.ref, FileOperation.CREATE, "notes/a.txt")
    create_grant = grant(issuer, handle.ref, create_intent, FileOperation.CREATE)

    stat = await handle.filesystem.write_bytes(
        "notes/a.txt",
        b"hello",
        intent=create_intent,
        grant=create_grant,
    )
    assert stat.path == "/workspace/notes/a.txt"
    assert stat.size == 5

    with pytest.raises(SageV2Error) as changed_operation:
        await handle.filesystem.write_bytes(
            "notes/a.txt",
            b"again",
            intent=create_intent,
            grant=create_grant,
        )
    assert changed_operation.value.info.code == "sandbox.grant_mismatch"

    read_intent = intent(handle.ref, FileOperation.READ, "notes/a.txt")
    read_grant = grant(issuer, handle.ref, read_intent, FileOperation.READ)
    content = await handle.filesystem.read_bytes(
        "notes/a.txt",
        intent=read_intent,
        grant=read_grant,
    )
    assert content == b"hello"
    with pytest.raises(SageV2Error) as replay:
        await handle.filesystem.read_bytes(
            "notes/a.txt", intent=read_intent, grant=read_grant
        )
    assert replay.value.info.code == "sandbox.grant_replayed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("run", "sandbox.grant_mismatch"),
        ("digest", "sandbox.grant_mismatch"),
        ("signature", "sandbox.grant_invalid"),
        ("policy", "sandbox.policy_stale"),
    ],
)
async def test_tampered_or_cross_scope_grant_is_rejected(mutation, error_code):
    issuer, provider = provider_pair()
    handle = await provider.provision(spec(), CONTEXT, run_id="run_1")
    operation_intent = intent(handle.ref, FileOperation.CREATE, "a.txt")
    operation_grant = grant(issuer, handle.ref, operation_intent, FileOperation.CREATE)
    if mutation == "run":
        operation_grant = operation_grant.model_copy(update={"run_id": "run_2"})
    elif mutation == "digest":
        operation_intent = operation_intent.model_copy(update={"path": "b.txt"})
    elif mutation == "signature":
        operation_grant = operation_grant.model_copy(update={"signature": "bad"})
    else:
        operation_grant = operation_grant.model_copy(
            update={"policy_hash": "sha256:old"}
        )

    with pytest.raises(SageV2Error) as exc_info:
        await handle.filesystem.write_bytes(
            operation_intent.path,
            b"content",
            intent=operation_intent,
            grant=operation_grant,
        )
    assert exc_info.value.info.code == error_code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["../secret", "/etc/passwd", "nested/../../secret", "..\\secret"],
)
async def test_path_traversal_and_absolute_escape_are_rejected(path):
    issuer, provider = provider_pair()
    handle = await provider.provision(spec(), CONTEXT, run_id="run_1")
    operation_intent = intent(handle.ref, FileOperation.CREATE, path)
    operation_grant = grant(issuer, handle.ref, operation_intent, FileOperation.CREATE)

    with pytest.raises(PermissionError):
        await handle.filesystem.write_bytes(
            path, b"secret", intent=operation_intent, grant=operation_grant
        )


@pytest.mark.asyncio
async def test_policy_and_resource_limits_fail_without_partial_file_write():
    issuer, provider = provider_pair()
    handle = await provider.provision(
        spec(
            operations=frozenset({FileOperation.READ, FileOperation.CREATE}),
            max_file_bytes=4,
        ),
        CONTEXT,
        run_id="run_1",
    )
    operation_intent = intent(handle.ref, FileOperation.CREATE, "large.txt")

    with pytest.raises(SageV2Error) as exhausted:
        await handle.filesystem.write_bytes(
            "large.txt",
            b"12345",
            intent=operation_intent,
            grant=grant(issuer, handle.ref, operation_intent, FileOperation.CREATE),
        )
    assert exhausted.value.info.code == "sandbox.resource_exhausted"
    assert (await handle.status()).file_count == 0


@pytest.mark.asyncio
async def test_expired_grant_is_rejected():
    issuer, provider = provider_pair()
    handle = await provider.provision(spec(), CONTEXT, run_id="run_1")
    operation_intent = intent(handle.ref, FileOperation.CREATE, "a.txt")
    expired = grant(
        issuer,
        handle.ref,
        operation_intent,
        FileOperation.CREATE,
        ttl=timedelta(seconds=-1),
    )
    with pytest.raises(SageV2Error) as exc_info:
        await handle.filesystem.write_bytes(
            "a.txt", b"a", intent=operation_intent, grant=expired
        )
    assert exc_info.value.info.code == "sandbox.grant_expired"


@pytest.mark.asyncio
async def test_snapshot_restore_attach_ownership_and_terminate_lifecycle():
    issuer, provider = provider_pair()
    handle = await provider.provision(spec(), CONTEXT, run_id="run_1")
    create_intent = intent(handle.ref, FileOperation.CREATE, "state.txt")
    await handle.filesystem.write_bytes(
        "state.txt",
        b"stable",
        intent=create_intent,
        grant=grant(issuer, handle.ref, create_intent, FileOperation.CREATE),
    )

    checkpoint = await handle.suspend()
    assert (await handle.status()).state == SandboxState.SUSPENDED
    restored = await provider.restore(checkpoint, CONTEXT)
    read_intent = intent(restored.ref, FileOperation.READ, "state.txt")
    assert (
        await restored.filesystem.read_bytes(
            "state.txt",
            intent=read_intent,
            grant=grant(issuer, restored.ref, read_intent, FileOperation.READ),
        )
        == b"stable"
    )

    other_tenant = RequestContext(
        actor=ActorRef(
            principal_id="user_2",
            principal_type=PrincipalType.USER,
            tenant_id="tenant_2",
        )
    )
    with pytest.raises(SageV2Error) as denied:
        await provider.attach(restored.ref, other_tenant)
    assert denied.value.info.code == "sandbox.permission_denied"

    await restored.destroy()
    assert (await provider.inspect(restored.ref)).state == SandboxState.TERMINATED
    with pytest.raises(SageV2Error) as lost:
        await provider.attach(restored.ref, CONTEXT)
    assert lost.value.info.code == "sandbox.lost"


@pytest.mark.asyncio
async def test_v3_release_is_idempotent_and_snapshot_fences_old_compute():
    issuer, provider = provider_pair()
    handle = await provider.provision(spec(), CONTEXT, run_id="run_1")
    operation_intent = intent(handle.ref, FileOperation.CREATE, "state.txt")
    old_grant = grant(issuer, handle.ref, operation_intent, FileOperation.CREATE)
    snapshot = await provider.inspect(handle.ref)
    request = SandboxReleaseRequest(
        ref=handle.ref,
        disposition=SandboxReleaseDisposition.SNAPSHOT_AND_TERMINATE,
        reason="approval_required",
        expected_revision=snapshot.revision,
        idempotency_key="release_once",
    )

    first = await provider.release(request, CONTEXT)
    duplicate = await provider.release(request, CONTEXT)

    assert first.compute_released is True
    assert first.state == SandboxState.TERMINATED
    assert first.checkpoint is not None
    assert duplicate.duplicate is True
    assert duplicate.checkpoint == first.checkpoint
    with pytest.raises(SageV2Error):
        await handle.filesystem.write_bytes(
            "state.txt",
            b"stale",
            intent=operation_intent,
            grant=old_grant,
        )


def test_release_receipt_rejects_unconfirmed_or_inconsistent_compute_state():
    _issuer, provider = provider_pair()

    # Obtain a well-formed ref without reaching into provider internals.
    async def build_ref():
        return (await provider.provision(spec(), CONTEXT, run_id="run_1")).ref

    ref = asyncio.run(build_ref())
    with pytest.raises(ValueError):
        SandboxReleaseReceipt(
            ref=ref,
            disposition=SandboxReleaseDisposition.TERMINATE,
            state=SandboxState.READY,
            compute_released=True,
            released_at=NOW,
        )


# ---------- FileSystemPolicy.protected_paths ----------


@pytest.mark.parametrize(
    "raw",
    ["/workspace/.git/hooks", "../.git", "..", ".", "", "hooks/../../etc", "..\\x"],
)
def test_protected_paths_reject_absolute_or_escaping_entries(raw):
    with pytest.raises(ValueError, match="relative path inside the workspace"):
        FileSystemPolicy(
            allowed_operations=frozenset(FileOperation), protected_paths=(raw,)
        )


def test_protected_paths_are_canonical_and_match_defensively():
    policy = FileSystemPolicy(
        allowed_operations=frozenset(FileOperation),
        protected_paths=("./.git/hooks/", ".git\\config", ".git/hooks", ".git//info"),
    )
    reordered = FileSystemPolicy(
        allowed_operations=frozenset(FileOperation),
        protected_paths=(".git/info", ".git/hooks", ".git/config"),
    )

    # 去重、排序、统一分隔符 → policy_hash 与书写顺序/写法无关。
    assert policy.protected_paths == (".git/config", ".git/hooks", ".git/info")
    assert policy.model_dump(mode="json") == reordered.model_dump(mode="json")
    assert policy.model_dump(mode="json")["protected_paths"] == [
        ".git/config",
        ".git/hooks",
        ".git/info",
    ]
    # 子树、大小写、ADS、重复分隔符与 ".." 都命中；同前缀的兄弟路径不误伤。
    assert policy.protected_path_for(".git/hooks") == ".git/hooks"
    assert policy.protected_path_for(".git/hooks/pre-commit") == ".git/hooks"
    assert policy.protected_path_for(".GIT/Hooks/pre-commit") == ".git/hooks"
    assert policy.protected_path_for(".git/config:evil") == ".git/config"
    assert policy.protected_path_for(".git//hooks/../hooks/x") == ".git/hooks"
    assert policy.protected_path_for("/.git/hooks/x") == ".git/hooks"
    assert policy.protected_path_for(".git/hooks-extra/x") is None
    assert policy.protected_path_for(".git/config.bak") is None
    assert policy.protected_path_for(".git/description") is None
    assert policy.protected_path_for(".gitignore") is None
    assert policy.protected_path_for("") is None
    whole_git = FileSystemPolicy(
        allowed_operations=frozenset(FileOperation), protected_paths=(".git",)
    )
    assert whole_git.protected_path_for(".gitignore") is None
    assert whole_git.protected_path_for(".git/objects/ab/cd") == ".git"
    # NFC/NFD 视作同一路径（macOS 文件系统对规范化不敏感）。
    accented = FileSystemPolicy(
        allowed_operations=frozenset(FileOperation), protected_paths=("données",)
    )
    assert accented.protected_path_for("données/x") == "données"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        ".git/hooks/pre-commit",
        ".git/hooks",
        "/workspace/.git/hooks/post-commit",
        ".GIT/HOOKS/pre-commit",
        "src/../.git/hooks/pre-commit",
        ".git//hooks//pre-commit",
        ".git\\hooks\\pre-commit",
        ".git/config",
        ".git/config:stream",
    ],
)
async def test_protected_paths_reject_every_mutating_spelling(path):
    issuer, provider = provider_pair()
    handle = await provider.provision(
        spec(protected_paths=(".git/hooks", ".git/config")), CONTEXT, run_id="run_1"
    )
    operation_intent = intent(handle.ref, FileOperation.CREATE, path)

    with pytest.raises(SageV2Error) as denied:
        await handle.filesystem.write_bytes(
            path,
            b"x",
            intent=operation_intent,
            grant=grant(issuer, handle.ref, operation_intent, FileOperation.CREATE),
        )

    assert denied.value.info.code == "sandbox.protected_path"
    assert denied.value.info.category == ErrorCategory.POLICY_DENIED
    assert denied.value.info.safe_to_resume is True
    # 拒绝发生在写入之前：工具执行器据此判定为干净失败，而不是结果未知。
    assert denied.value.info.metadata["side_effect_state"] == "not_applied"
    assert denied.value.info.metadata["protected_path"] in {".git/hooks", ".git/config"}
    assert (await handle.status()).file_count == 0


@pytest.mark.asyncio
async def test_protected_paths_keep_reads_and_unprotected_writes_working():
    issuer, provider = provider_pair()
    handle = await provider.provision(
        spec(protected_paths=(".git/hooks",)), CONTEXT, run_id="run_1"
    )
    # 模拟宿主仓库里预置的 hook：受保护内容只能来自策略之外。
    provider._rows[handle.ref.sandbox_id].files["/workspace/.git/hooks/pre-commit"] = (
        b"#!/bin/sh\n"
    )

    read_intent = intent(handle.ref, FileOperation.READ, ".git/hooks/pre-commit")
    assert (
        await handle.filesystem.read_bytes(
            ".git/hooks/pre-commit",
            intent=read_intent,
            grant=grant(issuer, handle.ref, read_intent, FileOperation.READ),
        )
        == b"#!/bin/sh\n"
    )
    list_intent = intent(handle.ref, FileOperation.LIST, ".git")
    listed = await handle.filesystem.list_paths(
        ".git",
        intent=list_intent,
        grant=grant(issuer, handle.ref, list_intent, FileOperation.LIST),
    )
    assert [value.path for value in listed] == ["/workspace/.git/hooks/pre-commit"]

    delete_intent = intent(handle.ref, FileOperation.DELETE, ".git/hooks/pre-commit")
    with pytest.raises(SageV2Error) as denied:
        await handle.filesystem.delete(
            ".git/hooks/pre-commit",
            intent=delete_intent,
            grant=grant(issuer, handle.ref, delete_intent, FileOperation.DELETE),
        )
    assert denied.value.info.code == "sandbox.protected_path"

    for path in (".gitignore", ".git/description", "src/main.py"):
        create_intent = intent(handle.ref, FileOperation.CREATE, path)
        await handle.filesystem.write_bytes(
            path,
            b"ok",
            intent=create_intent,
            grant=grant(issuer, handle.ref, create_intent, FileOperation.CREATE),
        )
    status = await handle.status()
    assert status.file_count == 4
