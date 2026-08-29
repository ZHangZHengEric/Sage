"""One-time, read-only import of Desktop v1 settings into the v2 catalog."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.desktop_v2.backend.catalog import (
    DesktopMcpRecord,
    DesktopModelProviderRecord,
)


@dataclass(frozen=True)
class LegacyDesktopSettings:
    model_providers: tuple[DesktopModelProviderRecord, ...] = ()
    mcp_connections: tuple[DesktopMcpRecord, ...] = ()


def read_legacy_desktop_settings(
    database: Path,
    *,
    target_user_id: str,
) -> LegacyDesktopSettings:
    """Read compatible v1 rows without initializing the legacy application."""

    if not database.is_file():
        return LegacyDesktopSettings()
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        providers = _read_model_providers(connection, target_user_id)
        mcp = _read_mcp_connections(connection, target_user_id)
        return LegacyDesktopSettings(providers, mcp)
    finally:
        connection.close()


def _matching_rows(
    connection: sqlite3.Connection,
    table: str,
    target_user_id: str,
) -> list[sqlite3.Row]:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if table not in tables:
        return []
    rows = list(connection.execute(f"SELECT * FROM {table}"))
    exact = [row for row in rows if str(row["user_id"] or "") == target_user_id]
    if exact:
        return exact
    if target_user_id != "default_user":
        return []
    aliases = {"", "desktop_default_user"}
    return [row for row in rows if str(row["user_id"] or "") in aliases]


def _read_model_providers(
    connection: sqlite3.Connection,
    target_user_id: str,
) -> tuple[DesktopModelProviderRecord, ...]:
    records = []
    for row in _matching_rows(connection, "llm_providers", target_user_id):
        try:
            raw_keys = json.loads(row["api_keys"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            raw_keys = []
        keys = [str(value).strip() for value in raw_keys if str(value).strip()]
        records.append(
            DesktopModelProviderRecord(
                id=str(row["id"]),
                user_id=target_user_id,
                name=str(row["name"]),
                # v1 invokes these routes through Chat Completions.
                protocol="openai-chat-completions",
                model=str(row["model"]),
                base_url=str(row["base_url"]),
                api_key=keys[0] if keys else "",
                supports_multimodal=bool(row["supports_multimodal"]),
                supports_structured_output=bool(row["supports_structured_output"]),
                is_default=bool(row["is_default"]),
                max_tokens=int(row["max_tokens"] or 8192),
                temperature=(
                    float(row["temperature"])
                    if row["temperature"] is not None
                    else None
                ),
                top_p=float(row["top_p"]) if row["top_p"] is not None else None,
                max_model_len=int(row["max_model_len"] or 128_000),
                extra={
                    "imported_from": "desktop-v1",
                    "presence_penalty": row["presence_penalty"],
                },
            )
        )
    return tuple(records)


def _read_mcp_connections(
    connection: sqlite3.Connection,
    target_user_id: str,
) -> tuple[DesktopMcpRecord, ...]:
    records = []
    for row in _matching_rows(connection, "mcp_servers", target_user_id):
        try:
            config: dict[str, Any] = json.loads(row["config"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        protocol = str(config.get("protocol") or "stdio")
        if protocol not in {"stdio", "sse", "streamable_http"}:
            continue
        records.append(
            DesktopMcpRecord(
                user_id=target_user_id,
                name=str(row["name"]),
                protocol=protocol,
                disabled=bool(config.get("disabled", False)),
                streamable_http_url=config.get("streamable_http_url")
                or config.get("url"),
                sse_url=config.get("sse_url"),
                api_key=config.get("api_key"),
                command=config.get("command"),
                args=tuple(str(value) for value in config.get("args") or ()),
                env={
                    str(key): str(value)
                    for key, value in (config.get("env") or {}).items()
                },
                kind=str(config.get("kind") or "external"),
                description=str(config.get("description") or ""),
                tools=tuple(
                    value
                    for value in (config.get("tools") or ())
                    if isinstance(value, dict)
                ),
                simulator=(
                    dict(config["simulator"])
                    if isinstance(config.get("simulator"), dict)
                    else {}
                ),
            )
        )
    return tuple(records)
