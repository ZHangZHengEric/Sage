"""Explicit manifest upgrades that preserve their source files."""

from pathlib import Path

import yaml


def migrate_manifest_v1(
    source: str | Path,
    target: str | Path | None = None,
    *,
    dry_run: bool = False,
) -> Path:
    """Generate a new sage/v2 manifest without overwriting the v1 source."""

    source_path = Path(source).expanduser().resolve()
    raw = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != "sage/v1":
        raise ValueError("manifest migration requires schema_version sage/v1")
    output = (
        Path(target).expanduser().resolve()
        if target is not None
        else source_path.with_name("sage.v2.yaml")
    )
    if output == source_path or output.exists():
        raise FileExistsError(f"manifest migration target already exists: {output}")
    migrated = dict(raw)
    migrated["schema_version"] = "sage/v2"
    old_runtime = dict(migrated.get("runtime") or {})
    capabilities = dict(old_runtime.pop("capabilities", {}) or {})
    aliases = {
        "session_store": "session.store",
        "memory_provider": "memory.provider",
        "session_memory_provider": "session-memory.provider",
        "tool_provider": "tool.provider",
        "tool_selection": "tool.selection-policy",
    }
    for old_key, capability in aliases.items():
        selection = old_runtime.pop(old_key, None)
        if selection is not None:
            capabilities[capability] = selection
    scheduler = old_runtime.pop("scheduler", None)
    if scheduler is not None:
        capabilities["execution.scheduler"] = {
            "plugin": "sage.scheduler.ephemeral",
            "config": scheduler,
        }
    migrated["runtime"] = {
        "preset": old_runtime.pop("preset", "standard"),
        "capabilities": capabilities,
        **old_runtime,
    }
    protocol_plugins = {
        "native": "sage.protocol.native",
        "ag_ui": "sage.protocol.ag-ui",
        "acp": "sage.protocol.acp",
        "a2a": "sage.protocol.a2a",
        "mcp": "sage.protocol.mcp",
    }
    migrated["interfaces"] = {
        name: {
            "plugin": value.get("plugin") or protocol_plugins.get(name, name),
            **value,
        }
        for name, declaration in (migrated.get("interfaces") or {}).items()
        for value in [dict(declaration or {})]
    }
    if not dry_run:
        output.write_text(
            yaml.safe_dump(migrated, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    return output
