from __future__ import annotations

import asyncio
import base64
import contextlib
import ipaddress
import sys
import ssl
from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.runtime.execution.sandbox import NetworkMode, NetworkPolicy
from sagents.v2.runtime.execution.sandbox.local_support.network import (
    ShellNetworkBroker,
    _client_hello_host,
    _tls_prefix,
    validate_shell_network,
)


def policy(port, **changes):
    values = dict(
        mode=NetworkMode.ALLOWLIST,
        allowed_hosts=("127.0.0.1",),
        allowed_ports=(port,),
        allowed_schemes=("http", "https"),
        deny_private_networks=False,
    )
    values.update(changes)
    return NetworkPolicy(**values)


def authorization(broker):
    return (
        "Proxy-Authorization: Basic "
        + base64.b64encode(f"sage:{broker.token}".encode()).decode()
    )


@contextlib.asynccontextmanager
async def origin(*, tls=None):
    requests = []

    async def respond(reader, writer):
        try:
            requests.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(
                b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: 10\r\n\r\nnetwork-ok"
            )
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    server = await asyncio.start_server(respond, "127.0.0.1", 0, ssl=tls)
    try:
        yield server.sockets[0].getsockname()[1], requests
    finally:
        server.close()
        await server.wait_closed()


@contextlib.asynccontextmanager
async def broker_for(selected):
    broker = ShellNetworkBroker(selected)
    await broker.start()
    try:
        yield broker
    finally:
        await broker.close()


async def request(broker, target, *, authenticate=True, extra="", method="GET"):
    reader, writer = await asyncio.open_connection("127.0.0.1", broker.port)
    try:
        auth = authorization(broker) + "\r\n" if authenticate else ""
        writer.write(
            f"{method} {target} HTTP/1.1\r\nHost: ignored.invalid\r\n{auth}{extra}\r\n".encode()
        )
        await writer.drain()
        return await asyncio.wait_for(reader.read(), 3)
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_proxy_forwards_one_checked_http_request_and_strips_credentials():
    async with origin() as (port, requests), broker_for(policy(port)) as broker:
        result = await request(broker, f"http://127.0.0.1:{port}/page?q=1")
        assert result.endswith(b"network-ok")
        assert requests[0].startswith(b"GET /page?q=1 HTTP/1.1")
        assert f"Host: 127.0.0.1:{port}".encode() in requests[0]
        assert b"Proxy-Authorization" not in requests[0]
        assert b"ignored.invalid" not in requests[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_hosts": ("allowed.invalid",)},
        {"allowed_ports": (1,)},
        {"deny_private_networks": True},
        {"allowed_schemes": ("https",)},
    ],
)
async def test_proxy_rejects_disallowed_host_port_private_ip_and_scheme(changes):
    async with (
        origin() as (port, requests),
        broker_for(policy(port, **changes)) as broker,
    ):
        assert b"403 Forbidden" in await request(broker, f"http://127.0.0.1:{port}/")
        assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        "Content-Length: 0\r\nContent-Length: 5\r\n",
        "Transfer-Encoding: chunked\r\n",
        "Connection: content-length\r\nContent-Length: 0\r\n",
        "Bad Header: value\r\n",
        "X-Test: value\nHost: bypass.invalid\r\n",
    ],
)
async def test_proxy_rejects_ambiguous_http_framing(extra):
    async with origin() as (port, _), broker_for(policy(port)) as broker:
        assert b"403 Forbidden" in await request(
            broker, f"http://127.0.0.1:{port}/", extra=extra
        )


@pytest.mark.asyncio
async def test_proxy_requires_run_credentials_and_does_not_accept_userinfo_targets():
    async with origin() as (port, requests), broker_for(policy(port)) as broker:
        assert b"403 Forbidden" in await request(
            broker, f"http://127.0.0.1:{port}/", authenticate=False
        )
        assert b"403 Forbidden" in await request(
            broker, f"http://user@127.0.0.1:{port}/"
        )
        assert requests == []


@pytest.mark.asyncio
async def test_proxy_pins_the_checked_dns_address(monkeypatch):
    async with (
        origin() as (port, requests),
        broker_for(policy(port, allowed_hosts=("allowed.test",))) as broker,
    ):
        loop = asyncio.get_running_loop()
        original = loop.getaddrinfo
        calls = []

        async def resolve(host, selected_port, **kwargs):
            if host == "allowed.test":
                calls.append(host)
                return await original("127.0.0.1", selected_port, **kwargs)
            return await original(host, selected_port, **kwargs)

        monkeypatch.setattr(loop, "getaddrinfo", resolve)
        result = await request(broker, f"http://allowed.test:{port}/")
        assert result.endswith(b"network-ok")
        assert calls == ["allowed.test"]
        assert f"Host: allowed.test:{port}".encode() in requests[0]


@pytest.mark.asyncio
async def test_redirect_to_disallowed_host_is_checked_on_next_request():
    async with origin() as (port, _), broker_for(policy(port)) as broker:
        assert b"200 OK" in await request(broker, f"http://127.0.0.1:{port}/")
        assert b"403 Forbidden" in await request(
            broker, f"http://redirect.invalid:{port}/"
        )


@pytest.mark.asyncio
async def test_proxy_routes_through_configured_upstream_with_pinned_ip():
    authorities = []

    async def upstream(reader, writer):
        remote = None
        tasks = []
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            authorities.append(header.split(b"\r\n")[0])
            target = header.split(b" ")[1].decode()
            host, port = target.rsplit(":", 1)
            other, remote = await asyncio.open_connection(host, int(port))
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            async def copy(source, destination):
                while data := await source.read(65536):
                    destination.write(data)
                    await destination.drain()

            tasks = [
                asyncio.create_task(copy(reader, remote)),
                asyncio.create_task(copy(other, writer)),
            ]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            if remote:
                remote.close()

    server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    try:
        upstream_port = server.sockets[0].getsockname()[1]
        async with (
            origin() as (port, _),
            broker_for(
                policy(
                    port,
                    mode=NetworkMode.PROXY,
                    proxy_url=f"http://127.0.0.1:{upstream_port}",
                )
            ) as broker,
        ):
            assert (await request(broker, f"http://127.0.0.1:{port}/")).endswith(
                b"network-ok"
            )
            assert authorities == [f"CONNECT 127.0.0.1:{port} HTTP/1.1".encode()]
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_upstream_rejection_never_falls_back_to_direct_network():
    async def reject(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(reject, "127.0.0.1", 0)
    try:
        proxy_port = server.sockets[0].getsockname()[1]
        async with (
            origin() as (port, requests),
            broker_for(
                policy(
                    port,
                    mode=NetworkMode.PROXY,
                    proxy_url=f"http://127.0.0.1:{proxy_port}",
                )
            ) as broker,
        ):
            assert b"403 Forbidden" in await request(
                broker, f"http://127.0.0.1:{port}/"
            )
            assert requests == []
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_proxy_bounds_response_bytes_and_idle_connection_time():
    async with (
        origin() as (port, _),
        broker_for(policy(port, max_response_bytes=4)) as broker,
    ):
        assert b"network-ok" not in await request(broker, f"http://127.0.0.1:{port}/")
    async with broker_for(policy(443, max_wall_time_seconds=0.05)) as broker:
        reader, writer = await asyncio.open_connection("127.0.0.1", broker.port)
        try:
            assert b"403 Forbidden" in await asyncio.wait_for(reader.read(), 1)
        finally:
            writer.close()
            await writer.wait_closed()


@pytest.fixture
def certificate(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "allowed.test")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.DNSName("allowed.test"),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "ca.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@pytest.mark.asyncio
async def test_connect_tunnel_preserves_end_to_end_tls_certificate_verification(
    certificate,
):
    cert, key = certificate
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(cert, key)
    async with origin(tls=server_tls) as (port, _), broker_for(policy(port)) as broker:
        reader, writer = await asyncio.open_connection("127.0.0.1", broker.port)
        try:
            writer.write(
                f"CONNECT 127.0.0.1:{port} HTTP/1.1\r\n{authorization(broker)}\r\n\r\n".encode()
            )
            await writer.drain()
            assert b"200 Connection Established" in await reader.readuntil(b"\r\n\r\n")
            await writer.start_tls(
                ssl.create_default_context(cafile=cert), server_hostname="127.0.0.1"
            )
            writer.write(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            await writer.drain()
            assert (await asyncio.wait_for(reader.read(), 3)).endswith(b"network-ok")
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()


@pytest.mark.asyncio
async def test_tls_tunnel_rejects_different_server_name():
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    client = ssl.create_default_context().wrap_bio(
        incoming, outgoing, server_hostname="forbidden.test"
    )
    with pytest.raises(ssl.SSLWantReadError):
        client.do_handshake()
    record = outgoing.read()
    assert _client_hello_host(record[5:]) == "forbidden.test"
    reader = asyncio.StreamReader()
    reader.feed_data(record)
    reader.feed_eof()
    with pytest.raises(PermissionError, match="server name"):
        await _tls_prefix(reader, "allowed.test")


def test_exact_and_subdomain_wildcards_do_not_match_suffix_lookalikes():
    broker = ShellNetworkBroker(
        policy(443, allowed_hosts=("example.com", "*.example.org"))
    )
    assert broker._allowed("example.com")
    assert broker._allowed("sub.example.org")
    assert not broker._allowed("example.org")
    assert not broker._allowed("evilexample.com")
    assert not broker._allowed("example.com.evil.test")


@pytest.mark.parametrize(
    "values",
    [
        {"mode": "allowlist"},
        {"mode": "proxy"},
        {"mode": "proxy", "proxy_url": "socks5://localhost:8080"},
        {"mode": "proxy", "proxy_url": "http://user:pass@localhost:8080"},
        {"mode": "allowlist", "allowed_hosts": ["bad/host"]},
        {
            "mode": "allowlist",
            "allowed_hosts": ["example.com"],
            "allowed_methods": ["POST"],
        },
    ],
)
def test_proxy_configuration_fails_closed(values):
    with pytest.raises(ValueError):
        validate_shell_network(NetworkPolicy.model_validate(values))


@pytest.mark.asyncio
async def test_broker_close_stops_listening_and_closes_live_clients():
    broker = ShellNetworkBroker(policy(443))
    await broker.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", broker.port)
    await asyncio.sleep(0)
    await broker.close()
    with contextlib.suppress(ConnectionResetError):
        assert await asyncio.wait_for(reader.read(), 1) == b""
    with pytest.raises(OSError):
        await asyncio.open_connection("127.0.0.1", broker.port)
    writer.close()
    with contextlib.suppress(ConnectionResetError):
        await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native sandbox")
@pytest.mark.parametrize("mode", [NetworkMode.ALLOWLIST, NetworkMode.PROXY])
async def test_shell_uses_proxy_but_cannot_bypass_it(tmp_path, mode):
    from tests.sagents.v2.test_local_workspace_sandbox_matrix import (
        authorization as grant_for,
        provision,
    )
    from sagents.v2.runtime.execution.sandbox import ProcessRequest

    upstream_calls = []

    async def upstream(reader, writer):
        remote = None
        tasks = []
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            upstream_calls.append(header)
            host, port = header.split(b" ")[1].decode().rsplit(":", 1)
            remote_reader, remote = await asyncio.open_connection(host, int(port))
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            async def copy(source, destination):
                while data := await source.read(65536):
                    destination.write(data)
                    await destination.drain()

            tasks = [
                asyncio.create_task(copy(reader, remote)),
                asyncio.create_task(copy(remote_reader, writer)),
            ]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            if remote:
                remote.close()

    upstream_server = await asyncio.start_server(upstream, "127.0.0.1", 0)
    try:
        upstream_port = upstream_server.sockets[0].getsockname()[1]
        async with origin() as (port, requests):
            issuer, handle = await provision(
                tmp_path,
                network=policy(
                    port,
                    mode=mode,
                    proxy_url=f"http://127.0.0.1:{upstream_port}"
                    if mode == NetworkMode.PROXY
                    else None,
                ),
                allowed_executables=("python3",),
                read_paths=(sys.base_prefix,),
                max_output_bytes=8192,
                max_wall_time_seconds=10,
            )
            try:
                code = f"""import os, socket, urllib.request
print(urllib.request.urlopen('http://127.0.0.1:{port}/').read().decode())
try:
    urllib.request.urlopen('http://forbidden.invalid/')
    print('HOST-ESCAPED')
except urllib.error.HTTPError as error:
    print('host-denied' if error.code == 403 else 'unexpected-status')
for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
    os.environ.pop(name, None)
try:
    socket.create_connection(('127.0.0.1', {port}), timeout=1)
    print('ESCAPED')
except OSError:
    print('direct-denied')
try:
    socket.create_connection(('127.0.0.1', {upstream_port}), timeout=1)
    print('UPSTREAM-ESCAPED')
except OSError:
    print('upstream-denied')
"""
                argv = ("python3", "-c", code)
                intent, grant = grant_for(
                    issuer,
                    handle,
                    "process.run",
                    executable="python3",
                    argv=argv,
                    path="/workspace",
                )
                result = await handle.process.run(
                    ProcessRequest(argv=argv, cwd="/workspace"),
                    intent=intent,
                    grant=grant,
                )
                assert result.exit_code == 0, result.stderr
                assert result.stdout.splitlines() == [
                    b"network-ok",
                    b"host-denied",
                    b"direct-denied",
                    b"upstream-denied",
                ]
                assert len(requests) == 1
                assert bool(upstream_calls) is (mode == NetworkMode.PROXY)
            finally:
                await handle.destroy()
    finally:
        upstream_server.close()
        await upstream_server.wait_closed()


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native sandbox")
async def test_shell_https_through_allowlist_keeps_certificate_validation(
    tmp_path, certificate
):
    from tests.sagents.v2.test_local_workspace_sandbox_matrix import (
        authorization as grant_for,
        provision,
    )
    from sagents.v2.runtime.execution.sandbox import ProcessRequest

    cert, key = certificate
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(cert, key)
    async with origin(tls=server_tls) as (port, requests):
        issuer, handle = await provision(
            tmp_path,
            network=policy(port),
            allowed_executables=("python3",),
            read_paths=(sys.base_prefix,),
            max_output_bytes=8192,
            max_wall_time_seconds=10,
        )
        try:
            code = f"import ssl,urllib.request; context=ssl.create_default_context(cafile='ca.pem'); print(urllib.request.urlopen('https://127.0.0.1:{port}/',context=context).read().decode())"
            argv = ("python3", "-c", code)
            intent, grant = grant_for(
                issuer,
                handle,
                "process.run",
                executable="python3",
                argv=argv,
                path="/workspace",
            )
            result = await handle.process.run(
                ProcessRequest(argv=argv, cwd="/workspace"), intent=intent, grant=grant
            )
            assert result.exit_code == 0, result.stderr
            assert result.stdout.strip() == b"network-ok"
            assert len(requests) == 1
        finally:
            await handle.destroy()
