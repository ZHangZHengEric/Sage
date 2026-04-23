---
layout: default
title: CLI, Examples & External Entries
parent: Architecture
nav_order: 3
description: "app/cli/, examples/, app/chrome-extension/, app/wiki/ and other lightweight entries"
lang: en
ref: architecture-app-others
---

{% include lang_switcher.html %}

# CLI, Examples & External Entries

Beyond the two productized shapes (`app/server/` and `app/desktop/`), Sage ships several lighter entries for different scenarios: dev iteration, minimal demos, third-party integrations, docs/wiki.

## Entry Map

```mermaid
flowchart TD
    User((User)) --> CLI[app/cli<br/>sage command]
    User --> Demo1[examples/sage_cli.py]
    User --> Demo2[examples/sage_demo.py<br/>Streamlit]
    User --> Demo3[examples/sage_server.py<br/>standalone FastAPI]
    User --> Browser[(Browser)]
    User --> Reader[Doc reader]

    Browser --> Ext[app/chrome-extension<br/>side panel]
    Browser --> Wiki[app/wiki<br/>static site]

    CLI --> SAgent
    Demo1 --> SAgent
    Demo2 --> SAgent
    Demo3 --> SAgent
    Ext -->|HTTP/SSE| Server[app/server<br/>deployed]
    Wiki -. static .-> Browser
```

## CLI: `app/cli/`

```mermaid
flowchart LR
    User -->|sage run / chat / doctor| Argparse[main.py · argparse]
    Argparse --> Service[service.py<br/>session orchestration]
    Service --> SAgent[sagents runtime]
    Service --> LocalFS[(local session files)]
```

Properties:

- Reuses `sagents/` directly without `app/server/`.
- Suitable for local dev, prompt iteration, runtime diagnostics.
- `sage doctor` checks environment (deps, model connectivity, sandbox).

See [CLI Guide](../applications/CLI.md) for commands.

## Examples: `examples/`

```mermaid
flowchart TB
    subgraph G_Ex ["examples/"]
        SCli[sage_cli.py<br/>minimal CLI]
        SDemo[sage_demo.py<br/>Streamlit demo]
        SSrv[sage_server.py<br/>standalone FastAPI]
        Helper[_example_support.py]
        Mcp[mcp_setting.json<br/>MCP demo config]
        Cfg1[preset_running_agent_config.json]
        Cfg2[preset_running_config.json]
        Build[build_exec/<br/>single-file build sample]
    end

    SCli --> SAgent
    SDemo --> SAgent
    SSrv --> SAgent
    SCli -.read.-> Helper
    SDemo -.read.-> Helper
    SSrv -.read.-> Helper
    SCli -.read.-> Mcp
    SCli -.read.-> Cfg1
    SCli -.read.-> Cfg2
```

When to use:

- Validate the minimal arg set required to drive sagents.
- Build a quick standalone demo without the full server.
- Use as a baseline PyInstaller build sample.

When not to use: anything requiring full product features (multi-user, KB, observability UI) — go with `app/server/`.

## Chrome Extension: `app/chrome-extension/`

```mermaid
flowchart LR
    Web[(Browsing pages)] --> ContentScript[content-script.js<br/>injected into page]
    Web --> SidePanel[sidepanel.html<br/>side-panel UI]
    SidePanel --> SidePanelJS[sidepanel.js]
    ContentScript --> SW[service-worker.js<br/>background]
    SidePanelJS --> SW
    SW -->|HTTP/SSE| Server[app/server<br/>deployed]
```

It does not embed sagents; it is a browser-side UI client that talks to a deployed `app/server/` over HTTP/SSE — effectively a "web client living in the side panel".

## Wiki / Static Docs: `app/wiki/`

```mermaid
flowchart LR
    SrcMd[Markdown content] --> Gen[generate-docs.js]
    Gen --> Site[Static site output]
    Site --> ServeUser[(Browser readers)]
```

`app/wiki/` is an internal product/operations wiki site. It has a different purpose from this `docs/` set:

- `docs/` (what you are reading): technical docs, bound to the current code.
- `app/wiki/`: business / product / tutorial content, can be hosted independently.

It is not part of the runtime, but it is one of the apps in the repo, so it lives in this chapter.

## Picking the Right Entry

```mermaid
flowchart TD
    Need[Need]
    Need --> P1{Full multi-user<br/>web product?} -->|yes| Server[app/server + web]
    Need --> P2{Single-machine /<br/>offline?} -->|yes| Desktop[app/desktop]
    Need --> P3{CLI / scripts?} -->|yes| CLI[app/cli]
    Need --> P4{Minimal demo /<br/>integration template?} -->|yes| Examples[examples/sage_*.py]
    Need --> P5{Browser side entry?} -->|yes| Ext[app/chrome-extension]
    Need --> P6{Product / tutorial<br/>content?} -->|yes| Wiki[app/wiki]
```
