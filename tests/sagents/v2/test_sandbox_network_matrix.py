from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    InMemorySandboxProvider,
    NetworkMode,
    NetworkPolicy,
    NetworkRequest,
    NetworkResult,
    OperationIntent,
    ResolvedSandboxSpec,
    SandboxGrantIssuer,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext


NOW = datetime(2026, 8, 25, tzinfo=timezone.utc)
CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


def setup(*, policy=None, handler=None):
    issuer = SandboxGrantIssuer(
        b"test-key-32-bytes-minimum-length!!", clock=lambda: NOW
    )

    async def default_handler(request):
        return NetworkResult(
            request_id="request_1",
            status_code=200,
            final_url=request.url,
            body=b"response-body",
        )

    provider = InMemorySandboxProvider(
        issuer.verification_key,
        network_handlers={"api.example.com": handler or default_handler},
        clock=lambda: NOW,
    )
    spec = ResolvedSandboxSpec(
        spec_hash="sha256:spec",
        architecture="portable",
        filesystem=FileSystemPolicy(allowed_operations=frozenset({FileOperation.READ})),
        network=policy
        or NetworkPolicy(
            mode=NetworkMode.ALLOWLIST,
            allowed_hosts=("api.example.com",),
            allowed_ports=(443,),
            max_response_bytes=8,
        ),
        policy_hash="sha256:policy",
    )
    return issuer, provider, spec


def authorization(issuer, ref, request):
    from urllib.parse import urlsplit

    parsed = urlsplit(request.url)
    host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    intent = OperationIntent(
        operation="network.request",
        run_id="run_1",
        tool_call_id="tool_network",
        sandbox_id=ref.sandbox_id,
        network_host=host,
        network_port=port,
        metadata={"method": request.method.upper(), "url": request.url},
    )
    grant = issuer.issue(
        ref=ref,
        intent=intent,
        allowed_operations=frozenset({"network.request"}),
    )
    return intent, grant


@pytest.mark.asyncio
async def test_allowlisted_request_is_grant_bound_and_response_quota_is_enforced():
    issuer, provider, spec = setup()
    capabilities = await provider.capabilities()
    assert NetworkMode.ALLOWLIST in capabilities.network_modes
    handle = await provider.provision(spec, CONTEXT, run_id="run_1")
    request = NetworkRequest(method="GET", url="https://api.example.com/data")
    intent, grant = authorization(issuer, handle.ref, request)

    result = await handle.network.request(request, intent=intent, grant=grant)

    assert result.status_code == 200
    assert result.body == b"response"
    assert result.truncated is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("network_request", "code"),
    [
        (
            NetworkRequest(url="https://other.example.com/data"),
            "sandbox.permission_denied",
        ),
        (
            NetworkRequest(url="https://api.example.com:444/data"),
            "sandbox.permission_denied",
        ),
        (
            NetworkRequest(method="POST", url="https://api.example.com/data"),
            "sandbox.permission_denied",
        ),
        (
            NetworkRequest(url="http://api.example.com/data"),
            "sandbox.permission_denied",
        ),
        (
            NetworkRequest(url="https://127.0.0.1/data"),
            "sandbox.private_network_denied",
        ),
    ],
)
async def test_network_policy_denial_matrix(network_request, code):
    issuer, provider, spec = setup()
    handle = await provider.provision(spec, CONTEXT, run_id="run_1")
    intent, grant = authorization(issuer, handle.ref, network_request)
    with pytest.raises(SageV2Error) as caught:
        await handle.network.request(network_request, intent=intent, grant=grant)
    assert caught.value.info.code == code


@pytest.mark.asyncio
async def test_network_grant_binds_exact_url_method_and_is_single_use():
    issuer, provider, spec = setup()
    handle = await provider.provision(spec, CONTEXT, run_id="run_1")
    original = NetworkRequest(url="https://api.example.com/one")
    intent, grant = authorization(issuer, handle.ref, original)
    changed = NetworkRequest(url="https://api.example.com/two")
    with pytest.raises(SageV2Error) as mismatch:
        await handle.network.request(changed, intent=intent, grant=grant)
    assert mismatch.value.info.code == "sandbox.grant_mismatch"
    await handle.network.request(original, intent=intent, grant=grant)
    with pytest.raises(SageV2Error) as replay:
        await handle.network.request(original, intent=intent, grant=grant)
    assert replay.value.info.code == "sandbox.grant_replayed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("final_url", "redirect_count", "code"),
    [
        ("https://blocked.example.net/data", 1, "sandbox.redirect_denied"),
        ("https://api.example.com/data", 6, "sandbox.redirect_limit"),
    ],
)
async def test_redirect_policy_is_rechecked(final_url, redirect_count, code):
    async def redirecting(request):
        return NetworkResult(
            request_id="request_1",
            status_code=200,
            final_url=final_url,
            redirect_count=redirect_count,
        )

    issuer, provider, spec = setup(handler=redirecting)
    handle = await provider.provision(spec, CONTEXT, run_id="run_1")
    request = NetworkRequest(url="https://api.example.com/start")
    intent, grant = authorization(issuer, handle.ref, request)
    with pytest.raises(SageV2Error) as caught:
        await handle.network.request(request, intent=intent, grant=grant)
    assert caught.value.info.code == code
