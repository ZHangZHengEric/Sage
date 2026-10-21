"""Bounded HTTPS downloads with public DNS pinned to the TLS connection."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024


def import_error(message: str, *, conflict: bool = False) -> SageV2Error:
    return SageV2Error(RuntimeErrorInfo(
        code="server.skills.import.conflict" if conflict else "server.skills.import.validation",
        category=ErrorCategory.CONFLICT if conflict else ErrorCategory.VALIDATION,
        message=message,
    ))


def validate_https_url(url: str):
    try:
        parts = urlsplit(url)
        valid = (
            parts.scheme == "https" and parts.hostname and not parts.username
            and not parts.password and parts.port in {None, 443}
            and not parts.fragment and not any(ord(c) < 33 or c == "\\" for c in url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise import_error("请输入不含认证信息的 HTTPS 地址，仅支持 443 端口")
    return parts


def _public_address(host: str) -> str:
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise import_error("无法解析下载地址")
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        mapped = getattr(address, "ipv4_mapped", None)
        if not address.is_global or (mapped is not None and not mapped.is_global):
            raise import_error("在线导入不允许访问本机或私网地址")
    return str(addresses[0][4][0])


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str, timeout: float):
        self._tls_context = ssl.create_default_context()
        super().__init__(host, timeout=timeout, context=self._tls_context)
        self.address = address

    def connect(self):
        # Resolve exactly once; keep the original host for certificate validation/SNI.
        sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._tls_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def download_public_https(url: str, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> bytes:
    deadline = time.monotonic() + 60
    try:
        for _ in range(6):
            parts = validate_https_url(url)
            host = parts.hostname
            assert host is not None
            address = _public_address(host)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise import_error("下载超时，请重试")
            connection = _PinnedHTTPSConnection(host, address, min(15, remaining))
            try:
                target = parts.path or "/"
                if parts.query:
                    target += "?" + parts.query
                connection.request("GET", target, headers={
                    "User-Agent": "Sage-Skill-Importer", "Accept-Encoding": "identity",
                })
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location:
                        raise import_error("下载地址重定向无效")
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise import_error(f"下载失败（HTTP {response.status}），请检查地址和访问权限")
                size = response.getheader("Content-Length")
                if size and (not size.isdecimal() or int(size) > max_bytes):
                    raise import_error("下载文件超过大小限制")
                result = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise import_error("下载超时，请重试")
                    if connection.sock is not None:
                        connection.sock.settimeout(min(15, remaining))
                    chunk = response.read1(min(65536, max_bytes + 1 - len(result)))
                    if not chunk:
                        return bytes(result)
                    result.extend(chunk)
                    if len(result) > max_bytes:
                        raise import_error("下载文件超过大小限制")
            finally:
                connection.close()
        raise import_error("下载地址重定向次数过多")
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise import_error("无法下载文件，请检查 HTTPS 地址或稍后重试") from exc
