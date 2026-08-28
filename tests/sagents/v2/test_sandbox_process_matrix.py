from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    InMemorySandboxProvider,
    OperationIntent,
    ProcessPolicy,
    ProcessRequest,
    ResolvedSandboxSpec,
    SandboxGrantIssuer,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext


NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)
CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


async def echo_handler(request):
    return 0, " ".join(request.argv[1:]).encode(), b""


async def noisy_handler(request):
    return 2, b"12345", b"67890"


async def slow_handler(request):
    await asyncio.sleep(1)
    return 0, b"late", b""


def setup(*, allowed=("echo",), max_output=1024, max_wall_time=1):
    def clock():
        return NOW

    issuer = SandboxGrantIssuer(b"test-key-32-bytes-minimum-length!!", clock=clock)
    provider = InMemorySandboxProvider(
        issuer.verification_key,
        process_handlers={
            "echo": echo_handler,
            "noisy": noisy_handler,
            "slow": slow_handler,
        },
        clock=clock,
    )
    spec = ResolvedSandboxSpec(
        spec_hash="sha256:spec",
        architecture="portable",
        filesystem=FileSystemPolicy(
            allowed_operations=frozenset({FileOperation.READ}),
        ),
        process=ProcessPolicy(
            enabled=True,
            allowed_executables=allowed,
            allowed_env_names=("LANG",),
            max_wall_time_seconds=max_wall_time,
            max_output_bytes=max_output,
        ),
        policy_hash="sha256:policy",
    )
    return issuer, provider, spec


def authorization(issuer, ref, request, *, argv=None, executable=None, cwd=None):
    intent = OperationIntent(
        operation="process.run",
        run_id="run_1",
        tool_call_id="tool_process",
        sandbox_id=ref.sandbox_id,
        path=cwd or request.cwd,
        executable=executable or request.argv[0],
        argv=argv or request.argv,
    )
    grant = issuer.issue(
        ref=ref,
        intent=intent,
        allowed_operations=frozenset({"process.run"}),
    )
    return intent, grant


@pytest.mark.asyncio
async def test_registered_argv_process_runs_without_shell_and_records_result():
    issuer, provider, process_spec = setup()
    assert (await provider.capabilities()).process.supports_shell is False
    handle = await provider.provision(process_spec, CONTEXT, run_id="run_1")
    request = ProcessRequest(argv=("echo", "hello"), env={"LANG": "C"})
    intent, grant = authorization(issuer, handle.ref, request)

    result = await handle.process.run(request, intent=intent, grant=grant)

    assert result.exit_code == 0
    assert result.stdout == b"hello"
    assert result.argv == ("echo", "hello")
    assert result.timed_out is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("process_request", "code"),
    [
        (ProcessRequest(argv=("python", "x.py")), "sandbox.permission_denied"),
        (
            ProcessRequest(argv=("echo",), env={"SECRET": "x"}),
            "sandbox.permission_denied",
        ),
        (
            ProcessRequest(argv=("echo",), cwd="../outside"),
            "path_permission",
        ),
    ],
)
async def test_process_policy_denies_executable_environment_and_cwd(
    process_request, code
):
    issuer, provider, process_spec = setup()
    handle = await provider.provision(process_spec, CONTEXT, run_id="run_1")
    intent, grant = authorization(issuer, handle.ref, process_request)
    expected = PermissionError if code == "path_permission" else SageV2Error
    with pytest.raises(expected) as caught:
        await handle.process.run(process_request, intent=intent, grant=grant)
    if isinstance(caught.value, SageV2Error):
        assert caught.value.info.code == code


@pytest.mark.asyncio
async def test_process_grant_binds_exact_argv_and_is_single_use():
    issuer, provider, process_spec = setup()
    handle = await provider.provision(process_spec, CONTEXT, run_id="run_1")
    request = ProcessRequest(argv=("echo", "one"))
    intent, grant = authorization(issuer, handle.ref, request)
    changed = ProcessRequest(argv=("echo", "two"))
    with pytest.raises(SageV2Error) as mismatch:
        await handle.process.run(changed, intent=intent, grant=grant)
    assert mismatch.value.info.code == "sandbox.grant_mismatch"
    await handle.process.run(request, intent=intent, grant=grant)
    with pytest.raises(SageV2Error) as replay:
        await handle.process.run(request, intent=intent, grant=grant)
    assert replay.value.info.code == "sandbox.grant_replayed"


@pytest.mark.asyncio
async def test_process_timeout_and_combined_output_limit_are_enforced():
    issuer, provider, timeout_spec = setup(allowed=("slow",), max_wall_time=0.01)
    handle = await provider.provision(timeout_spec, CONTEXT, run_id="run_1")
    slow = ProcessRequest(argv=("slow",))
    intent, grant = authorization(issuer, handle.ref, slow)
    timed_out = await handle.process.run(slow, intent=intent, grant=grant)
    assert timed_out.exit_code == 124
    assert timed_out.timed_out is True

    issuer, provider, output_spec = setup(allowed=("noisy",), max_output=7)
    handle = await provider.provision(output_spec, CONTEXT, run_id="run_1")
    noisy = ProcessRequest(argv=("noisy",))
    intent, grant = authorization(issuer, handle.ref, noisy)
    result = await handle.process.run(noisy, intent=intent, grant=grant)
    assert result.truncated is True
    assert len(result.stdout) + len(result.stderr) == 7
