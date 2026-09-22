---
layout: default
title: Desktop v2
nav_order: 2
lang: en
ref: v2-applications-DESKTOP
parent: Applications
---

{% include lang_switcher.html %}

# Desktop v2

## Start from source

Complete the [Python setup](GETTING_STARTED.md). Install Flutter with Dart `^3.12.2` and your platform's desktop toolchain:

```bash
cd app/desktop_v2
flutter pub get
flutter run -d macos
```

Use `-d windows` or `-d linux` for those targets. The managed Python sidecar starts automatically on loopback with a temporary port and bearer capability token. The integrated PTY terminal currently supports macOS and Linux.

## First task

1. Add a model route in Settings: protocol, endpoint, model ID, and API key.
2. Select that route for an Agent; configure its tools and Skills.
3. Start a conversation in Agent Workspace, or register a project directory.
4. Inspect files and tool progress; answer input and approval requests when needed.

Model routes support OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages. MCP connections discover tools when configured and enabled. Studio provides shared conversations with member-directed messages.

## Data and settings

| Location | Purpose |
| --- | --- |
| `~/sage/runtime` | Settings, catalogs, session index, and Session state |
| `~/sage/skills` | Imported Skills |
| `~/sage/agent_workspace` | Default shared Agent Workspace |

Settings save automatically. Model and Agent settings are not overridden by environment variables. For source debugging, the backend accepts `--data-root /absolute/path`. Registered projects keep their own file roots.

Desktop v2 does not import v1 data. Existing Tauri release installers follow their own release instructions; do not assume they are Flutter v2 builds.

[Component reference](https://github.com/ZHangZHengEric/Sage/blob/main/app/desktop_v2/README.md) · [Troubleshooting](../TROUBLESHOOTING.md)
