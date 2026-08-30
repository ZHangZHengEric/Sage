"""Decorator-backed V2 webpage and file retrieval Tool."""

from __future__ import annotations

import asyncio
import html
import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from sagents.v2.runtime.execution.sandbox import NetworkResult
from sagents.v2.tool import SideEffectLevel, ToolInvocation, tool
from sagents.v2.tool.plugins.official.runtime import OfficialToolRuntime


class WebTools:
    def __init__(self, runtime: OfficialToolRuntime) -> None:
        self.runtime = runtime

    @tool(
        description="Fetch webpage text or download remote files.",
        side_effect_level=SideEffectLevel.READ,
    )
    async def fetch_webpages(
        self,
        urls: list[str],
        invocation: ToolInvocation,
        max_length_per_url: int = 8000,
        timeout: int = 30,
        retries: int = 1,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        del session_id
        if isinstance(urls, str):
            urls = [urls]
        results = []
        for url in urls:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                results.append(
                    {"url": url, "status": "error", "error": "unsupported URL scheme"}
                )
                continue
            response = None
            error = None
            for attempt in range(max(0, retries) + 1):
                try:
                    response = await self.runtime.network_request(
                        url,
                        invocation,
                        timeout_seconds=max(1, timeout),
                        headers={"accept": "*/*"},
                    )
                    if response.status_code >= 400:
                        raise RuntimeError(f"HTTP {response.status_code}")
                    break
                except Exception as exc:  # policy/provider errors are per URL
                    error = str(exc)
                    if attempt < retries:
                        await asyncio.sleep(min(2**attempt, 4))
            if response is None:
                results.append({"url": url, "status": "error", "error": error})
                continue
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" in content_type or "text/plain" in content_type:
                text = _html_to_text(response.body.decode("utf-8", errors="replace"))
                results.append(
                    {
                        "url": url,
                        "final_url": response.final_url,
                        "status": "success",
                        "type": "text",
                        "content": text[: max(1, max_length_per_url)],
                        "truncated": len(text) > max_length_per_url,
                    }
                )
            else:
                filename = _filename(response, parsed)
                target = f"downloads/{filename}"
                path = await self.runtime.write_bytes(target, response.body, invocation)
                results.append(
                    {
                        "url": url,
                        "final_url": response.final_url,
                        "status": "success",
                        "type": "file",
                        "file_path": path,
                        "size": len(response.body),
                        "content_type": content_type,
                    }
                )
        return {"status": "success", "results": results}


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", "", value)
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _filename(response: NetworkResult, parsed) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", disposition, re.I)
    raw = unquote(match.group(1)) if match else PurePosixPath(parsed.path).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw or "download.bin")
    return safe[:200]
