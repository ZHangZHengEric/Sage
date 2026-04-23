---
layout: default
title: Server & Web App Architecture
parent: Architecture
nav_order: 1
description: "FastAPI app and Vue 3 web client under app/server/"
lang: en
ref: architecture-app-server
---

{% include lang_switcher.html %}

# Server & Web App Architecture

`app/server/` is the main, productized entry of Sage. It owns multi-user, web, agent management, knowledge base, observability and the rest of the platform surface. It is not a demo.

## Module Composition

```mermaid
flowchart TB
    subgraph Entry
        Main[main.py<br/>FastAPI app + uvicorn]
        Boot[bootstrap.py<br/>subsystem init/teardown]
        Life[lifecycle.py<br/>initialize_system orchestration]
        Sched[scheduler.py<br/>scheduled jobs]
    end

    subgraph G_Core ["Cross-cutting (core/)"]
        Auth[auth.py<br/>auth deps]
        Mid[middleware.py<br/>CORS / logging / request id]
        AdminBoot[bootstrap_admin.py<br/>built-in admin bootstrap]
    end

    subgraph G_Routers ["Routers (routers/)"]
        RChat[chat]
        RAgent[agent]
        RConv[conversation]
        RTask[task]
        RTool[tool / mcp]
        RSkill[skill]
        RKdb[kdb]
        RLLM[llm_provider]
        RAuth[auth / oauth2 / user]
        ROss[oss]
        RObs[observability]
        RSys[system / version]
    end

    subgraph G_Services ["Services (services/)"]
        SChat[chat]
        SAuth[auth]
        SUser[user.py]
        SAgent[agent_inherit.py]
        SOss[oss.py]
    end

    subgraph G_Web ["Frontend (web/)"]
        WebSrc[Vue 3 + Vite + Tailwind]
    end

    Main --> Mid
    Main --> Life
    Main --> RChat
    RChat --> SChat
    RAgent --> SAgent
    RAuth --> SAuth
    SChat --> SAgent
    Life --> Boot
    Boot --> AdminBoot
```

## Startup Path

```mermaid
sequenceDiagram
    participant CLI as python -m app.server.main
    participant Cfg as init_startup_config
    participant App as create_fastapi_app
    participant Life as lifecycle.initialize_system
    participant Uvi as uvicorn.Server

    CLI->>Cfg: read .env / startup config
    CLI->>Uvi: start_server(cfg)
    Uvi->>App: factory build FastAPI
    App->>App: register_middlewares · exception · routes
    Uvi->>Life: lifespan: initialize_system(cfg)
    Life-->>Life: DB → Obs → Clients → Tool/Skill → Session → Scheduler
    Uvi-->>CLI: listening on http://host:port
```

## Routers and Services

```mermaid
flowchart LR
    HTTP((HTTP/SSE request)) --> Router[routers/* router]
    Router -->|parse + auth| Service[services/* business orchestration]
    Service -->|build SAgent args| RT[sagents runtime]
    RT -->|MessageChunk stream| Service
    Service -->|SSE / JSON| HTTP

    Router -.read.-> Auth
    Router -.errors.-> ExcHandler[common exception handler]
```

Each router maps to one HTTP resource group; services hold the business orchestration:

| Router | Responsibility |
| --- | --- |
| `chat` | Streaming chat (SSE), the bridge from HTTP to `SAgent.run_stream` |
| `agent` | Agent CRUD + configuration |
| `conversation` | History, lists, favorites |
| `task` | Long-running / async tasks |
| `tool` / `mcp` | Tool and MCP server registration |
| `skill` | Skill packages |
| `kdb` | Knowledge base |
| `llm_provider` | Model provider configuration |
| `auth` / `oauth2` / `user` | Login, users, third-party OAuth2 (e.g. Lage) |
| `oss` | Object storage |
| `observability` | Observability data |
| `system` / `version` | System info, version |

## Boundary with sagents

```mermaid
flowchart TB
    subgraph Startup
        Init[lifecycle.initialize_system]
        Init --> ToolMgr[global ToolManager]
        Init --> SkillMgr[global SkillManager]
        Init --> SessMgr[global SessionManager]
        Init --> ObsMgr[ObservabilityManager]
    end

    subgraph Per Request
        Req[Incoming request]
        Req --> Pick[pick model + tool/skill subset + sandbox]
        Pick --> Build[build ToolProxy / SkillProxy / system_prefix]
        Build --> Call[SAgent.run_stream]
        Call --> Sse[turn into SSE / JSON Lines]
    end

    ToolMgr -.reused.-> Build
    SkillMgr -.reused.-> Build
    SessMgr -.reused.-> Call
```

The server does not re-implement agent logic. It assembles HTTP/SSE protocol, auth, user/agent config and model providers into `SAgent.run_stream` arguments. See [sagents Overview](ARCHITECTURE_SAGENTS_OVERVIEW.md).

## Web Client Structure

```mermaid
flowchart TB
    subgraph G_Src ["app/server/web/src"]
        Entry[main.js · App.vue]
        Router[router · vue-router]
        Stores[stores · Pinia]
        Api[api · HTTP/SSE clients]
        Comp[components · generic UI]
        Compose[composables · chat/SSE hooks]
        Views[views · page components]
        I18n[locales · i18n]
        Util[utils]
    end

    Entry --> Router --> Views
    Views --> Comp
    Views --> Compose
    Compose --> Api
    Stores -.state.-> Views
    Stores -.state.-> Compose
```

The frontend subscribes to chunks via SSE and renders them based on `MessageChunk.role` / `message_type` (text, tool calls, token usage, etc.).

## Deployment Shapes

- `python -m app.server.main` for development.
- `docker-compose.yml` / `docker/` images for production (recommended).

See [Configuration](CONFIGURATION.md) and [Getting Started](../applications/GETTING_STARTED.md).

## Extending: Add a New Router

The most common server-side extension is "add a new HTTP resource". Template:

```python
# app/server/routers/my_module.py
from fastapi import APIRouter, Depends
from app.server.core.auth import current_user

router = APIRouter(prefix="/api/my", tags=["my"])

@router.get("/ping")
async def ping(user=Depends(current_user)):
    return {"ok": True, "user_id": user.id}
```

```python
# Register in app/server/routers/__init__.py
from . import my_module

def register_routes(app):
    ...
    app.include_router(my_module.router)
```

Put business logic in `services/`. The router stays thin: parse, auth, format response.
