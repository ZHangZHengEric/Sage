---

## layout: default
title: Architecture
nav_order: 4
has_children: true
description: "Repository and subsystem architecture overview, with sub-pages for apps and the sagents core runtime"
lang: en
ref: architecture

{% include lang_switcher.html %}

# Architecture

Sage is a layered codebase, not a single binary. The architecture chapter is split into two main tracks:

- **App architecture**: each user-facing entry (web server, desktop, CLI, examples, browser extension, etc.), its shape, startup path and boundary.
- **Core runtime `sagents/` architecture**: the session and agent engine shared by every app — the actual driver of "one conversation / one task".

This chapter has multiple sub-pages. This page is just the index and high-level map; details live in the children.

## Repository Map

```mermaid
flowchart TB
    subgraph G_App ["App Layer (app/)"]
        Server[server<br/>main FastAPI + Vue 3 web]
        Desktop[desktop<br/>desktop entry + local backend + UI]
        CLI[cli<br/>sage command]
        Ext[chrome-extension<br/>side panel]
        Skills[skills<br/>built-in skill packs]
        Wiki[wiki<br/>static site]
    end

    subgraph G_Ex ["Examples (examples/)"]
        DemoCLI[sage_cli.py]
        DemoUI[sage_demo.py · Streamlit]
        DemoSrv[sage_server.py · FastAPI]
    end

    subgraph G_Sagents ["Core Runtime (sagents/)"]
        Runtime[Session · Agent · Flow · Tool · Skill · Sandbox · Obs]
    end

    subgraph External
        MCP[mcp_servers · built-in MCP]
        Common[common · shared infra]
        Docs[docs · this site]
    end

    Server --> Runtime
    Desktop --> Runtime
    CLI --> Runtime
    DemoCLI --> Runtime
    DemoUI --> Runtime
    DemoSrv --> Runtime
    Ext -->|HTTP| Server
    Runtime --> MCP
    Runtime -.shared.-> Common
```



## High-Level Data Flow of One Conversation

```mermaid
flowchart LR
    UserIn((User input)) --> EntryApp[Some app entry]
    EntryApp -->|run_stream call| SAgent[SAgent entry]
    SAgent --> Sess[Session/SessionContext]
    Sess --> Flow[FlowExecutor + AgentFlow]
    Flow --> Agents[Specialized Agents]
    Agents --> LLM[Model layer]
    Agents --> Tools[Tool / Skill]
    Tools --> Sandbox[Sandbox]
    Sess --> Obs[Observability]
    Agents -->|stream of MessageChunk| EntryApp
    EntryApp -->|SSE/JSON| UserIn
```



## Sub-pages in this Chapter

App architecture (different app entries):

1. [Server & Web App Architecture](ARCHITECTURE_APP_SERVER.md)
2. [Desktop App Architecture](ARCHITECTURE_APP_DESKTOP.md)
3. [CLI, Examples & External Entries](ARCHITECTURE_APP_OTHERS.md)

Core runtime `sagents/` architecture (the heart of this chapter):

1. [sagents Overview](ARCHITECTURE_SAGENTS_OVERVIEW.md)
2. [Agent & Flow Orchestration](ARCHITECTURE_SAGENTS_AGENT_FLOW.md)
3. [Session & Context](ARCHITECTURE_SAGENTS_SESSION_CONTEXT.md)
4. [Tool & Skill System](ARCHITECTURE_SAGENTS_TOOL_SKILL.md)
5. [Sandbox, LLM Adapter & Observability](ARCHITECTURE_SAGENTS_SANDBOX_OBS.md)

## Reading Tips

```mermaid
flowchart TD
    Want[What do you want to do]

    Want --> A[Understand how a conversation runs]
    A --> A1[sagents Overview] --> A2[Agent + Flow] --> A3[Session + Context]

    Want --> B[Server integration / deployment]
    B --> B1[Server & Web App Architecture] --> B2[Configuration + HTTP API Reference]

    Want --> C[Extend with custom tool/MCP/skill/sub-agent]
    C --> C1[Tool & Skill System] --> C2[Agent + Flow extension points]

    Want --> D[Package the desktop app]
    D --> D1[Desktop App Architecture] --> D2[app/desktop/scripts]
```

