# Applications

```text
app/
  v1/
    cli/              Legacy command implementations
    desktop/          Legacy desktop host and UI
    server/           Legacy server and web UI
    chrome-extension/ Legacy browser bridge
    common/           Legacy application services, configuration and DAOs
  v2/
    cli/              V2 command implementations and configuration
    desktop/          Flutter client and Python host
    server/           Server API and web UI
  skills/             Packaged skill content
  wiki/               Packaged documentation content
```

Agent engines are in `sagents/v1` and `sagents/v2`. Independent MCP services are
in `mcp_servers`; AnyTool imports neither application nor agent engine.

`agent_workspace/` is existing local user data, not application source. Generated
caches, dependency directories, and builds are ignored by Git. Old `web/`
dependency artifacts were removed during the requested local cleanup.

See [source ownership and entry points](../docs/VERSIONED_LAYOUT.md).

Public launchers live outside `app`: `clients/cli` dispatches `sage` commands;
`clients/terminal` owns the Rust terminal client.

`app/skills` is the only built-in skill source. Former local root skills were
archived intact under `.sage/organization-backup/root-skills`; they are not shipped.
