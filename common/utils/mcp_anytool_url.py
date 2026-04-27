"""Rewrite built-in AnyTool streamable_http_url to the current backend port (common-only, no sagents)."""

from __future__ import annotations

from typing import Any, Dict


def coalesce_anytool_streamable_url(server_name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Point AnyTool MCP URLs at 127.0.0.1:<SAGE_PORT> when config still has a stale port."""
    out = dict(cfg)
    url = out.get("streamable_http_url") or out.get("url")
    kind = str(out.get("kind", "") or "").lower()
    if kind != "anytool" and not (
        isinstance(url, str) and "/api/mcp/anytool/" in url
    ):
        return out
    from common.services.mcp_service import _get_backend_port

    out["kind"] = "anytool"
    sn = (server_name or "").strip()
    out["streamable_http_url"] = (
        f"http://127.0.0.1:{_get_backend_port()}/api/mcp/anytool/{sn}"
    )
    return out
