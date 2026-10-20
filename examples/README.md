# Sage Examples

Examples are grouped by runtime version. Run commands from the repository root.

| Directory | Contents | Start here |
| --- | --- | --- |
| [v1](v1/README.md) | Legacy CLI, Streamlit demo, HTTP server, JSON presets and server build script | [v1 usage](v1/README.md) |
| [v2](v2/README.md) | SDK quickstart, host integration, tools/MCP, agent management, concurrency and optimization | [Offline host](v2/host/) |

Use Python 3.12+ for the current checkout. Install the project dependencies with
`python -m pip install -e .`; the v1 Streamlit demo also needs `streamlit`.
The `examples` tree is checkout content, so run these modules from the repository
root rather than expecting them in an installed wheel.

For a new integration, start with:

```bash
python -m examples.v2.host --offline
```

The [v2 index](v2/README.md) distinguishes offline examples, network/model calls,
and native media requirements. Configuration and debugging guides:
[English](../docs/en/architecture/sagents-host-development.md),
[中文](../docs/zh/architecture/sagents-host-development.md).
