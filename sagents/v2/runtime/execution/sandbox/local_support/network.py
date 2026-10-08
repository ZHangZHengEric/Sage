"""Run-owned HTTP/HTTPS egress broker for isolated Shell processes.

The broker, not client environment variables, enforces destination policy. DNS
is resolved once and the checked address is the address actually connected to.
HTTPS uses CONNECT without terminating or weakening client TLS verification.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import errno
import ipaddress
import os
import re
import socket
import ssl
import secrets
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from ..contracts import NetworkMode, NetworkPolicy

_HEADER_LIMIT = 32 * 1024
_PROXY_MODES = {NetworkMode.ALLOWLIST, NetworkMode.PROXY}
_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


def _host(value: str) -> str:
    value = value.rstrip(".").lower()
    if not value or any(character in value for character in "/\\@%\x00"):
        raise ValueError("invalid network host")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        result = value.encode("idna").decode("ascii")
        if any(
            not label
            or not all(c.isalnum() or c == "-" for c in label)
            or label.startswith("-")
            or label.endswith("-")
            for label in result.split(".")
        ):
            raise ValueError("invalid network host")
        return result


def validate_shell_network(policy: NetworkPolicy) -> None:
    if policy.mode == NetworkMode.NONE:
        return
    if policy.mode == NetworkMode.UNRESTRICTED:
        expected = NetworkPolicy(mode=policy.mode, deny_private_networks=False)
        if policy != expected:
            raise ValueError(
                "unrestricted Shell networking does not support additional network constraints"
            )
        return
    if policy.mode not in _PROXY_MODES:
        raise ValueError("unsupported Shell network mode")
    if policy.allow_listen:
        raise ValueError("Shell proxy modes do not support listening")
    if policy.mode == NetworkMode.ALLOWLIST and not policy.allowed_hosts:
        raise ValueError("allowlist Shell networking requires allowed_hosts")
    if policy.mode == NetworkMode.ALLOWLIST and policy.proxy_url:
        raise ValueError("proxy_url requires network mode proxy")
    if policy.mode == NetworkMode.PROXY:
        if not policy.proxy_url:
            raise ValueError("proxy Shell networking requires proxy_url")
        parsed = urlsplit(policy.proxy_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "proxy_url must be an HTTP(S) proxy origin without credentials"
            )
        _host(parsed.hostname)
        if parsed.port is not None and parsed.port < 1:
            raise ValueError("proxy_url port must be between 1 and 65535")
    for pattern in policy.allowed_hosts:
        _host(pattern[2:] if pattern.startswith("*.") else pattern)
    if any(port < 1 or port > 65535 for port in policy.allowed_ports):
        raise ValueError("allowed_ports must be between 1 and 65535")
    # An opaque HTTPS tunnel cannot enforce HTTP methods, headers or redirect
    # counts. These fields belong to network.request; reject custom values.
    defaults = NetworkPolicy()
    for field in ("allowed_methods", "allowed_request_headers", "max_redirects"):
        if getattr(policy, field) != getattr(defaults, field):
            raise ValueError(f"Shell proxy modes cannot enforce {field}")


def _client_hello_host(hello: bytes) -> str | None:
    """Read the visible SNI from one complete TLS ClientHello, without MITM."""
    if len(hello) < 39 or hello[0] != 1:
        raise ValueError("CONNECT requires a TLS ClientHello")
    end = 4 + int.from_bytes(hello[1:4], "big")
    if end > len(hello):
        raise ValueError("truncated TLS ClientHello")
    position = 38

    def take(length: int) -> bytes:
        nonlocal position
        if position + length > end:
            raise ValueError("invalid TLS ClientHello length")
        data = hello[position : position + length]
        position += length
        return data

    take(take(1)[0])  # session ID
    take(int.from_bytes(take(2), "big"))  # cipher suites
    take(take(1)[0])  # compression methods
    if position == end:
        return None
    extension_end = position + 2 + int.from_bytes(take(2), "big")
    if extension_end != end:
        raise ValueError("invalid TLS extension length")
    hostname = None
    seen = set()
    while position < end:
        kind = int.from_bytes(take(2), "big")
        data = take(int.from_bytes(take(2), "big"))
        if kind in seen:
            raise ValueError("duplicate TLS extension")
        seen.add(kind)
        if kind == 0xFE0D:
            raise PermissionError(
                "encrypted ClientHello cannot be checked by Shell proxy"
            )
        if kind == 0:
            if len(data) < 5 or int.from_bytes(data[:2], "big") != len(data) - 2:
                raise ValueError("invalid TLS server name")
            if data[2] != 0 or int.from_bytes(data[3:5], "big") != len(data) - 5:
                raise ValueError("unsupported TLS server name list")
            hostname = _host(data[5:].decode("ascii"))
    return hostname


async def _tls_prefix(reader: asyncio.StreamReader, host: str) -> bytes:
    records = bytearray()
    handshake = bytearray()
    while len(records) < 64 * 1024:
        header = await reader.readexactly(5)
        size = int.from_bytes(header[3:5], "big")
        if header[0] != 22 or header[1] != 3 or size < 1 or size > 18 * 1024:
            raise PermissionError("CONNECT accepts TLS traffic only")
        body = await reader.readexactly(size)
        records.extend(header + body)
        if len(records) > 64 * 1024:
            raise PermissionError("TLS ClientHello exceeds limit")
        handshake.extend(body)
        if len(handshake) >= 4 and len(handshake) >= 4 + int.from_bytes(
            handshake[1:4], "big"
        ):
            requested = _client_hello_host(bytes(handshake))
            try:
                ipaddress.ip_address(host)
                is_ip = True
            except ValueError:
                is_ip = False
            if requested != host and not (is_ip and requested is None):
                raise PermissionError("TLS server name differs from CONNECT authority")
            return bytes(records)
    raise PermissionError("TLS ClientHello exceeds limit")


class ShellNetworkBroker:
    def __init__(self, policy: NetworkPolicy) -> None:
        validate_shell_network(policy)
        self.policy = policy
        self.server: asyncio.AbstractServer | None = None
        self.server6: asyncio.AbstractServer | None = None
        self.port: int | None = None
        self.socket_path: Path | None = None
        self._directory: tempfile.TemporaryDirectory | None = None
        self._tasks: set[asyncio.Task] = set()
        self._writers: set[asyncio.StreamWriter] = set()
        self._closed = False
        self._slots = asyncio.Semaphore(32)
        # Prevent other local users/runs from using this run's TCP broker.
        self.token = secrets.token_urlsafe(32)

    async def start(
        self, *, unix: bool = False, uid: int | None = None, gid: int | None = None
    ) -> None:
        if self.server is not None or self._closed:
            raise RuntimeError("Shell proxy cannot be started twice")
        if unix:
            self._directory = tempfile.TemporaryDirectory(prefix="sage-egress-")
            directory = Path(self._directory.name)
            self.socket_path = directory / "proxy.sock"
            self.server = await asyncio.start_unix_server(
                self._accept, path=self.socket_path, limit=_HEADER_LIMIT + 1
            )
            if uid is not None and os.geteuid() == 0:
                os.chown(directory, uid, gid)
                os.chown(self.socket_path, uid, gid)
            self.socket_path.chmod(0o600)
        else:
            self.server = await asyncio.start_server(
                self._accept, "127.0.0.1", 0, limit=_HEADER_LIMIT + 1
            )
            self.port = self.server.sockets[0].getsockname()[1]
            # Seatbelt's localhost matcher includes IPv6. Reserve that same
            # TCP port on ::1 as well, so no unrelated local service occupies
            # an address the sandbox is allowed to reach.
            extra = None
            try:
                extra = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                extra.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                extra.bind(("::1", self.port))
                self.server6 = await asyncio.start_server(
                    self._accept, sock=extra, limit=_HEADER_LIMIT + 1
                )
            except OSError as error:
                if extra is not None:
                    extra.close()
                if error.errno not in {errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL}:
                    raise

    def environment(self, port: int | None = None) -> dict[str, str]:
        selected = self.port if port is None else port
        if selected is None:
            raise RuntimeError("Shell proxy has not started")
        value = f"http://sage:{self.token}@127.0.0.1:{selected}"
        return {
            "HTTP_PROXY": value,
            "HTTPS_PROXY": value,
            "ALL_PROXY": value,
            "http_proxy": value,
            "https_proxy": value,
            "all_proxy": value,
            "NO_PROXY": "",
            "no_proxy": "",
        }

    def _allowed(self, host: str) -> bool:
        patterns = self.policy.allowed_hosts
        if not patterns:
            return self.policy.mode == NetworkMode.PROXY
        for pattern in patterns:
            wildcard = pattern.startswith("*.")
            normalized = _host(pattern[2:] if wildcard else pattern)
            if host == normalized and not wildcard:
                return True
            if wildcard and host.endswith("." + normalized):
                return True
        return False

    async def _resolve(self, host: str, port: int) -> str:
        if not self._allowed(host):
            raise PermissionError("destination host is outside network policy")
        if port not in (self.policy.allowed_ports or (80, 443)):
            raise PermissionError("destination port is outside network policy")
        answers = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
        for _, _, _, _, address in answers:
            ip = ipaddress.ip_address(address[0])
            if (
                self.policy.deny_private_networks
                and not (
                    ip.ipv4_mapped
                    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped
                    else ip
                ).is_global
            ):
                continue
            return str(ip)
        raise PermissionError("destination has no permitted IP address")

    async def _connect(self, address: str, port: int):
        if self.policy.mode != NetworkMode.PROXY:
            return await asyncio.open_connection(address, port)
        parsed = urlsplit(self.policy.proxy_url)
        reader, writer = await asyncio.open_connection(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            ssl=ssl.create_default_context() if parsed.scheme == "https" else None,
            server_hostname=parsed.hostname if parsed.scheme == "https" else None,
            limit=_HEADER_LIMIT + 1,
        )
        self._writers.add(writer)
        authority = f"[{address}]:{port}" if ":" in address else f"{address}:{port}"
        try:
            writer.write(
                f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode()
            )
            await writer.drain()
            header = await reader.readuntil(b"\r\n\r\n")
            status = header.split(b"\r\n", 1)[0].split(b" ")
            if len(status) < 2 or status[1] != b"200":
                raise PermissionError("upstream proxy refused the destination")
            return reader, writer
        except BaseException:
            self._writers.discard(writer)
            writer.transport.abort()
            raise

    async def _copy(self, reader, writer, limit: int) -> None:
        total = 0
        while chunk := await reader.read(64 * 1024):
            total += len(chunk)
            if total > limit:
                raise PermissionError("Shell proxy transfer limit exceeded")
            writer.write(chunk)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()

    async def _relay(
        self, reader, writer, remote_reader, remote_writer, *, prefix_bytes: int = 0
    ) -> None:
        tasks = [
            asyncio.create_task(
                self._copy(
                    reader,
                    remote_writer,
                    self.policy.max_request_body_bytes - prefix_bytes,
                )
            ),
            asyncio.create_task(
                self._copy(remote_reader, writer, self.policy.max_response_bytes)
            ),
        ]
        try:
            # Either side closing stops the tunnel. Do not retain a hung upload
            # after an origin closes its response.
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if tasks[0] in done and tasks[1] not in done:
                # A client half-close does not discard the pending response.
                await tasks[1]
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _accept(self, reader, writer) -> None:
        if self._closed or len(self._tasks) >= 64:
            writer.transport.abort()
            return
        task = asyncio.current_task()
        self._tasks.add(task)
        self._writers.add(writer)
        remote_writer = None
        connected = False
        try:
            async with asyncio.timeout(self.policy.max_wall_time_seconds), self._slots:
                header = await reader.readuntil(b"\r\n\r\n")
                if len(header) > _HEADER_LIMIT:
                    raise ValueError("proxy headers exceed limit")
                lines = header.decode("iso-8859-1").split("\r\n")
                method, target, version = lines[0].split(" ")
                if not _TOKEN.fullmatch(method) or any(ord(c) < 32 for c in target):
                    raise ValueError("invalid proxy request line")
                if version not in {"HTTP/1.0", "HTTP/1.1"}:
                    raise ValueError("unsupported proxy HTTP version")
                headers = []
                seen = set()
                for line in lines[1:-2]:
                    if not line or line[0].isspace() or ":" not in line:
                        raise ValueError("invalid proxy header")
                    name, value = line.split(":", 1)
                    if not _TOKEN.fullmatch(name) or any(
                        ord(c) < 32 and c != "\t" for c in value
                    ):
                        raise ValueError("invalid proxy header")
                    name = name.lower()
                    if name in seen:
                        raise ValueError("duplicate proxy header")
                    seen.add(name)
                    headers.append((name, value.strip()))
                auth = dict(headers).get("proxy-authorization", "")
                expected = (
                    "Basic " + base64.b64encode(f"sage:{self.token}".encode()).decode()
                )
                if not secrets.compare_digest(auth.encode(), expected.encode()):
                    raise PermissionError("Shell proxy authentication required")
                is_tunnel = method == "CONNECT"
                parsed = urlsplit("https://" + target if is_tunnel else target)
                if (
                    not parsed.hostname
                    or parsed.username is not None
                    or parsed.password is not None
                    or parsed.fragment
                ):
                    raise ValueError("invalid proxy target")
                if is_tunnel and (parsed.port is None or parsed.path or parsed.query):
                    raise ValueError("CONNECT requires host:port")
                scheme = "https" if is_tunnel else parsed.scheme
                if scheme not in self.policy.allowed_schemes or (
                    not is_tunnel and scheme != "http"
                ):
                    raise PermissionError(
                        "destination scheme is outside network policy"
                    )
                host = _host(parsed.hostname)
                port = parsed.port or (443 if scheme == "https" else 80)
                address = await self._resolve(host, port)
                remote_reader, remote_writer = await self._connect(address, port)
                self._writers.add(remote_writer)
                if is_tunnel:
                    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    await writer.drain()
                    connected = True
                    prefix = await _tls_prefix(reader, host)
                    if len(prefix) > self.policy.max_request_body_bytes:
                        raise PermissionError("TLS request exceeds transfer limit")
                    remote_writer.write(prefix)
                    await remote_writer.drain()
                    await self._relay(
                        reader,
                        writer,
                        remote_reader,
                        remote_writer,
                        prefix_bytes=len(prefix),
                    )
                else:
                    # Read exactly one framed request. Never blindly tunnel
                    # pipelined HTTP requests with unchecked authorities.
                    if (
                        "transfer-encoding" in seen
                        or "upgrade" in seen
                        or "expect" in seen
                    ):
                        raise ValueError("unsupported HTTP request framing")
                    length = dict(headers).get("content-length", "0")
                    if not re.fullmatch(r"[0-9]+", length):
                        raise ValueError("invalid content length")
                    size = int(length)
                    if size < 0 or size > self.policy.max_request_body_bytes:
                        raise PermissionError("HTTP request body exceeds policy")
                    body = await reader.readexactly(size)
                    path = parsed.path or "/"
                    if parsed.query:
                        path += "?" + parsed.query
                    authority = f"[{host}]" if ":" in host else host
                    if port != 80:
                        authority += f":{port}"
                    hop = {
                        "host",
                        "connection",
                        "proxy-authorization",
                        "proxy-connection",
                        "keep-alive",
                        "te",
                        "trailer",
                    }
                    if set(
                        dict(headers)
                        .get("connection", "")
                        .lower()
                        .replace(" ", "")
                        .split(",")
                    ) & {"content-length", "host", "transfer-encoding"}:
                        raise ValueError("invalid hop-by-hop framing")
                    hop.update(
                        value.strip().lower()
                        for value in dict(headers).get("connection", "").split(",")
                    )
                    forwarded = [
                        f"{method} {path} HTTP/1.1",
                        f"Host: {authority}",
                        "Connection: close",
                    ]
                    forwarded += [
                        f"{name}: {value}" for name, value in headers if name not in hop
                    ]
                    remote_writer.write(
                        ("\r\n".join(forwarded) + "\r\n\r\n").encode("iso-8859-1")
                        + body
                    )
                    await remote_writer.drain()
                    connected = True
                    await self._copy(
                        remote_reader, writer, self.policy.max_response_bytes
                    )
        except (
            PermissionError,
            ValueError,
            OSError,
            TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            if not connected:
                with contextlib.suppress(OSError):
                    writer.write(
                        b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
                    )
                    await writer.drain()
        finally:
            for stream in (writer, remote_writer):
                if stream is not None:
                    self._writers.discard(stream)
                    stream.close()
                    try:
                        await asyncio.wait_for(stream.wait_closed(), 0.5)
                    except (OSError, TimeoutError):
                        stream.transport.abort()
            self._tasks.discard(task)

    async def close(self) -> None:
        self._closed = True
        if self.server:
            self.server.close()
        if self.server6:
            self.server6.close()
        for writer in tuple(self._writers):
            writer.transport.abort()
        for task in tuple(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.server:
            await self.server.wait_closed()
        if self.server6:
            await self.server6.wait_closed()
        if self._directory:
            self._directory.cleanup()


# This trusted program runs in the private Linux network namespace. Its child
# bridges loopback to one mounted broker socket. Before exec, the payload gets
# a second seccomp filter denying Unix sockets, bind/listen and host IPC. It
# cannot use the bridge to bypass the broker's independently checked policy.
LINUX_PROXY_LAUNCH = r"""
import base64, ctypes, json, os, select, socket, struct, sys, threading
endpoint, token, filter_b64, environment_json, executable, *arguments = sys.argv[1:]
listener = socket.socket()
listener.bind(('127.0.0.1', 0))
listener.listen(32)
port = listener.getsockname()[1]
helper = os.fork()
if helper == 0:
    for descriptor in (0, 1, 2):
        os.close(descriptor)
    slots = threading.BoundedSemaphore(32)
    def bridge(client):
        remote = socket.socket(socket.AF_UNIX)
        try:
            remote.connect(endpoint)
            while True:
                ready, _, _ = select.select([client, remote], [], [], 30)
                if not ready:
                    return
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (remote if source is client else client).sendall(data)
        except OSError:
            pass
        finally:
            client.close()
            remote.close()
            slots.release()
    while True:
        slots.acquire()
        client, _ = listener.accept()
        threading.Thread(target=bridge, args=(client,), daemon=True).start()
listener.close()
raw = base64.b64decode(filter_b64)
if len(raw) % 8:
    raise RuntimeError('invalid payload filter')
class Program(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ushort), ('filter', ctypes.c_void_p)]
buffer = ctypes.create_string_buffer(raw)
program = Program(len(raw) // 8, ctypes.cast(buffer, ctypes.c_void_p))
libc = ctypes.CDLL(None, use_errno=True)
if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(program), 0, 0):
    raise OSError(ctypes.get_errno(), 'cannot restrict proxy payload')
environment = json.loads(environment_json)
value = f'http://sage:{token}@127.0.0.1:{port}'
for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
    environment[key] = value
environment['NO_PROXY'] = environment['no_proxy'] = ''
os.execve(executable, [executable, *arguments], environment)
"""
