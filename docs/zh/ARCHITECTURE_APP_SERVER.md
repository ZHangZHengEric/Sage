---
layout: default
title: 服务端与 Web 应用架构
parent: 架构
nav_order: 1
description: "app/server/ 主 FastAPI 应用与 Vue 3 Web 客户端的架构"
lang: zh
ref: architecture-app-server
---

{% include lang_switcher.html %}

# 服务端与 Web 应用架构

`app/server/` 是 Sage 的主应用入口，承载多用户、Web、智能体管理、知识库、可观测性等完整能力。它是真正“产品级”的入口，而不是演示。

## 模块组成

```mermaid
flowchart TB
    subgraph 入口
        Main[main.py<br/>FastAPI app + uvicorn]
        Boot[bootstrap.py<br/>子系统 init/teardown]
        Life[lifecycle.py<br/>initialize_system 编排]
        Sched[scheduler.py<br/>定时任务]
    end

    subgraph G_Core ["公共能力 core/"]
        Auth[auth.py<br/>鉴权依赖]
        Mid[middleware.py<br/>CORS / 日志 / 请求 ID]
        AdminBoot[bootstrap_admin.py<br/>内置管理员初始化]
    end

    subgraph G_Routers ["路由 routers/"]
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

    subgraph G_Services ["服务 services/"]
        SChat[chat]
        SAuth[auth]
        SUser[user.py]
        SAgent[agent_inherit.py]
        SOss[oss.py]
    end

    subgraph G_Web ["前端 web/"]
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

## 启动链路

```mermaid
sequenceDiagram
    participant CLI as python -m app.server.main
    participant Cfg as init_startup_config
    participant App as create_fastapi_app
    participant Life as lifecycle.initialize_system
    participant Uvi as uvicorn.Server

    CLI->>Cfg: 读取 .env / 启动配置
    CLI->>Uvi: start_server(cfg)
    Uvi->>App: 工厂构造 FastAPI
    App->>App: register_middlewares · exception · routes
    Uvi->>Life: lifespan: initialize_system(cfg)
    Life-->>Life: DB → Obs → Clients → Tool/Skill → Session → Scheduler
    Uvi-->>CLI: 监听 http://host:port
```

## 路由与服务的协作

```mermaid
flowchart LR
    HTTP((HTTP/SSE 请求)) --> Router[routers/* 路由]
    Router -->|参数解析 + 鉴权| Service[services/* 服务编排]
    Service -->|构造 SAgent 入参| RT[sagents 运行时]
    RT -->|MessageChunk 流| Service
    Service -->|SSE / JSON| HTTP

    Router -.读.-> Auth
    Router -.异常.-> ExcHandler[common 异常处理器]
```

每个路由模块对应一组 HTTP 资源；服务层把“业务编排”从路由里抽出来：

| 路由模块 | 主要职责 |
| --- | --- |
| `chat` | 会话流式聊天接口（SSE），是 HTTP → `SAgent.run_stream` 的关键层 |
| `agent` | 智能体的 CRUD 与配置管理 |
| `conversation` | 会话历史、列表、收藏 |
| `task` | 长任务/异步任务相关接口 |
| `tool` / `mcp` | 工具与 MCP Server 注册管理 |
| `skill` | 技能包管理 |
| `kdb` | 知识库（Knowledge Base） |
| `llm_provider` | 模型供应商配置 |
| `auth` / `oauth2` / `user` | 登录、用户、第三方 OAuth2（如 Lage） |
| `oss` | 对象存储 |
| `observability` | 可观测性数据查询 |
| `system` / `version` | 系统信息、版本 |

## 与 sagents 的边界

```mermaid
flowchart TB
    subgraph 启动期
        Init[lifecycle.initialize_system]
        Init --> ToolMgr[全局 ToolManager]
        Init --> SkillMgr[全局 SkillManager]
        Init --> SessMgr[全局 SessionManager]
        Init --> ObsMgr[ObservabilityManager]
    end

    subgraph 请求期
        Req[一次请求]
        Req --> Pick[选模型 + 选工具/技能子集 + 选沙箱]
        Pick --> Build[构造 ToolProxy / SkillProxy / system_prefix]
        Build --> Call[SAgent.run_stream]
        Call --> Sse[转 SSE / JSON Lines]
    end

    ToolMgr -.被复用.-> Build
    SkillMgr -.被复用.-> Build
    SessMgr -.被复用.-> Call
```

服务端不重新实现智能体逻辑，只负责把 HTTP/SSE 协议、鉴权、用户/Agent 配置、模型供应商等组装成 `SAgent.run_stream` 的入参。详见 [sagents 总览](ARCHITECTURE_SAGENTS_OVERVIEW.md)。

## Web 客户端结构

```mermaid
flowchart TB
    subgraph G_Src ["app/server/web/src"]
        Entry[main.js<br/>App.vue]
        Router[router · vue-router]
        Stores[stores · Pinia]
        Api[api · HTTP/SSE 客户端]
        Comp[components · 通用组件]
        Compose[composables · 聊天流/SSE 钩子]
        Views[views · 页面级组件]
        I18n[locales · i18n]
        Util[utils]
    end

    Entry --> Router --> Views
    Views --> Comp
    Views --> Compose
    Compose --> Api
    Stores -.状态.-> Views
    Stores -.状态.-> Compose
```

前端通过 SSE 实时订阅消息分片，并按 `MessageChunk.role` / `message_type` 决定如何渲染（普通消息、工具调用、token 用量等）。

## 部署形态

- 直接 `python -m app.server.main` 启动（开发态）。
- 通过仓库提供的 `docker-compose.yml` / `docker/` 镜像启动（推荐生产）。

详见 [配置](CONFIGURATION.md) 与 [快速开始](GETTING_STARTED.md)。

## 二次开发：新增一个路由

服务端最常见的扩展是“加一个新的 HTTP 资源”，模板如下：

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
# app/server/routers/__init__.py 中注册
from . import my_module

def register_routes(app):
    ...
    app.include_router(my_module.router)
```

业务逻辑放进 `services/`，路由层只做参数解析、鉴权与响应封装。
