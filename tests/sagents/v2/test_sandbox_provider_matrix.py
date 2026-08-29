from __future__ import annotations

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
    SandboxState,
)
from sagents.v2.runtime.execution.sandbox.memory import (
    InMemorySandboxProvider,
    SandboxGrantIssuer,
)
from sagents.v2.contracts.errors import SageV2Error
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
    assert capabilities.supports_snapshot is True
    assert capabilities.network_modes == frozenset({NetworkMode.NONE})


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
