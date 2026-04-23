---
layout: default
title: 桌面应用架构
parent: 架构
nav_order: 2
description: "app/desktop/ 桌面端架构：本地后端、UI、Tauri 壳与与 sagents 的关系"
lang: zh
ref: architecture-app-desktop
---

{% include lang_switcher.html %}

# 桌面应用架构

`app/desktop/` 是 Sage 的桌面形态，特点是“本地优先”：内嵌一个本地的 FastAPI 后端 + 内嵌的 UI，外面套一层 Tauri / PyInstaller 打包，对用户呈现为一个可双击的桌面应用。

## 模块组成

```mermaid
flowchart TB
    subgraph 入口
        Entry[entry.py<br/>处理 frozen / SSL 证书]
    end

    subgraph G_Core ["本地后端 core/"]
        Main[main.py<br/>FastAPI app + uvicorn]
        Boot[bootstrap.py · lifecycle.py]
        DB[db_schema.py · migrations.py<br/>本地 SQLite]
        Sync[skill_sync.py<br/>内置技能 → 用户目录]
        UCtx[user_context.py<br/>桌面单用户身份注入]
        Routers[routers · 桌面路由]
        Services[services · 桌面服务]
    end

    subgraph 前端
        UI[ui/<br/>Vue 3 + Vite + Tailwind 独立工程]
        Tauri[tauri/<br/>Tauri 壳 · 托盘/菜单/系统集成]
    end

    subgraph 打包
        Spec[sage-desktop.spec<br/>PyInstaller 规格]
        Scripts[scripts/<br/>构建/打包脚本]
        Out[build/ · dist/<br/>构建产物]
    end

    Entry --> Main
    Main --> Boot
    Main --> Routers --> Services
    Boot --> DB
    Boot --> Sync
    Tauri --> UI
    Tauri -.启动.-> Entry
    Spec -.驱动.-> Out
    Scripts -.驱动.-> Out
```

## 启动链路

```mermaid
sequenceDiagram
    participant User as 用户
    participant Tauri as Tauri 壳
    participant UI as UI 静态资源
    participant Entry as entry.py
    participant Main as core/main.py
    participant Life as core/lifecycle.initialize_system
    participant SAgent

    User->>Tauri: 双击启动
    Tauri->>UI: 加载 ui/dist
    Tauri->>Entry: 启动桌面后端进程
    Entry->>Entry: frozen 模式修复 SSL 证书路径
    Entry->>Main: 调用 main()
    Main->>Main: 强制 AGENT_BROWSER_HEADED=1
    Main->>Main: 提前 import sagents.prompts
    Main->>Life: lifespan: initialize_system()
    Life-->>Life: 本地 DB → Tool/Skill → SessionManager
    UI->>Main: HTTP/SSE 请求<br/>带 X-Sage-Internal-UserId
    Main->>Main: inject_desktop_user_context 中间件
    Main->>SAgent: SAgent.run_stream(...)
    SAgent-->>UI: 流式 MessageChunk
```

## 与服务端架构的差异

| 维度 | `app/server/` | `app/desktop/` |
| --- | --- | --- |
| 多用户 | 是，完整鉴权 | 否，单用户，注入身份 |
| 持久化 | 多用户 DB / 对象存储 | 本地 SQLite + 用户目录文件 |
| 部署 | 容器/服务器 | 桌面安装包（PyInstaller + Tauri） |
| 浏览器自动化 | 默认 headless | 默认 headed（`AGENT_BROWSER_HEADED=1`） |
| 技能 | 平台级管理 | `skill_sync.py` 把内置技能同步到用户目录，可被用户编辑 |
| 启动入口 | `app/server/main.py` | `app/desktop/entry.py` → `app/desktop/core/main.py` |
| 鉴权中间件 | 完整 OAuth/JWT | `inject_desktop_user_context` 单用户注入 |

但两者最终都调用同一个 `sagents/` 运行时，行为差异主要来自：沙箱配置（桌面更倾向 `local`）、工具/技能注册集合不同、模型配置来源不同（桌面通常从本地 DB 读取用户填写的 API Key）。

## 桌面运行态依赖关系

```mermaid
flowchart LR
    User((用户)) --> TauriShell[Tauri 壳]
    TauriShell --> UIRender[UI 渲染]
    UIRender -->|HTTP/SSE localhost| LocalAPI[本地 FastAPI]
    LocalAPI --> SAgent
    LocalAPI --> LocalDB[(本地 SQLite/<br/>用户目录文件)]
    SAgent --> Sandbox[本地沙箱]
    SAgent --> Tools
    LocalAPI -.静态.-> UserSkills[(同步出来的技能目录)]
    Sync[skill_sync] -. 复制 .-> UserSkills
```

## Tauri 壳层职责

```mermaid
flowchart TB
    Tauri[Tauri 壳]
    Tauri --> Window[创建桌面窗口 + 加载 UI]
    Tauri --> Process[启动 / 监督<br/>PyInstaller 后端进程]
    Tauri --> Tray[系统托盘 / 菜单 / 自启动]
    Tauri --> Dialog[文件对话框 / 系统通知]
```

## 打包链路与关注点

```mermaid
flowchart LR
    SrcPy[Python 源码 + sagents/prompts/]
    SrcUI[ui/ 前端工程]
    SrcSkill[app/skills/ 内置技能]

    SrcUI -->|npm build| UIDist[ui/dist]
    SrcPy -->|PyInstaller<br/>sage-desktop.spec| Exec[sage-desktop 可执行]
    SrcSkill -->|打入 + skill_sync| UserDir[用户目录技能]
    UIDist --> Bundle[最终桌面安装包]
    Exec --> Bundle
    UserDir -.运行期.-> Bundle
```

打包的关键约束：

- `sagents/prompts/` 必须被 PyInstaller 显式收集（`main.py` 里有兜底 import）。
- 内置技能 `app/skills/` 需要被打入并通过 `skill_sync.py` 复制到用户目录。
- 证书路径要兼容 `_MEIPASS` 临时目录（`entry.py` 已处理）。
