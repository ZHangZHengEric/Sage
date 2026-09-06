from __future__ import annotations

from sagents.v2.tool.plugins.mcp import McpServerConfig, McpToolPlugin

from app.server_v2.core.errors import ServerV2Error
from app.server_v2.domain.catalog import McpServerRecord


def to_mcp_config(record: McpServerRecord, *, required: bool = False) -> McpServerConfig:
    try:
        return McpServerConfig(
            name=record.name,
            protocol=record.protocol,  # type: ignore[arg-type]
            url=record.url,
            api_key=record.api_key,
            command=record.command,
            args=tuple(record.args),
            env=dict(record.env),
            required=required,
        )
    except Exception as exc:
        raise ServerV2Error("validation", f"invalid mcp {record.name}: {exc}") from exc


async def discover_mcp_tools(config: McpServerConfig) -> list[str]:
    plugin = McpToolPlugin((config,))
    definitions = await plugin.list_tools(run_id="discover")
    errors = plugin.discovery_errors()
    if config.name in errors:
        info = errors[config.name]
        raise ServerV2Error("validation", info.message)
    return [item.name for item in definitions]


def mcp_plugin(records: list[McpServerRecord]) -> McpToolPlugin | None:
    servers = tuple(to_mcp_config(item, required=False) for item in records if not item.disabled)
    if not servers:
        return None
    return McpToolPlugin(servers)
