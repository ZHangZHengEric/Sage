"""Transport rules for a public multi-tenant MCP registry.

Only network transports exist here, and a server that cannot be reached is
rejected where the tenant can see the error — not at chat time.
"""

from __future__ import annotations

import pytest

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.catalog import (
    McpServerRecord,
    UserCatalog,
    empty_catalog,
    upsert_mcp,
)
from app.server_v2.infrastructure.mcp import mcp_server_configs


def _payload(**overrides) -> dict[str, object]:
    return {
        "name": "files",
        "protocol": "streamable_http",
        "url": "https://mcp.example.com/files",
        **overrides,
    }


def test_stdio_is_not_a_registrable_transport():
    with pytest.raises(ServerV2Error) as exc:
        upsert_mcp(empty_catalog(), _payload(protocol="stdio", url=None))

    assert exc.value.reason == "validation"


def test_a_network_server_without_a_url_is_rejected_at_save():
    for url in (None, "", "   ", "not-a-url", "file:///etc/passwd"):
        with pytest.raises(ServerV2Error) as exc:
            upsert_mcp(empty_catalog(), _payload(url=url))
        assert exc.value.reason == "validation"


def test_a_valid_server_keeps_its_transport():
    record, catalog = upsert_mcp(empty_catalog(), _payload(protocol="sse"))

    assert record.protocol == "sse"
    assert record.url == "https://mcp.example.com/files"
    assert [item.name for item in catalog.mcp_servers] == ["files"]


def test_a_legacy_stdio_row_is_skipped_instead_of_breaking_the_catalog():
    catalog = UserCatalog.model_validate(
        {
            "agents": [{"id": "main", "name": "Main"}],
            "mcp_servers": [
                {"name": "local", "protocol": "stdio", "command": "npx"},
                {
                    "name": "remote",
                    "protocol": "streamable_http",
                    "url": "https://mcp.example.com/remote",
                },
            ],
        }
    )

    assert [item.id for item in catalog.agents] == ["main"]
    assert [item.name for item in catalog.mcp_servers] == ["remote"]


def test_one_unusable_server_does_not_take_down_the_others():
    good = McpServerRecord(
        name="remote", protocol="sse", url="https://mcp.example.com/remote"
    )
    broken = good.model_construct(name="broken", protocol="sse", url=None)

    configs = mcp_server_configs([broken, good])

    assert [item.name for item in configs] == ["remote"]
