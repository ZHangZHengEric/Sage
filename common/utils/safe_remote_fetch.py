"""服务端拉取公网 HTTP(S) URL 的字节流，带 SSRF 基线防护与大小上限。"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from typing import Tuple
from urllib.parse import urlparse, unquote


class SafeRemoteFetchError(ValueError):
    pass


_BLOCKED_HOST_SUFFIXES = (".localhost", ".local")


def parse_and_validate_public_http_url(raw: str):
    parsed = urlparse((raw or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise SafeRemoteFetchError("仅支持 http(s) URL")
    host = parsed.hostname
    if not host:
        raise SafeRemoteFetchError("无效的 URL")

    lowered = host.lower()
    if lowered in ("localhost", "0") or lowered.startswith("127."):
        raise SafeRemoteFetchError("不允许访问本地回环地址")
    if "::1" in lowered:
        raise SafeRemoteFetchError("不允许访问本地回环地址")
    if lowered.endswith(_BLOCKED_HOST_SUFFIXES):
        raise SafeRemoteFetchError("不允许访问保留主机名")

    return parsed


async def resolve_host_ips_non_private(hostname: str) -> None:
    def _worker():
        infos = socket.getaddrinfo(hostname, None)
        ips = []
        for item in infos:
            sockaddr = item[4]
            if not sockaddr:
                continue
            ips.append(sockaddr[0])

        if not ips:
            raise SafeRemoteFetchError("无法解析域名")

        for ip_str in ips:
            addr = ipaddress.ip_address(ip_str)
            if not addr.is_global:
                raise SafeRemoteFetchError("不允许访问非公网 IP")

    await asyncio.to_thread(_worker)


def filename_hint_from_response(url: str, content_disposition: str | None, content_type: str | None) -> str:
    if content_disposition:
        cd = content_disposition
        if "filename*=" in cd:
            mstar = re.search(
                r"filename\*\s*=\s*UTF-8''([^;]+)|filename\*\s*=\s*utf-8''([^;]+)",
                cd,
                flags=re.IGNORECASE,
            )
            if mstar:
                name = unquote((mstar.group(1) or mstar.group(2) or "").strip().strip('"').split(";")[0])
                if name:
                    return name[:240]
        m = re.search(r'filename=(?:"?)([^";]+)', cd, flags=re.IGNORECASE)
        if m:
            return unquote(m.group(1).strip('"'))[:240]

    path = urlparse(url).path
    tail = path.rsplit("/", 1)[-1].strip()
    if tail:
        tail = unquote(tail.split("?", 1)[0])
        if tail and tail not in {"/", "."}:
            return tail[-240:]
    ctype = (content_type or "").split(";")[0].strip().lower()
    if "jpeg" in ctype or ctype == "image/jpg":
        return "import.jpg"
    if "png" in ctype:
        return "import.png"
    if "webp" in ctype:
        return "import.webp"
    if "gif" in ctype:
        return "import.gif"
    return "import.bin"


async def fetch_http_url_bytes_bounded(url: str, max_bytes: int = 25 * 1024 * 1024) -> Tuple[bytes, str, str]:
    parsed = parse_and_validate_public_http_url(url)
    await resolve_host_ips_non_private(parsed.hostname)

    try:
        import httpx
    except ImportError as e:
        raise SafeRemoteFetchError("httpx 未安装，无法拉取远端资源") from e

    timeout = httpx.Timeout(45.0, connect=10.0)
    headers = {"User-Agent": "Sage-OssImport/1.0"}

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            ct = (resp.headers.get("content-type") or "").split(";")[0].strip() or "application/octet-stream"
            cd = resp.headers.get("content-disposition")
            cl = resp.headers.get("content-length")
            if cl is not None:
                try:
                    if int(cl) > max_bytes:
                        raise SafeRemoteFetchError("资源过大")
                except ValueError:
                    pass

            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise SafeRemoteFetchError("资源过大")
                chunks.append(chunk)

            body = b"".join(chunks)
            name = filename_hint_from_response(url, cd, ct)
            return body, ct, name
