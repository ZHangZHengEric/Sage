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

Complete the [Python setup](GETTING_STARTED.md). Install Node.js 22+ for the official streaming UI parser, then install Flutter with Dart `^3.12.2` and your platform's desktop toolchain:

```bash
cd app/v2/desktop
flutter pub get
flutter run -d macos
```

Use `-d windows` or `-d linux` for those targets. The managed Python sidecar starts automatically on loopback with a temporary port and bearer capability token. The integrated PTY terminal currently supports macOS and Linux.

## First task

1. Add a model route in Settings: protocol, endpoint, model ID, and API key.
2. Select that route for an Agent; configure its tools and Skills.
3. Start a conversation in Agent Workspace, or register a project directory.
4. Inspect files and tool progress; answer input and approval requests when needed.

Model routes support OpenAI Chat Completions, OpenAI Responses, Anthropic Messages, and Gemini GenerateContent. MCP connections discover tools when configured and enabled. Studio provides shared conversations with member-directed messages.

For native Gemini, select **Gemini GenerateContent**, set the endpoint to
`https://generativelanguage.googleapis.com/v1beta`, and enter the model ID and
Google API key. Run the capability check before saving. The adapter streams
native text and thought summaries, calls Sage tools, and preserves thought
signatures across tool calls and Session restarts. Google-hosted search and code
execution are not exposed by this adapter. Model support for thinking levels,
JSON output, and media is verified by the capability check.

## Data and settings

| Location | Purpose |
| --- | --- |
| `~/sage/runtime` | Settings, catalogs, session index, and Session state |
| `~/sage/skills` | Imported Skills |
| `~/sage/agent_workspace` | Default shared Agent Workspace |

Settings save automatically. Model and Agent settings are not overridden by environment variables. For source debugging, the backend accepts `--data-root /absolute/path`. Registered projects keep their own file roots.

Desktop v2 does not import v1 data. [Sage 2.1.1](https://github.com/ZHangZHengEric/Sage/releases/tag/v2.1.1) installers are built by GitHub Actions from the Flutter v2 client and include Python and the v2 backend. The older Tauri releases remain v1. macOS packages use ad-hoc signing and are not notarized; Windows packages are not code-signed.

[Component reference](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/desktop/README.md) · [Troubleshooting](../TROUBLESHOOTING.md)

## RSI and Agent versions

[RSI workflow, editable scope, audits and version confirmation](RSI.md).

## Interactive UI and presentations

Ask naturally: “Compare these three plans”, “Make a compound-interest calculator”, or “Create a four-page product presentation”. You do not need to mention OpenUI or write a protocol.

- For one ordinary chat, open the composer **+** menu and enable **Prefer interactive UI**.
- For new chats by default, enable **Settings → General → Interactive UI on by default**. Settings save automatically; the initial default is off. Existing chats keep their choice, and branches inherit their source chat's choice.
- Enabled chats preload the complete built-in `sage-openui` Skill into the first model context without a loading tool call. Disabled chats select UI or prose automatically; an explicit text request is respected.

Sage uses the official [OpenUI](https://github.com/thesysdev/openui) streaming parser and its own native Flutter Glass renderer, with light/dark themes and 31 registered component types. The renderer updates for every incoming text chunk; token-by-token cadence depends on the model provider. Inputs become usable after validation and completion. Calculators and numeric chart bindings update locally, while a form button sends the values as the next user turn. Computed results can feed further calculations and charts through acyclic dependencies. If final validation fails, the existing preview remains visible with an incomplete status and submission disabled.

Presentations stream into native 16:9 pages with navigation, thumbnails and fullscreen mode. After validation, export the same document to editable PPTX and open it in PowerPoint or Keynote. Supported slide blocks are text, metrics, tables and literal-data charts. PPTX import, freeform editing and animation are not included. This is Sage's own integration, not the full upstream renderer or OpenUI Cloud Reports API. These features are included in the 2.1.1 desktop packages.

Local-only input interfaces do not require submit buttons. Computed results and bound charts update on input changes; a submit button is a separate handoff to the assistant, not a recalculation control.

Local progress tracking supports explicit `Computed` operations: `count` counts selected checkbox options; `ratioPercent` returns completed / total * 100. `Progress` can bind numeric fields or computed results. Updates remain local. `sum` does not coerce selection arrays; the existing `percent` operation retains base * rate / 100 semantics.

Read [Streaming UI: from an answer to an interface](STREAMING_UI.md) for examples and the rendering workflow.
